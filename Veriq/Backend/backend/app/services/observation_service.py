"""Services for ordinary task execution telemetry and the task catalog.

Ordinary telemetry is stored in ``task_executions``/``execution_events`` and
does not require an ExperimentRun. When the SDK does report VeriQ experiment
headers and the run belongs to the authenticated application, the execution is
linked to that run; otherwise the execution remains independent.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models import (
    ExecutionEvent,
    Experiment,
    ExperimentRun,
    RegisteredTask,
    TaskExecution,
    TargetApp,
)
from app.models.observation import TELEMETRY_SUPPRESSED_STATUSES
from app.schemas.observation import TaskExecutionEventCreate
from app.services import checkpoint_service, discovery_service

_TERMINAL_EVENTS = {
    "TASK_SUCCEEDED": "SUCCEEDED",
    "TASK_FAILED": "FAILED",
    "TASK_RETRY_REQUESTED": "RETRYING",
}


class ExecutionNotFoundError(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _get_or_create_registered_task(
    db: Session, target_app: TargetApp, task_name: str, now: datetime
) -> RegisteredTask:
    task = db.scalar(
        select(RegisteredTask).where(
            RegisteredTask.target_app_id == target_app.id,
            RegisteredTask.task_name == task_name,
        )
    )
    if task is None:
        task = RegisteredTask(
            target_app_id=target_app.id,
            task_name=task_name,
            status="DISCOVERED",
            discovery_source="SDK",
            first_seen_at=now,
            last_seen_at=now,
            discovered_at=now,
        )
        db.add(task)
        db.flush()
    else:
        task.last_seen_at = now
    return task


def _owned_run(
    db: Session, target_app: TargetApp, run_id: uuid.UUID | None
) -> ExperimentRun | None:
    """Return the run only when it belongs to this application.

    A stale/foreign ``veriq_run_id`` never fails ordinary telemetry: the
    execution is still stored, just without the experiment link.
    """
    if run_id is None:
        return None
    run = db.get(ExperimentRun, run_id)
    if run is None:
        return None
    experiment = db.get(Experiment, run.experiment_id)
    if experiment is None or experiment.target_app_id != target_app.id:
        return None
    return run


def _finish(execution: TaskExecution, event_type: str, occurred_at: datetime) -> None:
    status = _TERMINAL_EVENTS.get(event_type)
    if status is None:
        return
    execution.status = status
    execution.finished_at = occurred_at
    started = execution.started_at
    if started is not None:
        # SQLite (tests) may return naive datetimes; normalize before subtracting.
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        finished = occurred_at
        execution.duration_ms = max(0, int((finished - started).total_seconds() * 1000))


def report_execution_event(
    db: Session, target_app: TargetApp, payload: TaskExecutionEventCreate
) -> tuple[TaskExecution | None, ExecutionEvent | None, bool, str | None]:
    """Apply one SDK execution lifecycle event.

    Returns ``(execution, event, duplicate, reason)``. ``execution`` is ``None``
    when the event was intentionally not stored (observation disabled).
    """
    now = _now()
    occurred_at = payload.occurred_at or now
    started_at = payload.started_at or occurred_at

    registered_task = _get_or_create_registered_task(db, target_app, payload.task_name, now)
    if registered_task.status in TELEMETRY_SUPPRESSED_STATUSES:
        # Discovery continues (last_seen_at above), only telemetry is dropped.
        db.commit()
        return None, None, False, "observation disabled for this task"

    execution = db.scalar(
        select(TaskExecution).where(
            TaskExecution.target_app_id == target_app.id,
            TaskExecution.execution_id == payload.execution_id,
        )
    )

    if execution is None:
        run = _owned_run(db, target_app, payload.veriq_run_id)
        execution = TaskExecution(
            target_app_id=target_app.id,
            registered_task_id=registered_task.id,
            execution_id=payload.execution_id,
            celery_task_id=payload.celery_task_id,
            task_name=payload.task_name,
            worker_instance_id=payload.worker_instance_id,
            worker_hostname=payload.worker_hostname,
            pid=payload.pid,
            process_start_identity=payload.process_start_identity,
            queue_name=payload.queue_name,
            experiment_run_id=run.id if run is not None else None,
            veriq_operation_id=payload.veriq_operation_id,
            status="RUNNING",
            started_at=started_at,
        )
        db.add(execution)
        db.flush()
    else:
        # Identity fields are write-once: a later checkpoint must not rewrite
        # where/when the attempt started.
        if execution.registered_task_id is None:
            execution.registered_task_id = registered_task.id
        if execution.celery_task_id is None:
            execution.celery_task_id = payload.celery_task_id
        if execution.worker_instance_id is None:
            execution.worker_instance_id = payload.worker_instance_id
        if execution.worker_hostname is None:
            execution.worker_hostname = payload.worker_hostname
        if execution.pid is None:
            execution.pid = payload.pid
        if execution.process_start_identity is None:
            execution.process_start_identity = payload.process_start_identity
        if execution.queue_name is None:
            execution.queue_name = payload.queue_name
        if execution.experiment_run_id is None:
            run = _owned_run(db, target_app, payload.veriq_run_id)
            if run is not None:
                execution.experiment_run_id = run.id
        if execution.veriq_operation_id is None:
            execution.veriq_operation_id = payload.veriq_operation_id

    # Idempotency: one client event id per execution.
    if payload.event_id is not None:
        existing = db.scalar(
            select(ExecutionEvent).where(
                ExecutionEvent.task_execution_id == execution.id,
                ExecutionEvent.client_event_id == payload.event_id,
            )
        )
        if existing is not None:
            db.commit()
            return execution, existing, True, None

    if execution.worker_id is None and payload.worker_instance_id:
        worker = discovery_service.upsert_worker_from_execution(
            db,
            target_app,
            worker_instance_id=payload.worker_instance_id,
            hostname=payload.worker_hostname,
            pid=payload.pid,
            process_start_identity=payload.process_start_identity,
            seen_at=occurred_at,
        )
        if worker is not None:
            execution.worker_id = worker.id

    event = ExecutionEvent(
        task_execution_id=execution.id,
        event_type=payload.event_type,
        source="SDK",
        payload=payload.payload,
        occurred_at=occurred_at,
        client_event_id=payload.event_id,
    )
    db.add(event)

    # Checkpoint discovery is additive planning metadata: the event above is
    # still ordinary telemetry and the task is never blocked or paused.
    if payload.event_type == "TASK_CHECKPOINT":
        checkpoint_service.record_checkpoint(
            db,
            target_app,
            registered_task,
            payload=payload.payload,
            occurred_at=occurred_at,
        )
        # Test-only coordination: only a run that explicitly registered a
        # checkpoint waiter is affected. Production checkpoints stay report-only.
        from app.runtime import checkpoint_coordination

        checkpoint_coordination.notify_checkpoint(
            db,
            operation_id=execution.veriq_operation_id or payload.veriq_operation_id,
            checkpoint_name=(payload.payload or {}).get("checkpoint"),
            execution_id=execution.execution_id,
            celery_task_id=execution.celery_task_id,
            occurred_at=occurred_at,
        )

    if payload.event_type == "TASK_STARTED":
        if execution.status == "RUNNING" and payload.started_at is not None:
            execution.started_at = payload.started_at
    else:
        _finish(execution, payload.event_type, occurred_at)

    try:
        db.commit()
    except IntegrityError:
        # Concurrent duplicate submission: the unique constraint won.
        db.rollback()
        if payload.event_id is None:
            raise
        execution = db.scalar(
            select(TaskExecution).where(
                TaskExecution.target_app_id == target_app.id,
                TaskExecution.execution_id == payload.execution_id,
            )
        )
        if execution is None:
            raise
        existing = db.scalar(
            select(ExecutionEvent).where(
                ExecutionEvent.task_execution_id == execution.id,
                ExecutionEvent.client_event_id == payload.event_id,
            )
        )
        return execution, existing, existing is not None, None

    db.refresh(execution)
    db.refresh(event)
    return execution, event, False, None


def list_executions(
    db: Session,
    *,
    target_app_id: uuid.UUID | None = None,
    task_name: str | None = None,
    status: str | None = None,
    celery_task_id: str | None = None,
    skip: int = 0,
    limit: int = 100,
) -> tuple[list[TaskExecution], int]:
    stmt = select(TaskExecution)
    if target_app_id is not None:
        stmt = stmt.where(TaskExecution.target_app_id == target_app_id)
    if task_name is not None:
        stmt = stmt.where(TaskExecution.task_name == task_name)
    if status is not None:
        stmt = stmt.where(TaskExecution.status == status)
    if celery_task_id is not None:
        stmt = stmt.where(TaskExecution.celery_task_id == celery_task_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(TaskExecution.started_at.desc(), TaskExecution.id.desc())
        .offset(skip)
        .limit(limit)
    ).all()
    return list(rows), int(total)


def get_execution(db: Session, execution_id: uuid.UUID) -> TaskExecution:
    execution = db.get(TaskExecution, execution_id)
    if execution is None:
        raise ExecutionNotFoundError(str(execution_id))
    return execution


def list_execution_events(db: Session, execution_id: uuid.UUID) -> list[ExecutionEvent]:
    execution = get_execution(db, execution_id)
    rows = db.scalars(
        select(ExecutionEvent)
        .where(ExecutionEvent.task_execution_id == execution.id)
        .order_by(ExecutionEvent.occurred_at, ExecutionEvent.id)
    ).all()
    return list(rows)


def get_execution_with_events(db: Session, execution_id: uuid.UUID) -> TaskExecution:
    execution = db.scalar(
        select(TaskExecution)
        .options(selectinload(TaskExecution.events))
        .where(TaskExecution.id == execution_id)
    )
    if execution is None:
        raise ExecutionNotFoundError(str(execution_id))
    # Timeline order is by event time, not insertion order.
    execution.events.sort(key=lambda event: (event.occurred_at, str(event.id)))
    return execution


def list_registered_tasks(
    db: Session,
    *,
    target_app_id: uuid.UUID | None = None,
    status: str | None = None,
    skip: int = 0,
    limit: int = 100,
) -> tuple[list[RegisteredTask], int]:
    stmt = select(RegisteredTask)
    if target_app_id is not None:
        stmt = stmt.where(RegisteredTask.target_app_id == target_app_id)
    if status is not None:
        stmt = stmt.where(RegisteredTask.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(RegisteredTask.task_name.asc()).offset(skip).limit(limit)
    ).all()
    return list(rows), int(total)


def catalog_aggregates(
    db: Session, tasks: list[RegisteredTask]
) -> dict[uuid.UUID, dict[str, Any]]:
    """Bulk execution count / last execution / queues for catalog rows."""
    if not tasks:
        return {}
    task_ids = [task.id for task in tasks]
    app_ids = {task.target_app_id for task in tasks}

    counts = {
        task_id: (count, last_started)
        for task_id, count, last_started in db.execute(
            select(
                TaskExecution.registered_task_id,
                func.count(TaskExecution.id),
                func.max(TaskExecution.started_at),
            )
            .where(TaskExecution.registered_task_id.in_(task_ids))
            .group_by(TaskExecution.registered_task_id)
        ).all()
    }

    # Latest execution per task, used for the "recent outcome" column.
    latest: dict[uuid.UUID, TaskExecution] = {}
    recent_rows = db.scalars(
        select(TaskExecution)
        .where(TaskExecution.registered_task_id.in_(task_ids))
        .order_by(TaskExecution.started_at.desc())
    ).all()
    for row in recent_rows:
        if row.registered_task_id is not None and row.registered_task_id not in latest:
            latest[row.registered_task_id] = row

    # Queues observed per task name, scoped to the applications involved.
    queue_map: dict[str, set[str]] = {}
    queue_rows = db.execute(
        select(TaskExecution.task_name, TaskExecution.queue_name)
        .where(
            TaskExecution.target_app_id.in_(app_ids),
            TaskExecution.queue_name.is_not(None),
        )
        .distinct()
    ).all()
    for task_name, queue_name in queue_rows:
        if queue_name:
            queue_map.setdefault(task_name, set()).add(queue_name)

    result: dict[uuid.UUID, dict[str, Any]] = {}
    for task in tasks:
        count, last_started = counts.get(task.id, (0, None))
        recent = latest.get(task.id)
        result[task.id] = {
            "execution_count": int(count or 0),
            "last_execution_at": _ensure_utc(last_started),
            "last_outcome": recent.status if recent is not None else None,
            "queue_names": sorted(queue_map.get(task.task_name, set())),
        }
    return result


def recent_executions_for_task(
    db: Session, registered_task_id: uuid.UUID, limit: int = 20
) -> list[TaskExecution]:
    rows = db.scalars(
        select(TaskExecution)
        .where(TaskExecution.registered_task_id == registered_task_id)
        .order_by(TaskExecution.started_at.desc(), TaskExecution.id.desc())
        .limit(limit)
    ).all()
    return list(rows)
