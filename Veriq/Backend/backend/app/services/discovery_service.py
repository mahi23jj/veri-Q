"""Discovery services: registered tasks, worker instances and worker queues.

Discovery is deliberately separate from execution telemetry. A task is
discovered because it is registered in the Celery app, not because it ran, and
disabling observation never stops discovery.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models import RegisteredTask, TargetApp, Worker, WorkerQueue
from app.models.observation import STALE_WORKER_SECONDS
from app.schemas.observation import QueueReport, TaskDiscoveryCreate, WorkerEventCreate


class TargetAppNotFoundError(Exception):
    pass


class WorkerNotFoundError(Exception):
    pass


class RegisteredTaskNotFoundError(Exception):
    pass


def get_target_app(db: Session, target_app_id: uuid.UUID) -> TargetApp:
    app = db.get(TargetApp, target_app_id)
    if app is None:
        raise TargetAppNotFoundError(str(target_app_id))
    return app


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def discover_tasks(
    db: Session,
    target_app: TargetApp,
    payload: TaskDiscoveryCreate,
    *,
    commit: bool = True,
) -> list[RegisteredTask]:
    """Idempotently upsert registered tasks for one application.

    Repeated discovery updates ``last_seen_at`` only; it never duplicates rows
    and never changes an operator's observation selection.
    """
    now = _now()
    names = payload.task_names
    existing = {
        task.task_name: task
        for task in db.scalars(
            select(RegisteredTask).where(
                RegisteredTask.target_app_id == target_app.id,
                RegisteredTask.task_name.in_(names),
            )
        ).all()
    }

    results: list[RegisteredTask] = []
    for name in names:
        task = existing.get(name)
        if task is None:
            task = RegisteredTask(
                target_app_id=target_app.id,
                task_name=name,
                status="DISCOVERED",
                discovery_source=payload.source,
                first_seen_at=now,
                last_seen_at=now,
                discovered_at=now,
            )
            db.add(task)
        else:
            task.last_seen_at = now
            task.discovery_source = payload.source
        results.append(task)

    if not commit:
        db.flush()
        return results

    try:
        db.commit()
    except IntegrityError:
        # A concurrent discovery won the unique constraint. Roll back and
        # reload the rows instead of returning transient duplicates.
        db.rollback()
        for name in names:
            existing_task = db.scalar(
                select(RegisteredTask).where(
                    RegisteredTask.target_app_id == target_app.id,
                    RegisteredTask.task_name == name,
                )
            )
            if existing_task is not None:
                existing_task.last_seen_at = now
        db.commit()

    stored = {
        task.task_name: task
        for task in db.scalars(
            select(RegisteredTask).where(
                RegisteredTask.target_app_id == target_app.id,
                RegisteredTask.task_name.in_(names),
            )
        ).all()
    }
    return [stored[name] for name in names if name in stored]


def _upsert_queue(
    db: Session, worker: Worker, report: QueueReport, now: datetime
) -> WorkerQueue:
    queue = db.scalar(
        select(WorkerQueue).where(
            WorkerQueue.worker_id == worker.id,
            WorkerQueue.queue_name == report.name,
        )
    )
    if queue is None:
        queue = WorkerQueue(
            worker_id=worker.id,
            queue_name=report.name,
            exchange=report.exchange,
            routing_key=report.routing_key,
            is_configured=report.is_configured,
            is_consumed=report.is_consumed,
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(queue)
    else:
        queue.exchange = report.exchange or queue.exchange
        queue.routing_key = report.routing_key or queue.routing_key
        # Once observed as consumed/configured, keep that fact; a later report
        # that omits the flag must not erase it.
        queue.is_configured = queue.is_configured or report.is_configured
        queue.is_consumed = queue.is_consumed or report.is_consumed
        queue.last_seen_at = now
    return queue


def report_worker_event(
    db: Session, target_app: TargetApp, payload: WorkerEventCreate
) -> Worker:
    """Upsert a worker process and refresh its queues/registered task names."""
    now = payload.occurred_at or _now()
    worker = db.scalar(
        select(Worker).where(
            Worker.target_app_id == target_app.id,
            Worker.worker_instance_id == payload.worker_instance_id,
        )
    )
    if worker is None:
        worker = Worker(
            target_app_id=target_app.id,
            worker_instance_id=payload.worker_instance_id,
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(worker)
        db.flush()  # assign worker.id before inserting queues

    if payload.hostname:
        worker.hostname = payload.hostname
    if payload.worker_hostname:
        worker.worker_hostname = payload.worker_hostname
    if payload.pid is not None:
        worker.pid = payload.pid
    if payload.process_start_identity:
        worker.process_start_identity = payload.process_start_identity
    if payload.registered_tasks is not None:
        worker.registered_task_names = payload.registered_tasks
    worker.last_seen_at = now
    if payload.event_type == "WORKER_SHUTTING_DOWN":
        worker.status = "OFFLINE"
    else:
        worker.status = "ONLINE"

    for queue_report in payload.queues:
        _upsert_queue(db, worker, queue_report, now)

    # Worker inventory also proves the task exists in the app; record it without
    # altering observation selection.
    if payload.registered_tasks:
        discover_tasks(
            db,
            target_app,
            TaskDiscoveryCreate(task_names=payload.registered_tasks),
            commit=False,
        )

    db.commit()
    db.refresh(worker)
    return worker


def upsert_worker_from_execution(
    db: Session,
    target_app: TargetApp,
    *,
    worker_instance_id: str | None,
    hostname: str | None,
    pid: int | None,
    process_start_identity: str | None,
    seen_at: datetime,
) -> Worker | None:
    """Link an execution to a worker record, creating a minimal one if needed.

    A task can execute before ``worker_ready`` reaches the backend (or remote
    discovery may be unavailable), so telemetry must not depend on the worker
    report having arrived first.
    """
    if not worker_instance_id:
        return None
    worker = db.scalar(
        select(Worker).where(
            Worker.target_app_id == target_app.id,
            Worker.worker_instance_id == worker_instance_id,
        )
    )
    if worker is None:
        worker = Worker(
            target_app_id=target_app.id,
            worker_instance_id=worker_instance_id,
            hostname=hostname,
            worker_hostname=hostname,
            pid=pid,
            process_start_identity=process_start_identity,
            status="ONLINE",
            first_seen_at=seen_at,
            last_seen_at=seen_at,
        )
        db.add(worker)
        db.flush()
    else:
        if hostname and not worker.hostname:
            worker.hostname = hostname
        if hostname:
            worker.worker_hostname = worker.worker_hostname or hostname
        if pid is not None and worker.pid is None:
            worker.pid = pid
        if process_start_identity and not worker.process_start_identity:
            worker.process_start_identity = process_start_identity
        if seen_at > _ensure_utc(worker.last_seen_at):
            worker.last_seen_at = seen_at
        if worker.status != "ONLINE":
            worker.status = "ONLINE"
    return worker


def _effective_status(worker: Worker, *, now: datetime, stale_seconds: int) -> str:
    if worker.status == "ONLINE" and _ensure_utc(worker.last_seen_at) < now - timedelta(
        seconds=stale_seconds
    ):
        return "OFFLINE"
    return worker.status


def list_workers(
    db: Session,
    *,
    target_app_id: uuid.UUID | None = None,
    status: str | None = None,
    skip: int = 0,
    limit: int = 100,
    stale_seconds: int = STALE_WORKER_SECONDS,
) -> tuple[list[Worker], int]:
    now = _now()
    stmt = select(Worker).options(selectinload(Worker.queues))
    if target_app_id is not None:
        stmt = stmt.where(Worker.target_app_id == target_app_id)

    rows = list(db.scalars(stmt.order_by(Worker.last_seen_at.desc())).all())
    changed = False
    for worker in rows:
        effective = _effective_status(worker, now=now, stale_seconds=stale_seconds)
        if effective != worker.status:
            worker.status = effective
            changed = True
    if changed:
        db.commit()

    if status is not None:
        rows = [worker for worker in rows if worker.status == status]
    total = len(rows)
    return rows[skip : skip + limit], total


def get_worker(
    db: Session, worker_id: uuid.UUID, *, stale_seconds: int = STALE_WORKER_SECONDS
) -> Worker:
    worker = db.scalar(
        select(Worker).options(selectinload(Worker.queues)).where(Worker.id == worker_id)
    )
    if worker is None:
        raise WorkerNotFoundError(str(worker_id))
    effective = _effective_status(worker, now=_now(), stale_seconds=stale_seconds)
    if effective != worker.status:
        worker.status = effective
        db.commit()
        db.refresh(worker)
    return worker


def get_registered_task(db: Session, task_id: uuid.UUID) -> RegisteredTask:
    task = db.get(RegisteredTask, task_id)
    if task is None:
        raise RegisteredTaskNotFoundError(str(task_id))
    return task


def set_observation_status(
    db: Session, task_id: uuid.UUID, status: str
) -> RegisteredTask:
    task = get_registered_task(db, task_id)
    task.status = status
    task.last_seen_at = _now()
    db.commit()
    db.refresh(task)
    return task
