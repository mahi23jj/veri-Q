"""SDK-facing observation endpoints (``X-API-Key`` authenticated).

These routes accept ordinary task telemetry and discovery reports. They never
start, stop or control a worker.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_target_app
from app.core.database import get_db
from app.models import TargetApp
from app.schemas.observation import (
    ExecutionReportResponse,
    RegisteredTaskResponse,
    TaskDiscoveryCreate,
    TaskExecutionEventCreate,
    WorkerEventCreate,
    WorkerResponse,
)
from app.services import discovery_service, observation_service

router = APIRouter(tags=["observation-ingest"])


@router.post(
    "/task-executions/events",
    response_model=ExecutionReportResponse,
    status_code=status.HTTP_201_CREATED,
)
def report_execution_event(
    payload: TaskExecutionEventCreate,
    db: Session = Depends(get_db),
    target_app: TargetApp = Depends(get_current_target_app),
):
    """Record one SDK execution lifecycle event.

    Reporting is idempotent by ``event_id``. Events for a task the developer
    has disabled are acknowledged but not stored, while discovery metadata is
    still refreshed.
    """
    execution, event, duplicate, reason = observation_service.report_execution_event(
        db, target_app, payload
    )
    if execution is None:
        return ExecutionReportResponse(
            execution_id=payload.execution_id,
            stored=False,
            reason=reason,
        )
    return ExecutionReportResponse(
        execution_id=execution.execution_id,
        stored=True,
        status=execution.status,
        event_id=event.id if event is not None else None,
        duplicate=duplicate,
    )


@router.post(
    "/tasks/discovery",
    response_model=list[RegisteredTaskResponse],
    status_code=status.HTTP_201_CREATED,
)
def discover_registered_tasks(
    payload: TaskDiscoveryCreate,
    db: Session = Depends(get_db),
    target_app: TargetApp = Depends(get_current_target_app),
):
    """Register the Celery task names the SDK found in the application."""
    return discovery_service.discover_tasks(db, target_app, payload)


@router.post(
    "/workers/events",
    response_model=WorkerResponse,
    status_code=status.HTTP_201_CREATED,
)
def report_worker_event(
    payload: WorkerEventCreate,
    db: Session = Depends(get_db),
    target_app: TargetApp = Depends(get_current_target_app),
):
    """Upsert a worker instance, its queues and its registered task names."""
    return discovery_service.report_worker_event(db, target_app, payload)


@router.get(
    "/observation/workers",
    response_model=list[WorkerResponse],
)
def list_authenticated_app_workers(
    db: Session = Depends(get_db),
    target_app: TargetApp = Depends(get_current_target_app),
):
    """Convenience endpoint for the connected application to read its workers."""
    workers, _ = discovery_service.list_workers(db, target_app_id=target_app.id, limit=500)
    return workers


@router.get("/observation/ping")
def observation_ping(target_app: TargetApp = Depends(get_current_target_app)) -> dict:
    """Cheap connectivity check for SDK discovery startup (no DB writes)."""
    return {"status": "ok", "target_app_id": str(target_app.id)}
