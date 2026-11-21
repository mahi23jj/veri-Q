"""End-to-end orchestration with real telemetry ingestion and evidence."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.runtime import (
    CheckpointWait,
    FaultEvent,
    RunnerEnvironment,
    RunnerWorker,
)
from app.models.runtime import TestCaseRun as RunRow
from app.runtime.finalizer import Finalizer
from app.runtime.simulated_backend import SimulatedRuntime
from app.runtime.supervisor import RunnerSupervisor
from app.services import runtime_service
from tests.runtime_helpers import (
    ScriptedExecutor,
    Telemetry,
    app_for,
    build_plan,
    case_for,
    orchestrator,
    start_run,
)


def _recovering_behaviour(db: Session, client: TestClient, fixture: dict):
    target_app = app_for(db, fixture)
    telemetry = Telemetry(db, target_app)

    def on_submit(executor, submission, run_id):
        telemetry.attempt(
            run_id=run_id, celery_task_id=submission.task_id, status="failed", retry=True
        )
        telemetry.attempt(
            run_id=run_id, celery_task_id=submission.task_id, status="succeeded"
        )

    return on_submit


# ---------------------------------------------------------------------------
# PASS path
# ---------------------------------------------------------------------------


def test_approved_case_runs_through_recovery_and_is_cleaned_up(
    client: TestClient, db_session: Session
):
    fixture = build_plan(client, "runtime-pass")
    case = case_for(fixture, "dependency_timeout")
    run = start_run(db_session, fixture, case)

    backend = SimulatedRuntime(worker_instance_id="sim-pass")
    executor = ScriptedExecutor(
        lambda _executor, submission, run_id: Telemetry(
            db_session, app_for(db_session, fixture)
        ).attempt(run_id=run_id, celery_task_id=submission.task_id, status="failed", retry=True)
    )
    # First attempt fails and requests a retry, second attempt succeeds.
    original = executor._on_submit

    def script(inner_executor, submission, run_id):
        original(inner_executor, submission, run_id)
        Telemetry(db_session, app_for(db_session, fixture)).attempt(
            run_id=run_id, celery_task_id=submission.task_id, status="succeeded"
        )

    executor._on_submit = script

    result = orchestrator(
        db_session, backend=backend, executor_factory=lambda _broker: executor
    ).execute(run.id)

    assert result.lifecycle_state == "COMPLETED"
    assert result.verdict == "PASS", result.verdict_detail
    assert result.finished_at is not None

    recovery = runtime_service.get_recovery(db_session, result)
    assert recovery is not None
    assert recovery.attempt_count == 2
    assert recovery.retry_request_count == 1
    assert recovery.subsequent_attempt_count == 1
    assert recovery.fault_activated is True
    assert recovery.final_execution_state == "SUCCEEDED"
    assert recovery.evidence_complete is True

    faults = runtime_service.list_fault_events(db_session, result)
    states = [event.state for event in faults]
    assert states[0] == "PREPARING"
    assert "ACTIVE" in states
    assert states[-1] == "RELEASED"

    environment = runtime_service.get_environment(db_session, result)
    assert environment is not None
    assert environment.provisioning_state == "READY"
    assert environment.runtime_type == "simulated"
    assert environment.cleanup_state == "CLEANED"
    assert environment.readiness["ok"] is True

    workers = runtime_service.list_workers(db_session, result)
    assert len(workers) == 1
    assert workers[0].lifecycle_state == "STOPPED"
    assert backend.state.cleaned == [environment.namespace]

    events = [event.event_type for event in runtime_service.list_runtime_events(db_session, result)]
    assert "message_submitted" in events
    assert "worker_ready" in events
    assert "finalized" in events

    # The submission carried the test-run correlation and the frozen input.
    assert executor.submissions[0]["operation_id"] == str(result.id)
    assert executor.submissions[0]["queue"] == "veriq.test"
    assert executor.closed is True


def test_task_input_rewritten_to_the_http_fault_proxy(client: TestClient, db_session: Session):
    fixture = build_plan(client, "runtime-proxy-input")
    case = case_for(fixture, "dependency_timeout")
    run = start_run(db_session, fixture, case)

    executor = ScriptedExecutor(
        lambda _executor, submission, run_id: Telemetry(
            db_session, app_for(db_session, fixture)
        ).attempt(run_id=run_id, celery_task_id=submission.task_id, status="succeeded")
    )
    orchestrator(db_session, executor_factory=lambda _broker: executor).execute(run.id)

    submitted = executor.submissions[0]["payload"]
    assert submitted["url"].startswith("http://127.0.0.1:")
    assert submitted["url"].endswith("/quote")
    assert "127.0.0.1:9" not in submitted["url"]


# ---------------------------------------------------------------------------
# FAIL / INCONCLUSIVE / INVALID_RUN / ERROR
# ---------------------------------------------------------------------------


def test_retry_without_second_attempt_fails(client: TestClient, db_session: Session):
    fixture = build_plan(client, "runtime-retry-lost")
    case = case_for(fixture, "dependency_timeout")
    run = start_run(db_session, fixture, case)

    executor = ScriptedExecutor(
        lambda _executor, submission, run_id: Telemetry(
            db_session, app_for(db_session, fixture)
        ).attempt(run_id=run_id, celery_task_id=submission.task_id, retry=True)
    )
    result = orchestrator(db_session, executor_factory=lambda _broker: executor).execute(run.id)

    assert result.lifecycle_state == "COMPLETED"
    assert result.verdict == "FAIL"
    codes = {reason["code"] for reason in result.verdict_detail["reasons"]}
    assert "RETRY_WITHOUT_SUBSEQUENT_ATTEMPT" in codes
    # Lifecycle and verdict stay separate.
    assert result.lifecycle_state != "FAILED"


def test_missing_telemetry_is_inconclusive(client: TestClient, db_session: Session):
    fixture = build_plan(client, "runtime-no-telemetry")
    case = case_for(fixture, "dependency_timeout")
    run = start_run(db_session, fixture, case)

    executor = ScriptedExecutor(lambda *_args: None)
    result = orchestrator(
        db_session,
        executor_factory=lambda _broker: executor,
        settings={"execution_timeout": 1},
    ).execute(run.id)

    assert result.verdict == "INCONCLUSIVE"
    recovery = runtime_service.get_recovery(db_session, result)
    assert recovery is not None
    assert recovery.attempt_count == 0
    assert "TASK_ATTEMPT_NOT_OBSERVED" in recovery.missing_evidence


def test_checkpoint_fault_that_never_triggers_is_an_invalid_run(
    client: TestClient, db_session: Session
):
    fixture = build_plan(
        client,
        "runtime-checkpoint-timeout",
        task_name="app.tasks.slow_operation",
        scenarios=(),
        checkpoints=("before_slow_work",),
        checkpoint_scenarios={"before_slow_work": ("worker_termination",)},
        recovery={"expect_redelivery": True, "expect_retry": True, "settle_seconds": 1},
    )
    case = case_for(fixture, "worker_termination", checkpoint_name="before_slow_work")
    run = start_run(db_session, fixture, case)

    # The task completes without ever reaching the selected checkpoint.
    executor = ScriptedExecutor(
        lambda _executor, submission, run_id: Telemetry(
            db_session,
            app_for(db_session, fixture),
            task_name="app.tasks.slow_operation",
        ).attempt(run_id=run_id, celery_task_id=submission.task_id, status="succeeded")
    )
    result = orchestrator(
        db_session,
        executor_factory=lambda _broker: executor,
        settings={"fault_activation_timeout": 0.2, "execution_timeout": 1},
    ).execute(run.id)

    assert result.verdict == "INVALID_RUN", result.verdict_detail
    states = [event.state for event in runtime_service.list_fault_events(db_session, result)]
    assert "SKIPPED" in states
    assert "ACTIVE" not in states


def test_checkpoint_activation_happens_while_the_checkpoint_is_reported(
    client: TestClient, db_session: Session
):
    fixture = build_plan(
        client,
        "runtime-checkpoint-termination",
        task_name="app.tasks.slow_operation",
        scenarios=(),
        checkpoints=("before_slow_work",),
        checkpoint_scenarios={"before_slow_work": ("worker_termination",)},
        recovery={
            # A terminated worker is redelivered by the broker; the application
            # itself never gets to request a retry, so that is not required.
            "expect_redelivery": True,
            "settle_seconds": 1,
            "max_attempts": 3,
        },
    )
    case = case_for(fixture, "worker_termination", checkpoint_name="before_slow_work")
    run = start_run(db_session, fixture, case)
    telemetry = Telemetry(
        db_session, app_for(db_session, fixture), task_name="app.tasks.slow_operation"
    )
    observed: dict[str, object] = {}

    def on_submit(_executor, submission, run_id):
        # Attempt 1 reaches the checkpoint and is terminated there.
        telemetry.attempt(
            run_id=run_id,
            celery_task_id=submission.task_id,
            checkpoints=("before_slow_work",),
            status="failed",
        )
        wait = db_session.scalar(
            select(CheckpointWait).where(CheckpointWait.test_case_run_id == run_id)
        )
        observed["checkpoint_state"] = wait.state if wait else None
        activation = db_session.scalar(
            select(FaultEvent).where(
                FaultEvent.test_case_run_id == run_id, FaultEvent.state == "ACTIVE"
            )
        )
        observed["activation_event_persisted_yet"] = activation is not None
        worker = db_session.scalar(
            select(RunnerWorker).where(RunnerWorker.test_case_run_id == run_id)
        )
        observed["worker_state_at_checkpoint"] = worker.lifecycle_state if worker else None
        # Redelivery: a second attempt runs the same logical job.
        telemetry.attempt(
            run_id=run_id, celery_task_id=str(uuid.uuid4()), status="succeeded"
        )

    executor = ScriptedExecutor(on_submit)
    result = orchestrator(db_session, executor_factory=lambda _broker: executor).execute(run.id)

    assert observed["checkpoint_state"] == "ACKNOWLEDGED", observed
    # The worker was already terminated while the checkpoint report was being
    # answered: activation is synchronous, the evidence row is persisted by the
    # runner immediately afterwards (single writer).
    assert observed["worker_state_at_checkpoint"] == "TERMINATED"
    assert observed["activation_event_persisted_yet"] is False
    assert result.verdict == "PASS", result.verdict_detail
    states = [event.state for event in runtime_service.list_fault_events(db_session, result)]
    assert "ACTIVE" in states
    recovery = runtime_service.get_recovery(db_session, result)
    assert recovery.attempt_count == 2
    termination = [
        event
        for event in runtime_service.list_runtime_events(db_session, result)
        if event.event_type == "worker_terminated"
    ]
    assert termination and termination[0].source == "RUNNER"


def test_worker_start_failure_is_a_runner_error_not_an_app_failure(
    client: TestClient, db_session: Session
):
    fixture = build_plan(client, "runtime-worker-fail")
    case = case_for(fixture, "dependency_timeout")
    run = start_run(db_session, fixture, case)

    result = orchestrator(
        db_session,
        backend=SimulatedRuntime(worker_start_error="no container capacity"),
        executor_factory=lambda _broker: ScriptedExecutor(lambda *_a: None),
    ).execute(run.id)

    assert result.verdict == "ERROR", result.verdict_detail
    assert result.lifecycle_state == "FAILED"
    assert "no container capacity" in (result.error_message or "")
    environment = runtime_service.get_environment(db_session, result)
    assert environment.cleanup_state == "CLEANED"


def test_environment_readiness_failure_is_a_runner_error(
    client: TestClient, db_session: Session
):
    fixture = build_plan(client, "runtime-readiness-fail")
    case = case_for(fixture, "dependency_timeout")
    run = start_run(db_session, fixture, case)

    result = orchestrator(
        db_session,
        backend=SimulatedRuntime(readiness_failures=("database_reachable",)),
        executor_factory=lambda _broker: ScriptedExecutor(lambda *_a: None),
    ).execute(run.id)

    assert result.verdict == "ERROR"
    environment = runtime_service.get_environment(db_session, result)
    assert environment.provisioning_state == "FAILED"
    assert "database" in (environment.error or "").lower()


def test_configuration_drift_blocks_execution(client: TestClient, db_session: Session):
    fixture = build_plan(client, "runtime-drift")
    case = case_for(fixture, "dependency_timeout")
    run = start_run(db_session, fixture, case)

    adapters = client.get(f"/api/v1/applications/{fixture['app_id']}/adapters").json()
    for adapter in adapters:
        if adapter["adapter_type"] == "http":
            client.delete(
                f"/api/v1/applications/{fixture['app_id']}/adapters/{adapter['id']}"
            )

    executor = ScriptedExecutor(lambda *_a: None)
    result = orchestrator(
        db_session, executor_factory=lambda _broker: executor
    ).execute(run.id)

    assert result.verdict == "INVALID_RUN", result.verdict_detail
    codes = {reason["code"] for reason in result.verdict_detail["reasons"]}
    assert "ADAPTER_NOT_CONFIGURED" in codes
    assert executor.submissions == []
    assert result.lifecycle_state == "FAILED"


def test_cancellation_finalizes_without_a_verdict_of_failure(
    client: TestClient, db_session: Session
):
    fixture = build_plan(client, "runtime-cancel")
    case = case_for(fixture, "dependency_timeout")
    run = start_run(db_session, fixture, case)
    runtime_service.request_cancel(db_session, run)

    executor = ScriptedExecutor(lambda *_a: None)
    result = orchestrator(db_session, executor_factory=lambda _broker: executor).execute(run.id)

    assert result.lifecycle_state == "CANCELLED"
    assert result.verdict == "INCONCLUSIVE"
    assert result.verdict_detail["reasons"][0]["code"] == "RUN_CANCELLED"
    assert executor.submissions == []
    # Cancelled before provisioning: finalization still ran and recorded it.
    events = [event.event_type for event in runtime_service.list_runtime_events(db_session, result)]
    assert "finalized" in events
    assert runtime_service.get_environment(db_session, result) is None


# ---------------------------------------------------------------------------
# Finalization
# ---------------------------------------------------------------------------


def test_finalization_is_idempotent_and_preserves_the_verdict(
    client: TestClient, db_session: Session
):
    fixture = build_plan(client, "runtime-finalize")
    case = case_for(fixture, "dependency_timeout")
    run = start_run(db_session, fixture, case)

    backend = SimulatedRuntime()
    supervisor = RunnerSupervisor(backend=backend)
    finalizer = Finalizer(backend=backend, supervisor=supervisor)
    environment = RunnerEnvironment(
        test_case_run_id=run.id,
        runtime_type="simulated",
        namespace="veriq-finalize",
        provisioning_state="READY",
        cleanup_state="CLEANED",
        container_refs=[],
        proxy_refs={},
    )
    db_session.add(environment)
    run.verdict = "FAIL"
    run.verdict_detail = {"verdict": "FAIL", "reasons": []}
    db_session.commit()

    first = finalizer.finalize(
        db_session, run=run, final_state="COMPLETED", reason="completed"
    )
    second = finalizer.finalize(
        db_session, run=run, final_state="COMPLETED", reason="completed"
    )

    assert first.clean is True
    assert second.clean is True
    db_session.refresh(run)
    assert run.verdict == "FAIL"
    assert run.lifecycle_state == "COMPLETED"


def test_runs_are_isolated_between_cases(client: TestClient, db_session: Session):
    fixture = build_plan(
        client,
        "runtime-isolation",
        scenarios=("dependency_timeout", "database_connection_interruption"),
    )
    first_case = case_for(fixture, "dependency_timeout")
    second_case = case_for(fixture, "database_connection_interruption")

    first_run = start_run(db_session, fixture, first_case)
    second_run = start_run(db_session, fixture, second_case)

    for run, case in ((first_run, first_case), (second_run, second_case)):
        executor = ScriptedExecutor(lambda *_a: None)
        orchestrator(
            db_session,
            backend=SimulatedRuntime(),
            executor_factory=lambda _broker: executor,
            settings={"execution_timeout": 1},
        ).execute(run.id)

    environments = list(
        db_session.scalars(
            select(RunnerEnvironment).where(
                RunnerEnvironment.test_case_run_id.in_([first_run.id, second_run.id])
            )
        ).all()
    )
    assert len(environments) == 2
    assert len({environment.namespace for environment in environments}) == 2
    assert all(environment.cleanup_state == "CLEANED" for environment in environments)


def test_second_active_run_of_the_same_case_is_rejected(
    client: TestClient, db_session: Session
):
    fixture = build_plan(client, "runtime-active-guard")
    case = case_for(fixture, "dependency_timeout")
    run = start_run(db_session, fixture, case)

    import pytest

    with pytest.raises(runtime_service.ActiveRunError):
        runtime_service.start_case_run(
            db_session,
            app_for(db_session, fixture),
            plan_id=uuid.UUID(fixture["plan"]["id"]),
            case_id=uuid.UUID(case["id"]),
        )

    # Cleanup the pending run so the shared test database stays consistent.
    db_session.delete(db_session.get(RunRow, run.id))
    db_session.commit()
