"""Observation models: discovery + ordinary (non-experiment) execution telemetry.

These tables deliberately sit next to, not inside, the experiment evidence
tables. ``experiment_events`` stays the append-only record for experiment runs;
``task_executions`` records ordinary executions and may *optionally* point at an
``ExperimentRun`` when the SDK reported VeriQ experiment headers.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utcnow

try:
    from sqlalchemy.dialects.postgresql import JSONB as _JSONB

    JSONBType = _JSONB().with_variant(JSON(), "sqlite")
except Exception:  # pragma: no cover
    JSONBType = JSON()

# Observation state for a discovered task. Newly discovered tasks are
# DISCOVERED and their ordinary telemetry is stored; DISABLED stops storage.
# OBSERVING is the explicit "selected for observation" state.
TASK_OBSERVATION_STATUSES = ("DISCOVERED", "OBSERVING", "DISABLED")
# Only DISABLED suppresses ordinary telemetry. Discovery always continues.
TELEMETRY_SUPPRESSED_STATUSES = {"DISABLED"}

WORKER_STATUSES = ("ONLINE", "OFFLINE", "UNKNOWN")
TASK_EXECUTION_STATUSES = ("RUNNING", "SUCCEEDED", "FAILED", "RETRYING")
EXECUTION_EVENT_SOURCES = ("SDK", "BACKEND", "OBSERVER")

# Event types emitted by the Celery integration.
TASK_EVENT_TYPES = (
    "TASK_STARTED",
    "TASK_SUCCEEDED",
    "TASK_FAILED",
    "TASK_RETRY_REQUESTED",
    "TASK_CHECKPOINT",
)
WORKER_EVENT_TYPES = ("WORKER_STARTED", "WORKER_HEARTBEAT", "WORKER_SHUTTING_DOWN")

# A worker that has not been seen for this long is considered OFFLINE.
STALE_WORKER_SECONDS = 120


class RegisteredTask(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A Celery task registered in a target application.

    Only names and bookkeeping are stored — never the task function or its
    arguments.
    """

    __tablename__ = "registered_tasks"
    __table_args__ = (
        UniqueConstraint("target_app_id", "task_name", name="uq_registered_tasks_app_task_name"),
        CheckConstraint(
            "status IN ('DISCOVERED','OBSERVING','DISABLED')",
            name="ck_registered_tasks_status",
        ),
        Index("ix_registered_tasks_app_status", "target_app_id", "status"),
    )

    target_app_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("target_apps.id", ondelete="CASCADE"), nullable=False
    )
    task_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="DISCOVERED")
    discovery_source: Mapped[str] = mapped_column(String(50), nullable=False, default="SDK")
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    task_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONBType, nullable=True)

    executions: Mapped[list["TaskExecution"]] = relationship(
        "TaskExecution", back_populates="registered_task"
    )


class Worker(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One worker *process lifetime*, identified by the SDK's instance id.

    PID alone is insufficient because operating systems reuse PIDs, so the SDK
    also reports a process-start identity.
    """

    __tablename__ = "workers"
    __table_args__ = (
        UniqueConstraint(
            "target_app_id", "worker_instance_id", name="uq_workers_app_worker_instance"
        ),
        CheckConstraint("status IN ('ONLINE','OFFLINE','UNKNOWN')", name="ck_workers_status"),
        Index("ix_workers_app_status", "target_app_id", "status"),
    )

    target_app_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("target_apps.id", ondelete="CASCADE"), nullable=False
    )
    worker_instance_id: Mapped[str] = mapped_column(String(64), nullable=False)
    hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    worker_hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    process_start_identity: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="ONLINE")
    # Last set of task names this worker process registered, for operator
    # visibility. Canonical task records live in registered_tasks.
    registered_task_names: Mapped[list[str] | None] = mapped_column(JSONBType, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    queues: Mapped[list["WorkerQueue"]] = relationship(
        "WorkerQueue", back_populates="worker", cascade="all, delete-orphan"
    )
    executions: Mapped[list["TaskExecution"]] = relationship(
        "TaskExecution", back_populates="worker"
    )


class WorkerQueue(Base, UUIDPrimaryKeyMixin):
    """A queue associated with a worker. ``is_consumed`` distinguishes queues a
    worker actually consumes from queues that merely exist in app config."""

    __tablename__ = "worker_queues"
    __table_args__ = (
        UniqueConstraint("worker_id", "queue_name", name="uq_worker_queues_worker_queue"),
        Index("ix_worker_queues_queue_name", "queue_name"),
    )

    worker_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workers.id", ondelete="CASCADE"), nullable=False
    )
    queue_name: Mapped[str] = mapped_column(String(255), nullable=False)
    exchange: Mapped[str | None] = mapped_column(String(255), nullable=True)
    routing_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_configured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_consumed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    worker: Mapped["Worker"] = relationship("Worker", back_populates="queues")


class TaskExecution(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One actual execution attempt.

    ``execution_id`` is a fresh UUID per attempt, so several rows may share one
    ``celery_task_id`` (retries, redelivery, repeated tests). ``experiment_run_id``
    is optional: ordinary telemetry does not require an experiment.
    """

    __tablename__ = "task_executions"
    __table_args__ = (
        UniqueConstraint("execution_id", name="uq_task_executions_execution_id"),
        CheckConstraint(
            "status IN ('RUNNING','SUCCEEDED','FAILED','RETRYING')",
            name="ck_task_executions_status",
        ),
        Index("ix_task_executions_app_started_at", "target_app_id", "started_at"),
        Index("ix_task_executions_task_name", "target_app_id", "task_name"),
        Index("ix_task_executions_celery_task_id", "celery_task_id"),
    )

    target_app_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("target_apps.id", ondelete="CASCADE"), nullable=False
    )
    registered_task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("registered_tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    execution_id: Mapped[uuid.UUID] = mapped_column(nullable=False, default=uuid.uuid4)
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    task_name: Mapped[str] = mapped_column(String(255), nullable=False)
    worker_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workers.id", ondelete="SET NULL"), nullable=True
    )
    worker_instance_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    worker_hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    process_start_identity: Mapped[str | None] = mapped_column(String(255), nullable=True)
    queue_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    experiment_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("experiment_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    veriq_operation_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="RUNNING")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    registered_task: Mapped["RegisteredTask | None"] = relationship(
        "RegisteredTask", back_populates="executions"
    )
    worker: Mapped["Worker | None"] = relationship("Worker", back_populates="executions")
    events: Mapped[list["ExecutionEvent"]] = relationship(
        "ExecutionEvent", back_populates="task_execution"
    )


class ExecutionEvent(Base, UUIDPrimaryKeyMixin):
    """Append-only event belonging to one task execution."""

    __tablename__ = "execution_events"
    __table_args__ = (
        Index("ix_execution_events_execution_occurred", "task_execution_id", "occurred_at"),
        UniqueConstraint(
            "task_execution_id",
            "client_event_id",
            name="uq_execution_events_execution_client_event",
        ),
        CheckConstraint(
            "source IN ('SDK','BACKEND','OBSERVER')", name="ck_execution_events_source"
        ),
    )

    task_execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("task_executions.id", ondelete="RESTRICT"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="SDK")
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONBType, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    client_event_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    task_execution: Mapped["TaskExecution"] = relationship(
        "TaskExecution", back_populates="events"
    )
