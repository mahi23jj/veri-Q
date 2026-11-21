"""Shared helpers for the runtime test suite."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import TargetApp
from app.runtime.execution import SubmissionResult
from app.runtime.orchestrator import OrchestratorSettings, TestOrchestrator
from app.runtime.simulated_backend import SimulatedRuntime
from app.schemas.observation import TaskExecutionEventCreate
from app.services import discovery_service, observation_service, runtime_service
from tests import planning_helpers as ph

TASK_NAME = "app.tasks.fetch_reference_data"
ALL_SCENARIOS = (
    "dependency_timeout",
    "successful_operation_lost_response",
    "duplicate_message_delivery",
    "database_connection_interruption",
    "worker_termination",
)

SIMULATED_PROFILE: dict[str, Any] = {
    "runtime_type": "simulated",
    "image": "veriq-celery-target-app:test",
    "queue": "veriq.test",
    "concurrency": 1,
    "broker_image": "redis:7-alpine",
    "database_image": "postgres:16-alpine",
    "env": {"TARGET_SQLITE_PATH": "/tmp/veriq-target.db"},
    "http": {"input_field": "url", "advertised_host": "127.0.0.1"},
    "database": {"url_env": "TARGET_DATABASE_URL"},
}

FAST_SETTINGS = dict(
    provisioning_timeout=5,
    worker_startup_timeout=5,
    fault_activation_timeout=1,
    execution_timeout=3,
    recovery_timeout=5,
    finalization_timeout=5,
    total_timeout=40,
    api_base_url="http://testserver",
    poll_interval=0.02,
)


def recovery_block(**overrides: Any) -> dict[str, Any]:
    block = {
        "max_attempts": 3,
        "per_attempt_timeout_seconds": 10,
        "recovery_deadline_seconds": 30,
        "expected_terminal_state": "SUCCEEDED",
        "expect_retry": True,
        "settle_seconds": 1,
    }
    block.update(overrides)
    return block


def contract_payload(*, recovery: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "safe_input": {"url": "http://127.0.0.1:9/quote", "timeout_seconds": 1},
        "effect_measurements": [],
        "assertions": [
            {
                "id": "execution_outcome",
                "description": "Execution reaches the expected terminal state",
                "type": "execution_status",
                "expected": "SUCCEEDED",
            }
        ],
        "cleanup": {"mode": "fixture_managed", "description": "test fixture"},
        "recovery": recovery or recovery_block(),
    }


def build_plan(
    client: TestClient,
    name: str,
    *,
    task_name: str = TASK_NAME,
    scenarios: tuple[str, ...] = ("dependency_timeout",),
    recovery: dict[str, Any] | None = None,
    checkpoints: tuple[str, ...] = (),
    checkpoint_scenarios: dict[str, tuple[str, ...]] | None = None,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create an approved plan revision with one executable case per scenario."""
    app_id, api_key = ph.register_app(client, name)
    task = ph.discover_task(client, api_key, task_name)
    http_adapter = ph.configure_adapter(
        client,
        app_id,
        name="http-sandbox",
        adapter_type="http",
        triggers=("timeout_simulation", "lost_response_simulation"),
    )
    ph.configure_adapter(
        client,
        app_id,
        name="db-sandbox",
        adapter_type="database",
        triggers=("connection_interruption",),
    )
    ph.configure_adapter(
        client,
        app_id,
        name="broker-sandbox",
        adapter_type="broker",
        triggers=("duplicate_delivery",),
    )
    ph.create_contract(
        client, app_id, task["id"], contract_payload(recovery=recovery)
    )

    for scenario_id in ALL_SCENARIOS:
        ph.select_task_scenario(
            client, app_id, task["id"], scenario_id, enabled=scenario_id in scenarios
        )

    discovered: dict[str, dict] = {}
    for checkpoint in checkpoints:
        response = ph.report_checkpoint(
            client, api_key, task_name=task_name, checkpoint=checkpoint
        )
        assert response.status_code == 201, response.text
    checkpoints_response = client.get(f"/api/v1/applications/{app_id}/checkpoints")
    assert checkpoints_response.status_code == 200, checkpoints_response.text
    for checkpoint in checkpoints_response.json():
        discovered[checkpoint["name"]] = checkpoint

    # Only these scenarios support checkpoint-triggered testing.
    checkpoint_capable = (
        "duplicate_message_delivery",
        "database_connection_interruption",
        "worker_termination",
    )
    for checkpoint_name, scenario_ids in (checkpoint_scenarios or {}).items():
        checkpoint = discovered[checkpoint_name]
        ph.enable_checkpoint(client, app_id, checkpoint["id"])
        for scenario_id in checkpoint_capable:
            ph.select_checkpoint_scenario(
                client,
                app_id,
                checkpoint["id"],
                scenario_id,
                enabled=scenario_id in scenario_ids,
            )

    plan = ph.create_plan(client, app_id, f"{name} plan", [task["id"]])
    generated = ph.generate_plan(client, app_id, plan["id"])
    revision = generated["revision"]["revision"]
    validated = client.post(
        f"/api/v1/applications/{app_id}/test-plans/{plan['id']}/validate"
    )
    assert validated.status_code == 200, validated.text
    submitted = client.post(f"/api/v1/applications/{app_id}/test-plans/{plan['id']}/submit")
    assert submitted.status_code == 200, submitted.text
    approved = client.post(
        f"/api/v1/applications/{app_id}/test-plans/{plan['id']}/approve",
        json={"revision": revision},
    )
    assert approved.status_code == 200, approved.text

    profile_body = dict(profile or SIMULATED_PROFILE)
    profile_response = client.put(
        f"/api/v1/applications/{app_id}/runtime-profile", json=profile_body
    )
    assert profile_response.status_code == 200, profile_response.text

    cases = ph.plan_cases(client, app_id, plan["id"], revision)
    return {
        "app_id": app_id,
        "api_key": api_key,
        "task": task,
        "plan": plan,
        "revision": revision,
        "cases": cases,
        "checkpoints": discovered,
        "profile": profile_body,
    }


def case_for(
    fixture: dict[str, Any], scenario_id: str, *, checkpoint_name: str | None = None
) -> dict:
    for case in fixture["cases"]:
        if case["scenario_id"] != scenario_id:
            continue
        if case["checkpoint_name"] != checkpoint_name:
            continue
        return case
    raise AssertionError(
        f"no case for {scenario_id} (checkpoint={checkpoint_name}); "
        f"available: {[(c['scenario_id'], c['checkpoint_name']) for c in fixture['cases']]}"
    )


def app_for(db: Session, fixture: dict[str, Any]) -> TargetApp:
    return discovery_service.get_target_app(db, uuid.UUID(fixture["app_id"]))


def start_run(
    db: Session, fixture: dict[str, Any], case: dict
) -> Any:
    return runtime_service.start_case_run(
        db,
        app_for(db, fixture),
        plan_id=uuid.UUID(fixture["plan"]["id"]),
        case_id=uuid.UUID(case["id"]),
    )


class Telemetry:
    """Writes real SDK-shaped telemetry through the observation service."""

    def __init__(self, db: Session, target_app: TargetApp, *, task_name: str = TASK_NAME):
        self.db = db
        self.target_app = target_app
        self.task_name = task_name

    def report(
        self,
        *,
        run_id: uuid.UUID,
        execution_id: uuid.UUID,
        celery_task_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        body = TaskExecutionEventCreate(
            execution_id=execution_id,
            celery_task_id=celery_task_id,
            task_name=self.task_name,
            worker_instance_id="sim-worker",
            worker_hostname="veriq@sim",
            pid=4242,
            queue_name="veriq.test",
            veriq_operation_id=run_id,
            event_type=event_type,
            event_id=uuid.uuid4(),
            occurred_at=datetime.now(timezone.utc),
            payload=payload,
        )
        return observation_service.report_execution_event(self.db, self.target_app, body)

    def attempt(
        self,
        *,
        run_id: uuid.UUID,
        celery_task_id: str,
        status: str = "succeeded",
        retry: bool = False,
        checkpoints: tuple[str, ...] = (),
        execution_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        execution_id = execution_id or uuid.uuid4()
        self.report(
            run_id=run_id,
            execution_id=execution_id,
            celery_task_id=celery_task_id,
            event_type="TASK_STARTED",
        )
        for checkpoint in checkpoints:
            self.report(
                run_id=run_id,
                execution_id=execution_id,
                celery_task_id=celery_task_id,
                event_type="TASK_CHECKPOINT",
                payload={"checkpoint": checkpoint},
            )
        if retry:
            self.report(
                run_id=run_id,
                execution_id=execution_id,
                celery_task_id=celery_task_id,
                event_type="TASK_RETRY_REQUESTED",
                payload={"reason": "injected fault"},
            )
        elif status == "succeeded":
            self.report(
                run_id=run_id,
                execution_id=execution_id,
                celery_task_id=celery_task_id,
                event_type="TASK_SUCCEEDED",
                payload={"state": "SUCCESS"},
            )
        elif status == "failed":
            self.report(
                run_id=run_id,
                execution_id=execution_id,
                celery_task_id=celery_task_id,
                event_type="TASK_FAILED",
                payload={"exception_type": "TimeoutError"},
            )
        return {
            "execution_id": execution_id,
            "celery_task_id": celery_task_id,
        }


class ScriptedExecutor:
    """Submission recorder that runs a scripted application behaviour."""

    def __init__(self, on_submit: Callable[["ScriptedExecutor", SubmissionResult, uuid.UUID], None]):
        self._on_submit = on_submit
        self.submissions: list[dict[str, Any]] = []
        self.closed = False

    def submit(
        self,
        *,
        task_name: str,
        payload: dict[str, Any],
        queue: str,
        operation_id: str,
        logical_job_id: str,
        task_id: str | None = None,
    ) -> SubmissionResult:
        result = SubmissionResult(
            task_id=task_id or str(uuid.uuid4()),
            queue=queue,
            submitted_at=datetime.now(timezone.utc),
            headers={"veriq_operation_id": operation_id},
        )
        self.submissions.append(
            {
                "task_name": task_name,
                "payload": dict(payload),
                "queue": queue,
                "operation_id": operation_id,
                "logical_job_id": logical_job_id,
                "task_id": result.task_id,
            }
        )
        self._on_submit(self, result, uuid.UUID(operation_id))
        return result

    def close(self) -> None:
        self.closed = True


def orchestrator(
    db: Session,
    *,
    backend: Any | None = None,
    executor_factory: Callable[[str], Any] | None = None,
    settings: dict[str, Any] | None = None,
) -> TestOrchestrator:
    merged = {**FAST_SETTINGS, **(settings or {})}
    return TestOrchestrator(
        db=db,
        backend=backend or SimulatedRuntime(),
        executor_factory=executor_factory,
        settings=OrchestratorSettings(**merged),
    )
