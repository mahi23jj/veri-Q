"""Dashboard/control endpoints for discovery, the task catalog and executions.

Mirrors the existing foundation convention: read endpoints are unauthenticated
like ``/applications`` and ``/experiments``; SDK writes use ``X-API-Key`` on the
observation-ingest routes.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.observation import (
    ExecutionEventResponse,
    RegisteredTaskResponse,
    TaskCatalogItem,
    TaskExecutionDetailResponse,
    TaskExecutionResponse,
    TaskObservationUpdate,
    WorkerResponse,
)
from app.schemas.target_app import PaginatedResponse
from app.services import discovery_service, observation_service

router = APIRouter(tags=["catalog"])


def _catalog_item(
    task, aggregates: dict[uuid.UUID, dict]
) -> TaskCatalogItem:
    item = TaskCatalogItem.model_validate(task)
    return item.model_copy(update=aggregates.get(task.id, {}))


@router.get("/registered-tasks", response_model=PaginatedResponse)
def list_registered_tasks(
    target_app_id: uuid.UUID | None = None,
    status: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    tasks, total = observation_service.list_registered_tasks(
        db, target_app_id=target_app_id, status=status, skip=skip, limit=limit
    )
    aggregates = observation_service.catalog_aggregates(db, tasks)
    return {
        "items": [_catalog_item(task, aggregates) for task in tasks],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.get("/registered-tasks/{task_id}", response_model=TaskCatalogItem)
def get_registered_task(task_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        task = discovery_service.get_registered_task(db, task_id)
    except discovery_service.RegisteredTaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail="registered task not found") from exc
    aggregates = observation_service.catalog_aggregates(db, [task])
    return _catalog_item(task, aggregates)


@router.patch("/registered-tasks/{task_id}/observation", response_model=TaskCatalogItem)
def update_task_observation(
    task_id: uuid.UUID, payload: TaskObservationUpdate, db: Session = Depends(get_db)
):
    """Enable, disable or reset ordinary execution telemetry for one task."""
    try:
        task = discovery_service.set_observation_status(db, task_id, payload.status)
    except discovery_service.RegisteredTaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail="registered task not found") from exc
    aggregates = observation_service.catalog_aggregates(db, [task])
    return _catalog_item(task, aggregates)


@router.get(
    "/registered-tasks/{task_id}/executions",
    response_model=PaginatedResponse,
)
def list_task_executions(
    task_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    try:
        task = discovery_service.get_registered_task(db, task_id)
    except discovery_service.RegisteredTaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail="registered task not found") from exc
    executions, total = observation_service.list_executions(
        db, target_app_id=task.target_app_id, task_name=task.task_name, skip=skip, limit=limit
    )
    return {
        "items": [TaskExecutionResponse.model_validate(row) for row in executions],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.get("/task-executions", response_model=PaginatedResponse)
def list_executions(
    target_app_id: uuid.UUID | None = None,
    task_name: str | None = None,
    status: str | None = None,
    celery_task_id: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    executions, total = observation_service.list_executions(
        db,
        target_app_id=target_app_id,
        task_name=task_name,
        status=status,
        celery_task_id=celery_task_id,
        skip=skip,
        limit=limit,
    )
    return {
        "items": [TaskExecutionResponse.model_validate(row) for row in executions],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.get("/task-executions/{execution_id}", response_model=TaskExecutionDetailResponse)
def get_execution(execution_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        execution = observation_service.get_execution_with_events(db, execution_id)
    except observation_service.ExecutionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="task execution not found") from exc
    return TaskExecutionDetailResponse.model_validate(execution)


@router.get(
    "/task-executions/{execution_id}/events",
    response_model=list[ExecutionEventResponse],
)
def list_execution_events(execution_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        return observation_service.list_execution_events(db, execution_id)
    except observation_service.ExecutionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="task execution not found") from exc


@router.get("/workers", response_model=PaginatedResponse)
def list_workers(
    target_app_id: uuid.UUID | None = None,
    status: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    workers, total = discovery_service.list_workers(
        db, target_app_id=target_app_id, status=status, skip=skip, limit=limit
    )
    return {
        "items": [WorkerResponse.model_validate(worker) for worker in workers],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.get("/workers/{worker_id}", response_model=WorkerResponse)
def get_worker(worker_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        return discovery_service.get_worker(db, worker_id)
    except discovery_service.WorkerNotFoundError as exc:
        raise HTTPException(status_code=404, detail="worker not found") from exc


@router.get(
    "/applications/{application_id}/registered-tasks",
    response_model=PaginatedResponse,
)
def list_application_tasks(
    application_id: uuid.UUID,
    status: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """Application-scoped catalog listing used by the dashboard."""
    try:
        discovery_service.get_target_app(db, application_id)
    except discovery_service.TargetAppNotFoundError as exc:
        raise HTTPException(status_code=404, detail="application not found") from exc
    tasks, total = observation_service.list_registered_tasks(
        db, target_app_id=application_id, status=status, skip=skip, limit=limit
    )
    aggregates = observation_service.catalog_aggregates(db, tasks)
    return {
        "items": [_catalog_item(task, aggregates) for task in tasks],
        "total": total,
        "skip": skip,
        "limit": limit,
    }
