"""Runtime models: one reliability test case execution and its isolated resources.

These tables are the *runtime* counterpart of the planning tables. Planning says
what may be tested and records approval; nothing here runs until a caller
explicitly starts a test case run.

Evidence is deliberately split by authority:

* ``task_executions`` / ``execution_events`` stay the single record of what the
  application reported (SDK). Nothing in this module duplicates them.
* ``runtime_events`` records runner/injector/broker facts (worker terminated,
  fault activated, message submitted) with their source preserved.
* ``test_case_runs.verdict`` is separate from ``lifecycle_state``: a run can be
  COMPLETED with a FAIL verdict.
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
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utcnow

try:
    from sqlalchemy.dialects.postgresql import JSONB as _JSONB

    JSONBType = _JSONB().with_variant(JSON(), "sqlite")
except Exception:  # pragma: no cover
    JSONBType = JSON()

LIFECYCLE_STATES = (
    "PENDING",
    "VALIDATING",
    "PROVISIONING",
    "PREPARING_FAULT",
    "STARTING",
    "RUNNING",
    "INJECTING",
    "OBSERVING_RECOVERY",
    "EVALUATING",
    "FINALIZING",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
)
TERMINAL_LIFECYCLE_STATES = ("COMPLETED", "FAILED", "CANCELLED")
ACTIVE_LIFECYCLE_STATES = tuple(
    state for state in LIFECYCLE_STATES if state not in TERMINAL_LIFECYCLE_STATES
)

VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"
VERDICT_INCONCLUSIVE = "INCONCLUSIVE"
VERDICT_INVALID_RUN = "INVALID_RUN"
VERDICT_ERROR = "ERROR"
VERDICTS = (
    VERDICT_PASS,
    VERDICT_FAIL,
    VERDICT_INCONCLUSIVE,
    VERDICT_INVALID_RUN,
    VERDICT_ERROR,
)

PROVISIONING_STATES = ("PENDING", "PROVISIONING", "READY", "FAILED", "STOPPED")
CLEANUP_STATES = ("PENDING", "CLEANING", "CLEANED", "FAILED")
WORKER_STATES = (
    "PENDING",
    "STARTING",
    "READY",
    "RUNNING",
    "TERMINATING",
    "TERMINATED",
    "FAILED",
    "STOPPED",
)
FAULT_STATES = ("PREPARING", "ARMED", "TRIGGERED", "ACTIVE", "RELEASED", "FAILED", "SKIPPED")
RUNTIME_EVENT_SOURCES = ("ORCHESTRATOR", "RUNNER", "INJECTOR", "BROKER", "OBSERVER", "CLEANUP")
CHECKPOINT_WAIT_STATES = ("WAITING", "ACKNOWLEDGED", "TIMED_OUT", "STALE", "DUPLICATE")


class TestCaseRun(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One execution of one approved test case.

    The overall verdict belongs here, not to an individual Celery attempt: one
    run may correlate several ``TaskExecution`` rows.
    """

    __tablename__ = "test_case_runs"
    __table_args__ = (
        CheckConstraint(
            "lifecycle_state IN ('PENDING','VALIDATING','PROVISIONING','PREPARING_FAULT',"
            "'STARTING','RUNNING','INJECTING','OBSERVING_RECOVERY','EVALUATING',"
            "'FINALIZING','COMPLETED','FAILED','CANCELLED')",
            name="ck_test_case_runs_lifecycle",
        ),
        CheckConstraint(
            "verdict IS NULL OR verdict IN ('PASS','FAIL','INCONCLUSIVE','INVALID_RUN','ERROR')",
            name="ck_test_case_runs_verdict",
        ),
        Index("ix_test_case_runs_app_created", "target_app_id", "created_at"),
        Index("ix_test_case_runs_state", "lifecycle_state"),
        Index("ix_test_case_runs_case", "test_plan_test_case_id"),
    )

    target_app_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("target_apps.id", ondelete="CASCADE"), nullable=False
    )
    registered_task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("registered_tasks.id", ondelete="CASCADE"), nullable=False
    )
    test_plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("test_plans.id", ondelete="CASCADE"), nullable=False
    )
    test_plan_revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("test_plan_revisions.id", ondelete="CASCADE"), nullable=False
    )
    test_plan_test_case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("test_plan_test_cases.id", ondelete="CASCADE"), nullable=False
    )
    case_key: Mapped[str] = mapped_column(String(64), nullable=False)
    scenario_id: Mapped[str] = mapped_column(String(100), nullable=False)
    scenario_version: Mapped[int] = mapped_column(Integer, nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(30), nullable=False)
    checkpoint_name: Mapped[str | None] = mapped_column(String(150), nullable=True)

    lifecycle_state: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")
    verdict: Mapped[str | None] = mapped_column(String(30), nullable=True)
    verdict_detail: Mapped[dict[str, Any] | None] = mapped_column(JSONBType, nullable=True)

    # Frozen at start: the exact configuration being executed.
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False)
    recovery_policy: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False)
    runtime_profile_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSONBType, nullable=True
    )

    # Identity: one logical job per run; every submitted message is listed.
    logical_job_id: Mapped[uuid.UUID] = mapped_column(nullable=False, default=uuid.uuid4)
    celery_task_ids: Mapped[list[str]] = mapped_column(JSONBType, nullable=False, default=list)

    environment_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    environment: Mapped["RunnerEnvironment | None"] = relationship(
        "RunnerEnvironment",
        back_populates="test_case_run",
        uselist=False,
        cascade="all, delete-orphan",
    )
    workers: Mapped[list["RunnerWorker"]] = relationship(
        "RunnerWorker",
        back_populates="test_case_run",
        cascade="all, delete-orphan",
        order_by="RunnerWorker.created_at",
    )
    faults: Mapped[list["FaultEvent"]] = relationship(
        "FaultEvent",
        back_populates="test_case_run",
        cascade="all, delete-orphan",
        order_by="FaultEvent.occurred_at",
    )
    recovery: Mapped["RecoveryObservation | None"] = relationship(
        "RecoveryObservation",
        back_populates="test_case_run",
        uselist=False,
        cascade="all, delete-orphan",
    )

    @property
    def terminal(self) -> bool:
        return self.lifecycle_state in TERMINAL_LIFECYCLE_STATES


class RunnerEnvironment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """The isolated runtime for one test case run.

    Secrets are never stored here: containers run on a private network with no
    published broker/database ports, so the provisioner needs no credentials to
    persist. Per-run SDK credentials are hashed in ``runner_credentials``.
    """

    __tablename__ = "runner_environments"
    __table_args__ = (
        UniqueConstraint("test_case_run_id", name="uq_runner_environments_run"),
        CheckConstraint(
            "provisioning_state IN ('PENDING','PROVISIONING','READY','FAILED','STOPPED')",
            name="ck_runner_environments_provisioning",
        ),
        CheckConstraint(
            "cleanup_state IN ('PENDING','CLEANING','CLEANED','FAILED')",
            name="ck_runner_environments_cleanup",
        ),
        Index("ix_runner_environments_namespace", "namespace"),
    )

    test_case_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("test_case_runs.id", ondelete="CASCADE"), nullable=False
    )
    runtime_type: Mapped[str] = mapped_column(String(30), nullable=False, default="docker")
    namespace: Mapped[str] = mapped_column(String(80), nullable=False)
    network_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    container_refs: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONBType, nullable=False, default=list
    )
    broker_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    database_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    proxy_refs: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)
    runtime_config_version: Mapped[str] = mapped_column(
        String(30), nullable=False, default="1.0"
    )

    provisioning_state: Mapped[str] = mapped_column(
        String(30), nullable=False, default="PENDING"
    )
    readiness: Mapped[dict[str, Any] | None] = mapped_column(JSONBType, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cleanup_state: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")
    cleanup_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cleaned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    test_case_run: Mapped["TestCaseRun"] = relationship(
        "TestCaseRun", back_populates="environment"
    )


class RunnerWorker(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Lifecycle of one dedicated worker instance (one process/container lifetime)."""

    __tablename__ = "runner_workers"
    __table_args__ = (
        UniqueConstraint(
            "test_case_run_id", "worker_key", name="uq_runner_workers_run_key"
        ),
        CheckConstraint(
            "lifecycle_state IN ('PENDING','STARTING','READY','RUNNING','TERMINATING',"
            "'TERMINATED','FAILED','STOPPED')",
            name="ck_runner_workers_state",
        ),
        Index("ix_runner_workers_run", "test_case_run_id"),
    )

    test_case_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("test_case_runs.id", ondelete="CASCADE"), nullable=False
    )
    environment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runner_environments.id", ondelete="CASCADE"), nullable=False
    )
    worker_key: Mapped[str] = mapped_column(String(80), nullable=False, default="primary")
    queue_name: Mapped[str] = mapped_column(String(255), nullable=False)
    concurrency: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    lifecycle_state: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")
    container_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Reported by the SDK, not assumed by the runner.
    worker_instance_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    termination_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    exit_info: Mapped[dict[str, Any] | None] = mapped_column(JSONBType, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    test_case_run: Mapped["TestCaseRun"] = relationship(
        "TestCaseRun", back_populates="workers"
    )


class FaultEvent(Base, UUIDPrimaryKeyMixin):
    """One fault state transition, append-only, scoped to one test case run."""

    __tablename__ = "fault_events"
    __table_args__ = (
        CheckConstraint(
            "state IN ('PREPARING','ARMED','TRIGGERED','ACTIVE','RELEASED','FAILED','SKIPPED')",
            name="ck_fault_events_state",
        ),
        Index("ix_fault_events_run_occurred", "test_case_run_id", "occurred_at"),
    )

    test_case_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("test_case_runs.id", ondelete="CASCADE"), nullable=False
    )
    scenario_id: Mapped[str] = mapped_column(String(100), nullable=False)
    injector_type: Mapped[str] = mapped_column(String(50), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(30), nullable=False)
    trigger_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    state: Mapped[str] = mapped_column(String(30), nullable=False)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONBType, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    activation_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deactivation_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    test_case_run: Mapped["TestCaseRun"] = relationship("TestCaseRun", back_populates="faults")


class RecoveryObservation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Derived recovery measurements plus the evidence they were derived from."""

    __tablename__ = "recovery_observations"
    __table_args__ = (
        UniqueConstraint("test_case_run_id", name="uq_recovery_observations_run"),
    )

    test_case_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("test_case_runs.id", ondelete="CASCADE"), nullable=False
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    subsequent_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fault_activated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    recovery_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_execution_state: Mapped[str | None] = mapped_column(String(30), nullable=True)
    evidence_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    missing_evidence: Mapped[list[str]] = mapped_column(JSONBType, nullable=False, default=list)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONBType, nullable=False, default=list)
    observation: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    test_case_run: Mapped["TestCaseRun"] = relationship(
        "TestCaseRun", back_populates="recovery"
    )


class RuntimeEvent(Base, UUIDPrimaryKeyMixin):
    """Append-only runner/injector/broker evidence for one test case run.

    Not a task-execution event log: application telemetry stays in
    ``execution_events``. This records what VeriQ's own components did.
    """

    __tablename__ = "runtime_events"
    __table_args__ = (
        CheckConstraint(
            "source IN ('ORCHESTRATOR','RUNNER','INJECTOR','BROKER','OBSERVER','CLEANUP')",
            name="ck_runtime_events_source",
        ),
        Index("ix_runtime_events_run_occurred", "test_case_run_id", "occurred_at"),
    )

    test_case_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("test_case_runs.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONBType, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class CheckpointWait(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Test-only checkpoint coordination record.

    Ordinary checkpoint reporting never creates a row here: only a run whose
    fault trigger is a checkpoint registers a wait.
    """

    __tablename__ = "checkpoint_waits"
    __table_args__ = (
        CheckConstraint(
            "state IN ('WAITING','ACKNOWLEDGED','TIMED_OUT','STALE','DUPLICATE')",
            name="ck_checkpoint_waits_state",
        ),
        Index("ix_checkpoint_waits_run", "test_case_run_id", "checkpoint_name"),
    )

    test_case_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("test_case_runs.id", ondelete="CASCADE"), nullable=False
    )
    checkpoint_name: Mapped[str] = mapped_column(String(150), nullable=False)
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    execution_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    state: Mapped[str] = mapped_column(String(30), nullable=False, default="WAITING")
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    timeout_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONBType, nullable=True)


class RunnerCredential(Base, UUIDPrimaryKeyMixin):
    """Run-scoped SDK credential for the isolated worker.

    Only the SHA-256 digest is stored; the plaintext key is injected into the
    test worker's environment and never persisted. Revoked during cleanup.
    """

    __tablename__ = "runner_credentials"
    __table_args__ = (
        UniqueConstraint("api_key_hash", name="uq_runner_credentials_hash"),
        Index("ix_runner_credentials_run", "test_case_run_id"),
    )

    test_case_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("test_case_runs.id", ondelete="CASCADE"), nullable=False
    )
    target_app_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("target_apps.id", ondelete="CASCADE"), nullable=False
    )
    api_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
