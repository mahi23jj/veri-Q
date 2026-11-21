"""Runtime service: start, read, cancel and recover reliability test runs.

Starting a run is always an explicit action on an *approved* plan revision. The
service validates executability against the current configuration, freezes the
configuration and policy the run executes, and persists it. It never executes
anything itself: the orchestrator does, in a background worker.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_api_key
from app.domain.runtime.recovery import RecoveryPolicy
from app.domain.runtime.lifecycle import assert_transition
from app.domain.scenarios.catalog import SCENARIO_CATALOG_VERSION
from app.models import (
    FaultEvent,
    RecoveryObservation,
    RegisteredTask,
    RunnerCredential,
    RunnerEnvironment,
    RunnerWorker,
    RuntimeEvent,
    TargetApp,
    TaskCheckpoint,
    TestCaseRun,
    TestPlan,
    TestPlanRevision,
    TestPlanTestCase,
)
from app.runtime.contracts import BrokerSpec, DatabaseSpec, EnvironmentPlan, WorkerSpec
from app.runtime.injectors.scenario_injectors import INJECTOR_TYPES, supported_scenarios
from app.services import (
    checkpoint_service,
    compatibility_service,
    task_contract_service,
    test_plan_service,
)

_SECRET_ENV_PATTERN = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "credential",
    "private_key",
)

DEFAULT_WORKER_COMMAND = (
    "celery",
    "-A",
    "app.worker",
    "worker",
    "-Q",
    "{queue}",
    "--loglevel=INFO",
    "--concurrency=1",
    "--hostname=veriq@%h",
)


class RunNotFoundError(Exception):
    pass


class RunNotExecutableError(Exception):
    """The case cannot be executed in its current configuration."""

    def __init__(self, issues: Sequence[dict[str, Any]]):
        super().__init__("; ".join(issue["message"] for issue in issues) or "not executable")
        self.issues = list(issues)


class RuntimeProfileError(Exception):
    def __init__(self, issues: Sequence[str]):
        super().__init__("; ".join(issues))
        self.issues = list(issues)


class ActiveRunError(Exception):
    """Another run of the same case is still active."""


class InvalidRunStateError(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _issue(code: str, message: str, field: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "severity": "error", "message": message}
    if field:
        payload["field"] = field
    return payload


# ---------------------------------------------------------------------------
# Runtime profile
# ---------------------------------------------------------------------------


def _looks_secret(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in _SECRET_ENV_PATTERN)


def validate_runtime_profile(profile: dict[str, Any] | None) -> dict[str, Any]:
    """Validate (and normalise) the application's runner configuration."""
    if not isinstance(profile, dict) or not profile:
        raise RuntimeProfileError(
            [
                "the application has no runtime profile; set one with "
                "PUT /applications/{id}/runtime-profile (image + worker command)"
            ]
        )
    issues: list[str] = []
    runtime_type = str(profile.get("runtime_type") or "docker")
    if runtime_type not in ("docker", "simulated"):
        issues.append("runtime_type must be 'docker' or 'simulated'")
    if runtime_type == "simulated" and not settings.RUNNER_SIMULATED_ALLOWED:
        issues.append("the simulated runtime is disabled on this backend")
    image = profile.get("image")
    if runtime_type == "docker" and (not isinstance(image, str) or not image.strip()):
        issues.append("image is required for the docker runtime")
    queue = profile.get("queue")
    if not isinstance(queue, str) or not queue.strip():
        issues.append("queue is required (the dedicated test queue)")
    command = profile.get("worker_command")
    if command is not None and (
        not isinstance(command, list) or not all(isinstance(part, str) for part in command)
    ):
        issues.append("worker_command must be a list of strings")
    env = profile.get("env") or {}
    if not isinstance(env, dict):
        issues.append("env must be an object")
    else:
        for key in env:
            if _looks_secret(str(key)):
                issues.append(
                    f"env key '{key}' looks like a credential; the runtime profile must "
                    "never contain secrets"
                )
    if issues:
        raise RuntimeProfileError(issues)

    concurrency = profile.get("concurrency", 1)
    if not isinstance(concurrency, int) or concurrency != 1:
        # One task per dedicated worker keeps termination attribution exact.
        issues.append("concurrency must be 1 for the initial runner implementation")
    if issues:
        raise RuntimeProfileError(issues)

    normalised = dict(profile)
    normalised["runtime_type"] = runtime_type
    normalised["queue"] = str(queue).strip()
    normalised["concurrency"] = 1
    normalised["env"] = {str(key): str(value) for key, value in (env or {}).items()}
    if "broker_image" not in normalised:
        normalised["broker_image"] = "redis:7-alpine"
    if "database_image" not in normalised:
        normalised["database_image"] = "postgres:16-alpine"
    if not isinstance(normalised.get("worker_command"), list):
        normalised["worker_command"] = [
            part.format(queue=normalised["queue"]) for part in DEFAULT_WORKER_COMMAND
        ]
    http = normalised.get("http")
    if http is not None and not isinstance(http, dict):
        issues.append("http must be an object")
    database = normalised.get("database")
    if database is not None and not isinstance(database, dict):
        issues.append("database must be an object")
    if issues:
        raise RuntimeProfileError(issues)
    return normalised


def set_runtime_profile(
    db: Session, target_app: TargetApp, profile: dict[str, Any]
) -> dict[str, Any]:
    normalised = validate_runtime_profile(profile)
    target_app.runtime_config = normalised
    db.commit()
    db.refresh(target_app)
    return normalised


# ---------------------------------------------------------------------------
# Starting a run
# ---------------------------------------------------------------------------


@dataclass
class ExecutableCase:
    run: TestCaseRun
    plan: TestPlan
    revision: TestPlanRevision
    case: TestPlanTestCase
    task: RegisteredTask
    profile: dict[str, Any]
    policy: RecoveryPolicy
    configuration: dict[str, Any]
    checkpoint: TaskCheckpoint | None = None
    issues: list[dict[str, Any]] = field(default_factory=list)


def _case_configuration(
    *, case: TestPlanTestCase, plan: TestPlan, revision: TestPlanRevision, task: RegisteredTask
) -> dict[str, Any]:
    return {
        "case_id": str(case.id),
        "case_key": case.case_key,
        "task_id": str(task.id),
        "task_name": task.task_name,
        "scenario_id": case.scenario_id,
        "scenario_version": case.scenario_version,
        "trigger_type": case.trigger_type,
        "checkpoint_id": str(case.checkpoint_id) if case.checkpoint_id else None,
        "checkpoint_name": case.checkpoint_name,
        "contract_id": str(case.contract_id) if case.contract_id else None,
        "contract_version": case.contract_version,
        "test_input": dict(case.test_input or {}),
        "input_fixture_ref": case.input_fixture_ref,
        "assertions": [dict(assertion) for assertion in (case.assertions or [])],
        "cleanup": dict(case.cleanup or {}),
        "scenario_config": dict(case.scenario_config or {}),
        "adapter_refs": [dict(ref) for ref in (case.adapter_refs or [])],
        "configuration_fingerprint": case.configuration_fingerprint,
        "plan_id": str(plan.id),
        "plan_revision": revision.revision,
        "scenario_catalog_version": SCENARIO_CATALOG_VERSION,
    }


def _policy_for(db: Session, case: TestPlanTestCase, configuration: dict[str, Any]) -> RecoveryPolicy:
    if case.recovery_policy:
        return RecoveryPolicy.from_contract({"recovery": case.recovery_policy})
    contract = None
    if case.contract_id is not None:
        contract = task_contract_service.get_contract_for_task(db, case.registered_task_id)
    payload = contract.payload if contract is not None else {}
    return RecoveryPolicy.from_contract(payload)


def _active_run_for_case(
    db: Session, *, target_app_id: uuid.UUID, case_id: uuid.UUID
) -> TestCaseRun | None:
    from app.models.runtime import ACTIVE_LIFECYCLE_STATES

    return db.scalar(
        select(TestCaseRun).where(
            TestCaseRun.target_app_id == target_app_id,
            TestCaseRun.test_plan_test_case_id == case_id,
            TestCaseRun.lifecycle_state.in_(ACTIVE_LIFECYCLE_STATES),
        )
    )


def start_case_run(
    db: Session,
    target_app: TargetApp,
    *,
    plan_id: uuid.UUID,
    case_id: uuid.UUID | None = None,
    case_key: str | None = None,
) -> TestCaseRun:
    """Create a PENDING run. Execution is scheduled separately, never here."""
    if not settings.RUNNER_ENABLED:
        raise RunNotExecutableError(
            [_issue("RUNNER_DISABLED", "the reliability runner is disabled on this backend")]
        )
    plan = test_plan_service.get_plan(db, plan_id, target_app_id=target_app.id)
    if plan.status != "APPROVED" or plan.approved_revision is None:
        raise RunNotExecutableError(
            [
                _issue(
                    "PLAN_NOT_APPROVED",
                    "only an approved plan revision can be executed",
                    "plan.status",
                )
            ]
        )
    if plan.approved_revision != plan.current_revision:
        raise RunNotExecutableError(
            [
                _issue(
                    "PLAN_REVISION_CHANGED",
                    "the approved revision is not the current revision; review and approve again",
                    "plan.approved_revision",
                )
            ]
        )
    revision = test_plan_service.get_revision(db, plan, plan.approved_revision)
    if case_id is None and case_key is None:
        raise RunNotExecutableError(
            [_issue("CASE_REQUIRED", "provide the test case id or case key to execute")]
        )
    stmt = select(TestPlanTestCase).where(
        TestPlanTestCase.test_plan_revision_id == revision.id
    )
    if case_id is not None:
        stmt = stmt.where(TestPlanTestCase.id == case_id)
    else:
        stmt = stmt.where(TestPlanTestCase.case_key == case_key)
    case = db.scalar(stmt)
    if case is None:
        raise RunNotFoundError("test case not found in the approved revision")
    if case.status != "READY":
        raise RunNotExecutableError(
            [
                _issue(
                    "CASE_BLOCKED",
                    "the selected test case is BLOCKED; fix its configuration and regenerate",
                    "case.status",
                )
            ]
        )
    task = db.get(RegisteredTask, case.registered_task_id)
    if task is None or task.target_app_id != target_app.id:
        raise RunNotExecutableError(
            [_issue("TASK_NOT_FOUND", "the case's registered task no longer exists")]
        )
    if _active_run_for_case(db, target_app_id=target_app.id, case_id=case.id) is not None:
        raise ActiveRunError("this test case already has an active run")

    profile = validate_runtime_profile(target_app.runtime_config)
    configuration = _case_configuration(case=case, plan=plan, revision=revision, task=task)
    policy = _policy_for(db, case, configuration)

    run = TestCaseRun(
        target_app_id=target_app.id,
        registered_task_id=task.id,
        test_plan_id=plan.id,
        test_plan_revision_id=revision.id,
        test_plan_test_case_id=case.id,
        case_key=case.case_key,
        scenario_id=case.scenario_id,
        scenario_version=case.scenario_version,
        trigger_type=case.trigger_type,
        checkpoint_name=case.checkpoint_name,
        lifecycle_state="PENDING",
        configuration=configuration,
        recovery_policy=policy.to_dict(),
        runtime_profile_snapshot=profile,
        logical_job_id=uuid.uuid4(),
        celery_task_ids=[],
        started_at=_now(),
    )
    db.add(run)
    db.flush()
    record_runtime_event(
        db,
        run,
        source="ORCHESTRATOR",
        event_type="run_created",
        payload={
            "case_key": case.case_key,
            "scenario_id": case.scenario_id,
            "trigger_type": case.trigger_type,
            "checkpoint_name": case.checkpoint_name,
            "plan_revision": revision.revision,
            "approval_basis": "approved plan revision",
            "execution_is_separate_action": True,
        },
    )
    db.commit()
    db.refresh(run)
    return run


# ---------------------------------------------------------------------------
# Validation before execution
# ---------------------------------------------------------------------------


def validate_executable(db: Session, run: TestCaseRun) -> ExecutableCase:
    """Re-check the frozen case against the *current* configuration."""
    issues: list[dict[str, Any]] = []
    plan = db.get(TestPlan, run.test_plan_id)
    case = db.get(TestPlanTestCase, run.test_plan_test_case_id)
    task = db.get(RegisteredTask, run.registered_task_id)
    if plan is None or case is None or task is None:
        raise RunNotExecutableError(
            [_issue("CONFIGURATION_MISSING", "the plan, case or task no longer exists")]
        )
    revision = db.get(TestPlanRevision, run.test_plan_revision_id)
    if revision is None:
        raise RunNotExecutableError([_issue("CONFIGURATION_MISSING", "revision is missing")])
    if plan.status != "APPROVED" or plan.approved_revision != revision.revision:
        issues.append(
            _issue(
                "APPROVAL_NO_LONGER_VALID",
                "the plan revision is no longer approved; review and approve it again",
            )
        )
    if case.status != "READY":
        issues.append(_issue("CASE_BLOCKED", "the test case is no longer READY"))
    if run.scenario_id not in supported_scenarios():
        issues.append(
            _issue(
                "SCENARIO_NOT_IMPLEMENTED",
                f"no injector is implemented for scenario '{run.scenario_id}'",
            )
        )

    checkpoint = None
    if case.checkpoint_id is not None:
        checkpoint = db.get(TaskCheckpoint, case.checkpoint_id)
    if run.trigger_type == "checkpoint":
        if checkpoint is None:
            issues.append(_issue("CHECKPOINT_MISSING", "the selected checkpoint no longer exists"))
        elif not checkpoint.reliability_enabled:
            issues.append(
                _issue(
                    "CHECKPOINT_NOT_ENABLED",
                    f"checkpoint '{checkpoint.name}' is not enabled for reliability testing",
                )
            )

    try:
        scenario = compatibility_service.resolve_scenario(run.scenario_id)
        result = compatibility_service.evaluate_task_scenario(
            db, task, scenario, trigger_type=run.trigger_type, checkpoint=checkpoint
        )
        if not result.compatible:
            for reason in result.blocking_reasons:
                issues.append(
                    _issue(
                        reason.code,
                        f"configuration drift: {reason.message}",
                        reason.field,
                    )
                )
    except compatibility_service.ScenarioNotFoundError:
        issues.append(
            _issue("SCENARIO_UNSUPPORTED", f"scenario '{run.scenario_id}' is not in the catalogue")
        )

    try:
        profile = validate_runtime_profile(run.runtime_profile_snapshot)
    except RuntimeProfileError as exc:
        for message in exc.issues:
            issues.append(_issue("RUNTIME_PROFILE_INVALID", message))
        profile = {}

    if issues:
        raise RunNotExecutableError(issues)

    policy = RecoveryPolicy.from_contract({"recovery": run.recovery_policy or {}})
    return ExecutableCase(
        run=run,
        plan=plan,
        revision=revision,
        case=case,
        task=task,
        profile=profile,
        policy=policy,
        configuration=dict(run.configuration or {}),
        checkpoint=checkpoint,
    )


# ---------------------------------------------------------------------------
# Environment plan
# ---------------------------------------------------------------------------


def build_environment_plan(
    executable: ExecutableCase,
    *,
    broker_url: str | None = None,
    database_url: str | None = None,
) -> EnvironmentPlan:
    profile = executable.profile
    run = executable.run
    namespace = f"veriq-{run.id.hex[:8]}"
    queue = profile["queue"]
    command = tuple(profile.get("worker_command") or ())
    if not command:
        command = tuple(part.format(queue=queue) for part in DEFAULT_WORKER_COMMAND)
    env = {str(key): str(value) for key, value in (profile.get("env") or {}).items()}
    if broker_url:
        env.setdefault("CELERY_BROKER_URL", broker_url)
        env.setdefault("VERIQ_BROKER_URL", broker_url)
    env.setdefault("VERIQ_QUEUE", queue)
    env.setdefault("CELERY_NORMAL_QUEUE", f"{namespace}.normal")
    if database_url:
        env["TARGET_DATABASE_URL"] = database_url
    runtime_type = profile.get("runtime_type", "docker")
    http_profile = profile.get("http") if isinstance(profile.get("http"), dict) else {}
    return EnvironmentPlan(
        test_run_id=str(run.id),
        target_app_id=str(run.target_app_id),
        namespace=namespace,
        runtime_type=runtime_type,
        network_name=f"{namespace}-net",
        worker=WorkerSpec(
            image=str(profile.get("image") or "simulated/target-app"),
            command=command,
            queue_name=queue,
            concurrency=1,
            hostname="veriq@%h",
            env=env,
        ),
        broker=(
            BrokerSpec(image=str(profile.get("broker_image")))
            if profile.get("broker_image")
            else BrokerSpec()
        ),
        database=(
            DatabaseSpec(image=str(profile.get("database_image")))
            if profile.get("database_image")
            else DatabaseSpec()
        ),
        env=env,
        runtime_config=dict(profile),
        provisioning_timeout_seconds=settings.RUNNER_PROVISIONING_TIMEOUT_SECONDS,
        worker_startup_timeout_seconds=settings.RUNNER_WORKER_STARTUP_TIMEOUT_SECONDS,
        expected_task_names=(executable.task.task_name,),
    )


def _database_proxy_url(upstream: tuple[str, int] | None, profile: dict[str, Any]) -> str:
    host = (profile.get("http") or {}).get("advertised_host", "host.docker.internal")
    port = upstream[1] if upstream else 5432
    return f"postgresql://veriq:veriq@{host}:{port}/veriq"


def worker_environment(
    plan: EnvironmentPlan,
    *,
    provisioned: Any,
    api_base_url: str,
    api_key: str,
    http_proxy_origin: str | None = None,
    database_proxy_port: int | None = None,
) -> dict[str, str]:
    env = dict(plan.env)
    env["VERIQ_API_URL"] = api_base_url
    env["VERIQ_API_KEY"] = api_key
    env["VERIQ_QUEUE"] = plan.worker.queue_name
    env["VERIQ_TEST_RUN_ID"] = plan.test_run_id
    if provisioned.broker_ref:
        env["CELERY_BROKER_URL"] = provisioned.broker_ref
    if provisioned.database_ref and "TARGET_DATABASE_URL" not in env:
        env["TARGET_DATABASE_URL"] = provisioned.database_ref
    profile = plan.runtime_config or {}
    http_profile = profile.get("http") if isinstance(profile.get("http"), dict) else {}
    database_profile = (
        profile.get("database") if isinstance(profile.get("database"), dict) else {}
    )
    if http_proxy_origin and http_profile.get("url_env"):
        env[str(http_profile["url_env"])] = http_proxy_origin
    if database_proxy_port and database_profile.get("url_env"):
        host = http_profile.get("advertised_host", "host.docker.internal")
        env[str(database_profile["url_env"])] = (
            f"postgresql://veriq:veriq@{host}:{database_proxy_port}/veriq"
        )
    return env


def input_with_proxy(
    configuration: dict[str, Any], profile: dict[str, Any], proxy_origin: str
) -> dict[str, Any]:
    """Rewrite the configured dependency input field to the fault proxy."""
    payload = dict(configuration.get("test_input") or {})
    http_profile = profile.get("http") if isinstance(profile.get("http"), dict) else {}
    field = http_profile.get("input_field")
    if field and field in payload and isinstance(payload[field], str):
        original = payload[field]
        suffix = ""
        if "://" in original:
            from urllib.parse import urlsplit

            parts = urlsplit(original)
            suffix = parts.path or ""
            if parts.query:
                suffix += "?" + parts.query
        payload[field] = f"{proxy_origin}{suffix}"
    return payload


def dependency_upstream(configuration: dict[str, Any], profile: dict[str, Any]) -> str | None:
    http_profile = profile.get("http") if isinstance(profile.get("http"), dict) else {}
    if http_profile.get("upstream_url"):
        return str(http_profile["upstream_url"])
    field = http_profile.get("input_field")
    value = (configuration.get("test_input") or {}).get(field) if field else None
    return str(value) if isinstance(value, str) else None


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


def create_runner_credential(
    db: Session, run: TestCaseRun, *, ttl_seconds: int = 3600
) -> str:
    """Mint a run-scoped SDK key; only its digest is persisted."""
    plaintext = f"vq_run_{secrets.token_urlsafe(32)}"
    credential = RunnerCredential(
        test_case_run_id=run.id,
        target_app_id=run.target_app_id,
        api_key_hash=hash_api_key(plaintext),
        expires_at=_now() + timedelta(seconds=ttl_seconds),
    )
    db.add(credential)
    db.commit()
    return plaintext


# ---------------------------------------------------------------------------
# Evidence helpers
# ---------------------------------------------------------------------------


def record_runtime_event(
    db: Session,
    run: TestCaseRun,
    *,
    source: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> RuntimeEvent:
    event = RuntimeEvent(
        test_case_run_id=run.id,
        source=source,
        event_type=event_type,
        payload=payload,
        occurred_at=_now(),
    )
    db.add(event)
    db.flush()
    return event


class RuntimeRecorder:
    """Recorder implementation shared by the orchestrator, supervisor and faults."""

    def __init__(self, db: Session, run: TestCaseRun) -> None:
        self._db = db
        self._run = run

    def runtime_event(self, source: str, event_type: str, payload: dict[str, Any]) -> None:
        record_runtime_event(
            self._db, self._run, source=source, event_type=event_type, payload=payload
        )
        self._db.commit()

    def fault_event(
        self,
        *,
        state: str,
        injector_type: str,
        trigger_type: str,
        trigger_ref: str | None,
        detail: dict[str, Any] | None = None,
        error: str | None = None,
        activation_at: datetime | None = None,
        deactivation_at: datetime | None = None,
    ) -> None:
        event = FaultEvent(
            test_case_run_id=self._run.id,
            scenario_id=self._run.scenario_id,
            injector_type=injector_type,
            trigger_type=trigger_type,
            trigger_ref=trigger_ref,
            state=state,
            detail=detail,
            error=error,
            occurred_at=_now(),
            activation_at=activation_at,
            deactivation_at=deactivation_at,
        )
        self._db.add(event)
        self._db.commit()


def set_lifecycle(db: Session, run: TestCaseRun, state: str) -> TestCaseRun:
    if run.lifecycle_state != state:
        assert_transition(run.lifecycle_state, state)
    run.lifecycle_state = state
    db.commit()
    db.refresh(run)
    record_runtime_event(
        db, run, source="ORCHESTRATOR", event_type="lifecycle_changed", payload={"state": state}
    )
    db.commit()
    return run


def set_verdict(
    db: Session,
    run: TestCaseRun,
    *,
    verdict: str,
    detail: dict[str, Any],
) -> TestCaseRun:
    run.verdict = verdict
    run.verdict_detail = detail
    db.commit()
    record_runtime_event(
        db,
        run,
        source="OBSERVER",
        event_type="verdict_recorded",
        payload={"verdict": verdict, "reasons": detail.get("reasons", [])},
    )
    db.commit()
    return run


def persist_recovery(
    db: Session,
    run: TestCaseRun,
    observation: Any,
    *,
    error: str | None = None,
) -> RecoveryObservation:
    row = db.scalar(
        select(RecoveryObservation).where(RecoveryObservation.test_case_run_id == run.id)
    )
    if row is None:
        row = RecoveryObservation(test_case_run_id=run.id)
        db.add(row)
    row.attempt_count = observation.attempt_count
    row.retry_request_count = observation.retry_request_count
    row.subsequent_attempt_count = observation.subsequent_attempt_count
    row.fault_activated = observation.fault_activated
    row.recovery_duration_ms = observation.recovery_duration_ms
    row.final_execution_state = observation.final_execution_state
    row.evidence_complete = observation.evidence_complete
    row.missing_evidence = list(observation.missing_evidence)
    row.evidence = list(observation.evidence)
    row.observation = dict(observation.observation)
    row.error = error
    db.commit()
    db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def get_run(db: Session, run_id: uuid.UUID, *, target_app_id: uuid.UUID) -> TestCaseRun:
    run = db.get(TestCaseRun, run_id)
    if run is None or run.target_app_id != target_app_id:
        raise RunNotFoundError(str(run_id))
    return run


def list_runs(
    db: Session,
    *,
    target_app_id: uuid.UUID,
    lifecycle_state: str | None = None,
    verdict: str | None = None,
    plan_id: uuid.UUID | None = None,
    limit: int = 100,
) -> list[TestCaseRun]:
    stmt = select(TestCaseRun).where(TestCaseRun.target_app_id == target_app_id)
    if lifecycle_state:
        stmt = stmt.where(TestCaseRun.lifecycle_state == lifecycle_state)
    if verdict:
        stmt = stmt.where(TestCaseRun.verdict == verdict)
    if plan_id:
        stmt = stmt.where(TestCaseRun.test_plan_id == plan_id)
    return list(
        db.scalars(
            stmt.order_by(TestCaseRun.created_at.desc()).limit(max(1, min(limit, 500)))
        ).all()
    )


def list_runtime_events(
    db: Session, run: TestCaseRun, *, limit: int = 500
) -> list[RuntimeEvent]:
    return list(
        db.scalars(
            select(RuntimeEvent)
            .where(RuntimeEvent.test_case_run_id == run.id)
            .order_by(RuntimeEvent.occurred_at, RuntimeEvent.id)
            .limit(max(1, min(limit, 2000)))
        ).all()
    )


def list_fault_events(db: Session, run: TestCaseRun) -> list[FaultEvent]:
    return list(
        db.scalars(
            select(FaultEvent)
            .where(FaultEvent.test_case_run_id == run.id)
            .order_by(FaultEvent.occurred_at, FaultEvent.id)
        ).all()
    )


def get_environment(db: Session, run: TestCaseRun) -> RunnerEnvironment | None:
    return db.scalar(
        select(RunnerEnvironment).where(RunnerEnvironment.test_case_run_id == run.id)
    )


def list_workers(db: Session, run: TestCaseRun) -> list[RunnerWorker]:
    return list(
        db.scalars(
            select(RunnerWorker)
            .where(RunnerWorker.test_case_run_id == run.id)
            .order_by(RunnerWorker.created_at)
        ).all()
    )


def get_recovery(db: Session, run: TestCaseRun) -> RecoveryObservation | None:
    return db.scalar(
        select(RecoveryObservation).where(RecoveryObservation.test_case_run_id == run.id)
    )


def request_cancel(db: Session, run: TestCaseRun) -> TestCaseRun:
    if run.lifecycle_state in ("COMPLETED", "FAILED", "CANCELLED"):
        raise InvalidRunStateError(f"run is already {run.lifecycle_state}")
    if run.cancel_requested_at is not None:
        # Already cancelling: idempotent, keep the original request time.
        return run
    run.cancel_requested_at = _now()
    db.commit()
    record_runtime_event(
        db, run, source="ORCHESTRATOR", event_type="cancel_requested", payload={}
    )
    db.commit()
    db.refresh(run)
    return run


# ---------------------------------------------------------------------------
# Recovery after a backend restart
# ---------------------------------------------------------------------------


def recover_interrupted_runs(
    db: Session, *, target_app_id: uuid.UUID | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    """Finalize runs whose orchestrator thread no longer exists.

    A task is never re-submitted blindly: the run is cancelled, its evidence is
    kept, the verdict becomes INCONCLUSIVE, and the environment is cleaned up by
    label (which works without any in-memory handle).
    """
    from app.models.runtime import ACTIVE_LIFECYCLE_STATES

    stmt = select(TestCaseRun).where(TestCaseRun.lifecycle_state.in_(ACTIVE_LIFECYCLE_STATES))
    if target_app_id is not None:
        stmt = stmt.where(TestCaseRun.target_app_id == target_app_id)
    runs = list(db.scalars(stmt.limit(limit)).all())

    from app.runtime.docker_backend import DockerRuntime
    from app.runtime.finalizer import Finalizer, environment_to_provision_result
    from app.runtime.simulated_backend import SimulatedRuntime
    from app.runtime.supervisor import RunnerSupervisor

    recovered: list[dict[str, Any]] = []
    for run in runs:
        environment = get_environment(db, run)
        profile = run.runtime_profile_snapshot or {}
        runtime_type = (environment.runtime_type if environment else None) or profile.get(
            "runtime_type", "docker"
        )
        backend = SimulatedRuntime() if runtime_type == "simulated" else DockerRuntime()
        supervisor = RunnerSupervisor(backend=backend)
        finalizer = Finalizer(
            backend=backend,
            supervisor=supervisor,
            record=lambda source, event_type, payload: record_runtime_event(
                db, run, source=source, event_type=event_type, payload=payload
            ),
        )
        plan = None
        provisioned = None
        if environment is not None:
            provisioned = environment_to_provision_result(environment)
            plan = EnvironmentPlan(
                test_run_id=str(run.id),
                target_app_id=str(run.target_app_id),
                namespace=environment.namespace,
                runtime_type=runtime_type,
                network_name=environment.network_ref or f"{environment.namespace}-net",
                worker=WorkerSpec(
                    image=str(profile.get("image") or "unknown"),
                    command=tuple(profile.get("worker_command") or ()),
                    queue_name=str(profile.get("queue") or "veriq.test"),
                ),
                broker=None,
                database=None,
            )
        observation = get_recovery(db, run)
        if observation is None or not run.verdict:
            run.verdict = "INCONCLUSIVE"
            run.verdict_detail = {
                "verdict": "INCONCLUSIVE",
                "reasons": [
                    {
                        "code": "RUN_INTERRUPTED",
                        "message": (
                            "The runner was interrupted before evaluation completed; evidence "
                            "was preserved but the intended test outcome is unknown."
                        ),
                    }
                ],
            }
            db.commit()
        outcome = finalizer.finalize(
            db,
            run=run,
            final_state="CANCELLED",
            reason="recovered_after_restart",
            plan=plan,
            provisioned=provisioned,
        )
        recovered.append(
            {
                "run_id": str(run.id),
                "lifecycle_state": outcome.lifecycle_state,
                "cleanup_errors": list(outcome.errors),
                "verdict": run.verdict,
            }
        )
    return recovered


def runtime_capabilities() -> dict[str, Any]:
    from app.runtime.docker_backend import DockerRuntime

    docker_available, docker_detail = DockerRuntime().available()
    return {
        "runner_enabled": settings.RUNNER_ENABLED,
        "runtime_types": {
            "docker": {"available": docker_available, "detail": docker_detail},
            "simulated": {
                "available": settings.RUNNER_SIMULATED_ALLOWED,
                "detail": "explicitly non-isolated; tests and local demos only",
            },
        },
        "supported_scenarios": [
            {"scenario_id": scenario_id, "injector_type": INJECTOR_TYPES[scenario_id]}
            for scenario_id in supported_scenarios()
        ],
        "limits": {
            "provisioning_seconds": settings.RUNNER_PROVISIONING_TIMEOUT_SECONDS,
            "worker_startup_seconds": settings.RUNNER_WORKER_STARTUP_TIMEOUT_SECONDS,
            "fault_activation_seconds": settings.RUNNER_FAULT_ACTIVATION_TIMEOUT_SECONDS,
            "execution_seconds": settings.RUNNER_EXECUTION_TIMEOUT_SECONDS,
            "recovery_seconds": settings.RUNNER_RECOVERY_TIMEOUT_SECONDS,
            "finalization_seconds": settings.RUNNER_FINALIZATION_TIMEOUT_SECONDS,
            "total_seconds": settings.RUNNER_TOTAL_TIMEOUT_SECONDS,
        },
        "isolation": (
            "Dedicated Docker network, per-run Redis and PostgreSQL containers, dedicated "
            "queue and a concurrency-1 worker. Trusted applications only; not a security "
            "boundary."
        ),
    }


def scenario_counts(db: Session, run: TestCaseRun) -> dict[str, int]:
    faults = list_fault_events(db, run)
    return {
        "fault_events": len(faults),
        "runtime_events": db.scalar(
            select(func.count())
            .select_from(RuntimeEvent)
            .where(RuntimeEvent.test_case_run_id == run.id)
        )
        or 0,
    }


__all__ = [
    "ActiveRunError",
    "ExecutableCase",
    "InvalidRunStateError",
    "RunNotExecutableError",
    "RunNotFoundError",
    "RuntimeProfileError",
    "RuntimeRecorder",
    "build_environment_plan",
    "create_runner_credential",
    "dependency_upstream",
    "get_environment",
    "get_recovery",
    "get_run",
    "input_with_proxy",
    "list_fault_events",
    "list_runs",
    "list_runtime_events",
    "list_workers",
    "persist_recovery",
    "recover_interrupted_runs",
    "request_cancel",
    "runtime_capabilities",
    "set_lifecycle",
    "set_runtime_profile",
    "set_verdict",
    "start_case_run",
    "validate_executable",
    "validate_runtime_profile",
    "worker_environment",
]
