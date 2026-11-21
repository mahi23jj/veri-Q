"""Schemas for the runtime execution layer."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class HttpRuntimeProfile(BaseModel):
    """How the runner reaches the HTTP fault proxy from inside the worker."""

    model_config = ConfigDict(extra="forbid")

    input_field: str | None = Field(
        default=None,
        description="Test-input key holding the dependency URL, rewritten to the fault proxy.",
        max_length=100,
    )
    url_env: str | None = Field(
        default=None, description="Environment variable holding the dependency base URL."
    )
    upstream_url: str | None = Field(
        default=None, description="Fixed upstream; defaults to the test input value."
    )
    advertised_host: str = Field(
        default="host.docker.internal",
        description="Host the isolated worker uses to reach the proxy on the runner host.",
    )


class DatabaseRuntimeProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url_env: str | None = Field(
        default=None,
        description="Environment variable rewritten to the database fault proxy.",
    )


class RuntimeProfileRequest(BaseModel):
    """Application runtime profile: how to launch the application's own image.

    No credentials: values are image names, commands, queue names and non-secret
    environment. The runner mints a run-scoped SDK key for the worker itself.
    """

    model_config = ConfigDict(extra="forbid")

    runtime_type: Literal["docker", "simulated"] = "docker"
    image: str | None = Field(default=None, max_length=300)
    worker_command: list[str] | None = None
    queue: str = Field(..., min_length=1, max_length=255)
    concurrency: int = 1
    broker_image: str | None = Field(default="redis:7-alpine", max_length=300)
    database_image: str | None = Field(default="postgres:16-alpine", max_length=300)
    env: dict[str, str] = Field(default_factory=dict)
    http: HttpRuntimeProfile | None = None
    database: DatabaseRuntimeProfile | None = None

    @field_validator("worker_command")
    @classmethod
    def _command_parts(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        if not all(isinstance(part, str) and part for part in value):
            raise ValueError("worker_command must be a list of non-empty strings")
        return value

    def to_profile(self) -> dict[str, Any]:
        data = self.model_dump(exclude_none=True)
        return data


class RuntimeProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    target_app_id: uuid.UUID
    runtime_config: dict[str, Any] | None


class RunnerCapabilitiesResponse(BaseModel):
    runner_enabled: bool
    runtime_types: dict[str, Any]
    supported_scenarios: list[dict[str, Any]]
    limits: dict[str, Any]
    isolation: str


class StartRunRequest(BaseModel):
    case_id: uuid.UUID | None = None
    case_key: str | None = Field(default=None, min_length=1, max_length=64)


class TestCaseRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    target_app_id: uuid.UUID
    test_plan_id: uuid.UUID
    test_plan_revision_id: uuid.UUID
    test_plan_test_case_id: uuid.UUID
    registered_task_id: uuid.UUID
    case_key: str
    scenario_id: str
    scenario_version: int
    trigger_type: str
    checkpoint_name: str | None
    lifecycle_state: str
    verdict: str | None
    logical_job_id: uuid.UUID
    celery_task_ids: list[str]
    environment_id: uuid.UUID | None
    error_message: str | None
    cancel_requested_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime
    recovery_policy: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "cancel_requested_at", "started_at", "finished_at", "created_at", "updated_at"
    )
    @classmethod
    def _as_utc(cls, value: datetime | None) -> datetime | None:
        return _utc(value)


class StartRunResponse(BaseModel):
    run: TestCaseRunResponse
    scheduled: bool
    next: str


class RunnerEnvironmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    test_case_run_id: uuid.UUID
    runtime_type: str
    namespace: str
    network_ref: str | None
    container_refs: list[dict[str, Any]]
    broker_ref: str | None
    database_ref: str | None
    proxy_refs: dict[str, Any]
    runtime_config_version: str
    provisioning_state: str
    readiness: dict[str, Any] | None
    error: str | None
    cleanup_state: str
    cleanup_error: str | None
    ready_at: datetime | None
    stopped_at: datetime | None
    cleaned_at: datetime | None


class RunnerWorkerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    test_case_run_id: uuid.UUID
    worker_key: str
    queue_name: str
    concurrency: int
    lifecycle_state: str
    container_ref: str | None
    hostname: str | None
    worker_instance_id: str | None
    started_at: datetime | None
    ready_at: datetime | None
    terminated_at: datetime | None
    termination_reason: str | None
    exit_info: dict[str, Any] | None
    error: str | None


class FaultEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    test_case_run_id: uuid.UUID
    scenario_id: str
    injector_type: str
    trigger_type: str
    trigger_ref: str | None
    state: str
    detail: dict[str, Any] | None
    error: str | None
    occurred_at: datetime
    activation_at: datetime | None
    deactivation_at: datetime | None


class RecoveryObservationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    test_case_run_id: uuid.UUID
    attempt_count: int
    retry_request_count: int
    subsequent_attempt_count: int
    fault_activated: bool
    recovery_duration_ms: int | None
    final_execution_state: str | None
    evidence_complete: bool
    missing_evidence: list[str]
    observation: dict[str, Any]
    error: str | None


class RuntimeEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    test_case_run_id: uuid.UUID
    source: str
    event_type: str
    payload: dict[str, Any] | None
    occurred_at: datetime


class VerdictResponse(BaseModel):
    run_id: uuid.UUID
    lifecycle_state: str
    verdict: str | None
    detail: dict[str, Any] | None
    attempts: int
    retries: int
    final_execution_state: str | None
    evidence_complete: bool
    scope: str = "execution_recovery_only"


class ObservedAttempt(BaseModel):
    execution_id: uuid.UUID
    celery_task_id: str | None
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    worker_instance_id: str | None
    duration_ms: int | None


class TestCaseRunDetail(BaseModel):
    run: TestCaseRunResponse
    configuration: dict[str, Any]
    environment: RunnerEnvironmentResponse | None = None
    workers: list[RunnerWorkerResponse] = Field(default_factory=list)
    fault_events: list[FaultEventResponse] = Field(default_factory=list)
    recovery: RecoveryObservationResponse | None = None
    runtime_events: list[RuntimeEventResponse] = Field(default_factory=list)
    observed_attempts: list[ObservedAttempt] = Field(default_factory=list)
    next: str


class RecoverRunsResponse(BaseModel):
    recovered: list[dict[str, Any]]


class CancelRunResponse(BaseModel):
    run: TestCaseRunResponse
    message: str
