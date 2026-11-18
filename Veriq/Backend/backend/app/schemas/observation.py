"""Schemas for discovery, task executions and execution events."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

TaskEventType = Literal[
    "TASK_STARTED",
    "TASK_SUCCEEDED",
    "TASK_FAILED",
    "TASK_RETRY_REQUESTED",
    "TASK_CHECKPOINT",
]
WorkerEventType = Literal["WORKER_STARTED", "WORKER_HEARTBEAT", "WORKER_SHUTTING_DOWN"]
ObservationStatus = Literal["DISCOVERED", "OBSERVING", "DISABLED"]

SDK_EVENT_SOURCE = "SDK"

_DATETIME_FIELDS = ("occurred_at", "started_at", "finished_at")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("must be timezone-aware (UTC preferred)")
    return value.astimezone(timezone.utc)


def _normalize_optional(value: datetime | None) -> datetime | None:
    return _as_utc(value) if value is not None else None


def _non_empty(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("must not be empty")
    return value


class TaskExecutionEventCreate(BaseModel):
    """Body accepted by ``POST /task-executions/events``.

    The SDK reports one execution lifecycle event at a time. ``execution_id``
    identifies one actual attempt; ``event_id`` is the idempotency key.
    Experiment linkage is optional.
    """

    execution_id: uuid.UUID
    celery_task_id: str | None = Field(default=None, max_length=255)
    task_name: str = Field(..., min_length=1, max_length=255)
    worker_instance_id: str | None = Field(default=None, max_length=64)
    worker_hostname: str | None = Field(default=None, max_length=255)
    pid: int | None = Field(default=None, ge=0)
    process_start_identity: str | None = Field(default=None, max_length=255)
    queue_name: str | None = Field(default=None, max_length=255)
    veriq_run_id: uuid.UUID | None = None
    veriq_operation_id: uuid.UUID | None = None

    event_id: uuid.UUID | None = None
    event_type: TaskEventType
    occurred_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    payload: dict[str, Any] | None = None

    @field_validator("task_name")
    @classmethod
    def _task_name_not_empty(cls, value: str) -> str:
        return _non_empty(value)

    @field_validator(*_DATETIME_FIELDS)
    @classmethod
    def _datetimes_utc(cls, value: datetime | None) -> datetime | None:
        return _normalize_optional(value)


class ExecutionReportResponse(BaseModel):
    """Outcome of reporting one execution event."""

    execution_id: uuid.UUID
    stored: bool
    status: str | None = None
    event_id: uuid.UUID | None = None
    duplicate: bool = False
    reason: str | None = None


class ExecutionEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_execution_id: uuid.UUID
    event_type: str
    source: str
    payload: dict[str, Any] | None
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def _occurred_at_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class TaskExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    target_app_id: uuid.UUID
    registered_task_id: uuid.UUID | None
    execution_id: uuid.UUID
    celery_task_id: str | None
    task_name: str
    worker_id: uuid.UUID | None
    worker_instance_id: str | None
    worker_hostname: str | None
    pid: int | None
    process_start_identity: str | None
    queue_name: str | None
    experiment_run_id: uuid.UUID | None
    veriq_operation_id: uuid.UUID | None
    status: str
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    created_at: datetime
    updated_at: datetime

    @field_validator("started_at", "finished_at", "created_at", "updated_at")
    @classmethod
    def _as_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class TaskExecutionDetailResponse(TaskExecutionResponse):
    events: list[ExecutionEventResponse] = Field(default_factory=list)


class QueueReport(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    exchange: str | None = Field(default=None, max_length=255)
    routing_key: str | None = Field(default=None, max_length=255)
    is_configured: bool = True
    is_consumed: bool = False

    @field_validator("name")
    @classmethod
    def _name_not_empty(cls, value: str) -> str:
        return _non_empty(value)


class WorkerEventCreate(BaseModel):
    """Worker startup / heartbeat / shutdown report, including queues."""

    worker_instance_id: str = Field(..., min_length=1, max_length=64)
    event_type: WorkerEventType
    hostname: str | None = Field(default=None, max_length=255)
    worker_hostname: str | None = Field(default=None, max_length=255)
    pid: int | None = Field(default=None, ge=0)
    process_start_identity: str | None = Field(default=None, max_length=255)
    registered_tasks: list[str] | None = None
    queues: list[QueueReport] = Field(default_factory=list)
    occurred_at: datetime | None = None

    @field_validator("worker_instance_id")
    @classmethod
    def _instance_not_empty(cls, value: str) -> str:
        return _non_empty(value)

    @field_validator("occurred_at")
    @classmethod
    def _occurred_at_utc(cls, value: datetime | None) -> datetime | None:
        return _normalize_optional(value)

    @field_validator("registered_tasks")
    @classmethod
    def _task_names_clean(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned = [name.strip() for name in value if isinstance(name, str) and name.strip()]
        # Bound the payload; discovery is a catalog, not a task dump.
        return list(dict.fromkeys(cleaned))[:1000]


def _utc_or_none(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class WorkerQueueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    queue_name: str
    exchange: str | None
    routing_key: str | None
    is_configured: bool
    is_consumed: bool
    last_seen_at: datetime

    @field_validator("last_seen_at")
    @classmethod
    def _last_seen_utc(cls, value: datetime) -> datetime:
        return _utc_or_none(value) or value


class WorkerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    target_app_id: uuid.UUID
    worker_instance_id: str
    hostname: str | None
    worker_hostname: str | None
    pid: int | None
    process_start_identity: str | None
    status: str
    registered_task_names: list[str] | None
    first_seen_at: datetime
    last_seen_at: datetime
    queues: list[WorkerQueueResponse] = Field(default_factory=list)

    @field_validator("first_seen_at", "last_seen_at")
    @classmethod
    def _timestamps_utc(cls, value: datetime) -> datetime:
        return _utc_or_none(value) or value


class TaskDiscoveryCreate(BaseModel):
    """Registered task discovery payload (``celery_app.tasks`` keys)."""

    task_names: list[str] = Field(..., min_length=1, max_length=1000)
    source: str = Field(default="SDK", max_length=50)

    @field_validator("task_names")
    @classmethod
    def _clean_task_names(cls, value: list[str]) -> list[str]:
        cleaned = [name.strip() for name in value if isinstance(name, str) and name.strip()]
        if not cleaned:
            raise ValueError("at least one non-empty task name is required")
        return list(dict.fromkeys(cleaned))


class RegisteredTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    target_app_id: uuid.UUID
    task_name: str
    status: str
    discovery_source: str
    first_seen_at: datetime
    last_seen_at: datetime
    discovered_at: datetime
    task_metadata: dict[str, Any] | None

    @field_validator("first_seen_at", "last_seen_at", "discovered_at")
    @classmethod
    def _timestamps_utc(cls, value: datetime) -> datetime:
        return _utc_or_none(value) or value


class TaskObservationUpdate(BaseModel):
    status: ObservationStatus


class TaskCatalogItem(RegisteredTaskResponse):
    """Registered task plus cheap aggregates for the dashboard catalog."""

    execution_count: int = 0
    last_execution_at: datetime | None = None
    last_outcome: str | None = None
    queue_names: list[str] = Field(default_factory=list)

    @field_validator("last_execution_at")
    @classmethod
    def _last_execution_utc(cls, value: datetime | None) -> datetime | None:
        return _utc_or_none(value)
