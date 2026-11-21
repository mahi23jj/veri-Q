"""Reliability runtime API.

Starting a test is an explicit action on an approved plan revision and a READY
test case; nothing here executes a task inline. Runtime control stays server
side: no endpoint exposes Docker access, container controls, credentials or
unrestricted command execution.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import TargetApp
from app.schemas.runtime import (
    CancelRunResponse,
    FaultEventResponse,
    ObservedAttempt,
    RecoverRunsResponse,
    RecoveryObservationResponse,
    RunnerCapabilitiesResponse,
    RunnerEnvironmentResponse,
    RunnerWorkerResponse,
    RuntimeEventResponse,
    RuntimeProfileRequest,
    RuntimeProfileResponse,
    StartRunRequest,
    StartRunResponse,
    TestCaseRunDetail,
    TestCaseRunResponse,
    VerdictResponse,
)
from app.runtime import scheduler
from app.services import discovery_service, runtime_service, test_plan_service
from app.runtime.observer import summarize_attempts

router = APIRouter(tags=["reliability-runtime"])

_NEXT = (
    "Poll GET /applications/{application_id}/test-runs/{run_id} for lifecycle, "
    "fault, recovery and verdict evidence."
)


def schedule_run(run_id: uuid.UUID) -> bool:
    """Module-level seam so tests can execute a run synchronously."""
    scheduler.schedule(run_id)
    return True


def _application(db: Session, application_id: uuid.UUID) -> TargetApp:
    try:
        return discovery_service.get_target_app(db, application_id)
    except discovery_service.TargetAppNotFoundError as exc:
        raise HTTPException(status_code=404, detail="application not found") from exc


def _run(db: Session, target_app: TargetApp, run_id: uuid.UUID):
    try:
        return runtime_service.get_run(db, run_id, target_app_id=target_app.id)
    except runtime_service.RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="test run not found") from exc


def _issues(issues: list[dict[str, Any]], status_code: int = 422) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"message": "the test case cannot be executed", "issues": issues},
    )


# ---------------------------------------------------------------------------
# Runtime profile and capabilities
# ---------------------------------------------------------------------------


@router.get("/applications/{application_id}/runtime-profile")
def get_runtime_profile(
    application_id: uuid.UUID, db: Session = Depends(get_db)
) -> RuntimeProfileResponse:
    target_app = _application(db, application_id)
    return RuntimeProfileResponse(
        target_app_id=target_app.id, runtime_config=target_app.runtime_config
    )


@router.put("/applications/{application_id}/runtime-profile")
def put_runtime_profile(
    application_id: uuid.UUID,
    payload: RuntimeProfileRequest,
    db: Session = Depends(get_db),
) -> RuntimeProfileResponse:
    """Configure how the isolated runner launches this application's own image."""
    target_app = _application(db, application_id)
    try:
        profile = runtime_service.set_runtime_profile(db, target_app, payload.to_profile())
    except runtime_service.RuntimeProfileError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "runtime profile is not valid",
                "issues": [
                    {"code": "RUNTIME_PROFILE_INVALID", "severity": "error", "message": issue}
                    for issue in exc.issues
                ],
            },
        ) from exc
    return RuntimeProfileResponse(target_app_id=target_app.id, runtime_config=profile)


@router.get(
    "/applications/{application_id}/runner/capabilities",
    response_model=RunnerCapabilitiesResponse,
)
def runner_capabilities(
    application_id: uuid.UUID, db: Session = Depends(get_db)
) -> dict[str, Any]:
    _application(db, application_id)
    return runtime_service.runtime_capabilities()


# ---------------------------------------------------------------------------
# Starting and reading runs
# ---------------------------------------------------------------------------


@router.post(
    "/applications/{application_id}/test-plans/{plan_id}/runs",
    response_model=StartRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_test_run(
    application_id: uuid.UUID,
    plan_id: uuid.UUID,
    payload: StartRunRequest,
    db: Session = Depends(get_db),
) -> StartRunResponse:
    """Start one approved test case. Approval itself never executes anything."""
    target_app = _application(db, application_id)
    try:
        run = runtime_service.start_case_run(
            db,
            target_app,
            plan_id=plan_id,
            case_id=payload.case_id,
            case_key=payload.case_key,
        )
    except test_plan_service.TestPlanNotFoundError as exc:
        raise HTTPException(status_code=404, detail="test plan not found") from exc
    except runtime_service.RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="test case not found") from exc
    except runtime_service.RuntimeProfileError as exc:
        raise _issues(
            [
                {"code": "RUNTIME_PROFILE_INVALID", "severity": "error", "message": issue}
                for issue in exc.issues
            ]
        ) from exc
    except runtime_service.RunNotExecutableError as exc:
        raise _issues(exc.issues) from exc
    except runtime_service.ActiveRunError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    scheduled = schedule_run(run.id)
    return StartRunResponse(
        run=TestCaseRunResponse.model_validate(run), scheduled=scheduled, next=_NEXT
    )


@router.post(
    "/applications/{application_id}/test-plans/{plan_id}/test-cases/{case_id}/runs",
    response_model=StartRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_test_case_run(
    application_id: uuid.UUID,
    plan_id: uuid.UUID,
    case_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> StartRunResponse:
    return start_test_run(
        application_id, plan_id, StartRunRequest(case_id=case_id), db
    )


@router.get(
    "/applications/{application_id}/test-runs",
    response_model=list[TestCaseRunResponse],
)
def list_test_runs(
    application_id: uuid.UUID,
    lifecycle_state: str | None = None,
    verdict: str | None = None,
    plan_id: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[TestCaseRunResponse]:
    target_app = _application(db, application_id)
    runs = runtime_service.list_runs(
        db,
        target_app_id=target_app.id,
        lifecycle_state=lifecycle_state,
        verdict=verdict,
        plan_id=plan_id,
        limit=limit,
    )
    return [TestCaseRunResponse.model_validate(run) for run in runs]


@router.post(
    "/applications/{application_id}/test-runs/recover-interrupted",
    response_model=RecoverRunsResponse,
)
def recover_interrupted_runs(
    application_id: uuid.UUID, db: Session = Depends(get_db)
) -> RecoverRunsResponse:
    """Finalize and clean runs left behind by an interrupted backend."""
    target_app = _application(db, application_id)
    recovered = runtime_service.recover_interrupted_runs(
        db, target_app_id=target_app.id
    )
    return RecoverRunsResponse(recovered=recovered)


@router.get(
    "/applications/{application_id}/test-runs/{run_id}",
    response_model=TestCaseRunDetail,
)
def get_test_run(
    application_id: uuid.UUID, run_id: uuid.UUID, db: Session = Depends(get_db)
) -> TestCaseRunDetail:
    target_app = _application(db, application_id)
    run = _run(db, target_app, run_id)
    environment = runtime_service.get_environment(db, run)
    recovery = runtime_service.get_recovery(db, run)
    workers = runtime_service.list_workers(db, run)
    return TestCaseRunDetail(
        run=TestCaseRunResponse.model_validate(run),
        configuration=dict(run.configuration or {}),
        environment=(
            RunnerEnvironmentResponse.model_validate(environment) if environment else None
        ),
        workers=[RunnerWorkerResponse.model_validate(worker) for worker in workers],
        fault_events=[
            FaultEventResponse.model_validate(event)
            for event in runtime_service.list_fault_events(db, run)
        ],
        recovery=(
            RecoveryObservationResponse.model_validate(recovery) if recovery else None
        ),
        runtime_events=[
            RuntimeEventResponse.model_validate(event)
            for event in runtime_service.list_runtime_events(db, run)
        ],
        observed_attempts=[
            ObservedAttempt(**attempt) for attempt in summarize_attempts(_attempts(db, run))
        ],
        next=_NEXT,
    )


def _attempts(db: Session, run) -> list:
    from app.runtime.execution import correlated_executions

    return correlated_executions(
        db, target_app_id=run.target_app_id, test_run_id=run.id
    )


@router.get(
    "/applications/{application_id}/test-runs/{run_id}/environment",
    response_model=RunnerEnvironmentResponse,
)
def get_run_environment(
    application_id: uuid.UUID, run_id: uuid.UUID, db: Session = Depends(get_db)
) -> RunnerEnvironmentResponse:
    target_app = _application(db, application_id)
    run = _run(db, target_app, run_id)
    environment = runtime_service.get_environment(db, run)
    if environment is None:
        raise HTTPException(status_code=404, detail="no environment for this run")
    return RunnerEnvironmentResponse.model_validate(environment)


@router.get(
    "/applications/{application_id}/test-runs/{run_id}/workers",
    response_model=list[RunnerWorkerResponse],
)
def get_run_workers(
    application_id: uuid.UUID, run_id: uuid.UUID, db: Session = Depends(get_db)
) -> list[RunnerWorkerResponse]:
    target_app = _application(db, application_id)
    run = _run(db, target_app, run_id)
    return [
        RunnerWorkerResponse.model_validate(worker)
        for worker in runtime_service.list_workers(db, run)
    ]


@router.get(
    "/applications/{application_id}/test-runs/{run_id}/faults",
    response_model=list[FaultEventResponse],
)
def get_run_faults(
    application_id: uuid.UUID, run_id: uuid.UUID, db: Session = Depends(get_db)
) -> list[FaultEventResponse]:
    target_app = _application(db, application_id)
    run = _run(db, target_app, run_id)
    return [
        FaultEventResponse.model_validate(event)
        for event in runtime_service.list_fault_events(db, run)
    ]


@router.get(
    "/applications/{application_id}/test-runs/{run_id}/recovery",
    response_model=RecoveryObservationResponse,
)
def get_run_recovery(
    application_id: uuid.UUID, run_id: uuid.UUID, db: Session = Depends(get_db)
) -> RecoveryObservationResponse:
    target_app = _application(db, application_id)
    run = _run(db, target_app, run_id)
    recovery = runtime_service.get_recovery(db, run)
    if recovery is None:
        raise HTTPException(status_code=404, detail="no recovery observation for this run")
    return RecoveryObservationResponse.model_validate(recovery)


@router.get(
    "/applications/{application_id}/test-runs/{run_id}/verdict",
    response_model=VerdictResponse,
)
def get_run_verdict(
    application_id: uuid.UUID, run_id: uuid.UUID, db: Session = Depends(get_db)
) -> VerdictResponse:
    target_app = _application(db, application_id)
    run = _run(db, target_app, run_id)
    recovery = runtime_service.get_recovery(db, run)
    return VerdictResponse(
        run_id=run.id,
        lifecycle_state=run.lifecycle_state,
        verdict=run.verdict,
        detail=run.verdict_detail,
        attempts=recovery.attempt_count if recovery else 0,
        retries=recovery.retry_request_count if recovery else 0,
        final_execution_state=recovery.final_execution_state if recovery else None,
        evidence_complete=recovery.evidence_complete if recovery else False,
    )


@router.get(
    "/applications/{application_id}/test-runs/{run_id}/events",
    response_model=list[RuntimeEventResponse],
)
def get_run_events(
    application_id: uuid.UUID, run_id: uuid.UUID, db: Session = Depends(get_db)
) -> list[RuntimeEventResponse]:
    target_app = _application(db, application_id)
    run = _run(db, target_app, run_id)
    return [
        RuntimeEventResponse.model_validate(event)
        for event in runtime_service.list_runtime_events(db, run)
    ]


@router.post(
    "/applications/{application_id}/test-runs/{run_id}/cancel",
    response_model=CancelRunResponse,
)
def cancel_run(
    application_id: uuid.UUID, run_id: uuid.UUID, db: Session = Depends(get_db)
) -> CancelRunResponse:
    """Request cancellation. The orchestrator finalizes and cleans up."""
    target_app = _application(db, application_id)
    run = _run(db, target_app, run_id)
    try:
        run = runtime_service.request_cancel(db, run)
    except runtime_service.InvalidRunStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return CancelRunResponse(
        run=TestCaseRunResponse.model_validate(run),
        message=(
            "cancellation requested; the runner releases the fault, stops the worker and "
            "removes the environment"
        ),
    )
