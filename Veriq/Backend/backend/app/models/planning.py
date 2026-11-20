"""Reliability-test planning models.

These tables are additive: ordinary observability (registered_tasks, workers,
task_executions, execution_events) and experiment evidence are untouched.

Ownership is always the target application. Checkpoint identity is scoped to a
registered task, so the same checkpoint name in two tasks is two rows.
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

ADAPTER_STATUSES = ("CONFIGURED", "VALIDATED", "INVALID")

TEST_PLAN_STATUSES = (
    "DRAFT",
    "VALIDATING",
    "NEEDS_CHANGES",
    "READY_FOR_REVIEW",
    "APPROVED",
)

TEST_CASE_STATUSES = ("READY", "BLOCKED")


class TaskCheckpoint(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A discovered checkpoint: a named execution boundary of one task.

    Identity is (registered_task_id, name). Repeated SDK reports refresh
    ``last_seen_at``/``report_count`` instead of inserting new definitions.
    ``reliability_enabled`` is planning configuration only: it never affects
    ordinary checkpoint reporting.
    """

    __tablename__ = "task_checkpoints"
    __table_args__ = (
        UniqueConstraint(
            "registered_task_id", "name", name="uq_task_checkpoints_task_name"
        ),
        Index("ix_task_checkpoints_app_task", "target_app_id", "registered_task_id"),
    )

    target_app_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("target_apps.id", ondelete="CASCADE"), nullable=False
    )
    registered_task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("registered_tasks.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    discovery_source: Mapped[str] = mapped_column(String(50), nullable=False, default="SDK")
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    report_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Safe metadata only: the last reported payload minus the checkpoint name.
    checkpoint_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSONBType, nullable=True
    )
    reliability_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    selections: Mapped[list["CheckpointScenarioSelection"]] = relationship(
        "CheckpointScenarioSelection",
        back_populates="checkpoint",
        cascade="all, delete-orphan",
    )


class TaskScenarioSelection(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Task-level choice for one automatic scenario (enable / opt out)."""

    __tablename__ = "task_scenario_selections"
    __table_args__ = (
        UniqueConstraint(
            "registered_task_id", "scenario_id", name="uq_task_scenario_selections_task_scenario"
        ),
        Index("ix_task_scenario_selections_app", "target_app_id", "registered_task_id"),
    )

    target_app_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("target_apps.id", ondelete="CASCADE"), nullable=False
    )
    registered_task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("registered_tasks.id", ondelete="CASCADE"), nullable=False
    )
    scenario_id: Mapped[str] = mapped_column(String(100), nullable=False)
    scenario_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config: Mapped[dict[str, Any] | None] = mapped_column(JSONBType, nullable=True)


class CheckpointScenarioSelection(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Scenario enabled at one checkpoint, with optional assertion overrides.

    Checkpoint selections never modify task-level automatic selections.
    """

    __tablename__ = "checkpoint_scenario_selections"
    __table_args__ = (
        UniqueConstraint(
            "checkpoint_id", "scenario_id", name="uq_checkpoint_scenario_selections_cp_scenario"
        ),
    )

    checkpoint_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("task_checkpoints.id", ondelete="CASCADE"), nullable=False
    )
    scenario_id: Mapped[str] = mapped_column(String(100), nullable=False)
    scenario_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config: Mapped[dict[str, Any] | None] = mapped_column(JSONBType, nullable=True)
    assertion_overrides: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONBType, nullable=True
    )

    checkpoint: Mapped["TaskCheckpoint"] = relationship(
        "TaskCheckpoint", back_populates="selections"
    )


class TaskTestContract(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """The active Task Test Contract for one registered task.

    ``payload`` is the current version; every version is also appended to
    ``task_test_contract_versions`` so generated plans can keep referencing the
    exact contract revision they were built from.
    """

    __tablename__ = "task_test_contracts"
    __table_args__ = (
        UniqueConstraint("registered_task_id", name="uq_task_test_contracts_task"),
        Index("ix_task_test_contracts_app", "target_app_id"),
    )

    target_app_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("target_apps.id", ondelete="CASCADE"), nullable=False
    )
    registered_task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("registered_tasks.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False)
    validation: Mapped[dict[str, Any] | None] = mapped_column(JSONBType, nullable=True)
    last_validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    versions: Mapped[list["TaskTestContractVersion"]] = relationship(
        "TaskTestContractVersion",
        back_populates="contract",
        cascade="all, delete-orphan",
        order_by="TaskTestContractVersion.version",
    )


class TaskTestContractVersion(Base, UUIDPrimaryKeyMixin):
    """Immutable snapshot of one contract revision."""

    __tablename__ = "task_test_contract_versions"
    __table_args__ = (
        UniqueConstraint(
            "contract_id", "version", name="uq_task_test_contract_versions_contract_version"
        ),
    )

    contract_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("task_test_contracts.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False)
    validation: Mapped[dict[str, Any] | None] = mapped_column(JSONBType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    contract: Mapped["TaskTestContract"] = relationship(
        "TaskTestContract", back_populates="versions"
    )


class AdapterDefinition(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Application-registered custom adapter type metadata.

    Built-in types live in code; this table only represents custom types so an
    application can describe an integration VeriQ does not ship.
    """

    __tablename__ = "adapter_definitions"
    __table_args__ = (
        UniqueConstraint("target_app_id", "slug", name="uq_adapter_definitions_app_slug"),
    )

    target_app_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("target_apps.id", ondelete="CASCADE"), nullable=False
    )
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False, default="custom")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    capabilities: Mapped[list[str]] = mapped_column(JSONBType, nullable=False, default=list)
    supported_triggers: Mapped[list[str]] = mapped_column(
        JSONBType, nullable=False, default=list
    )
    version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0")


class ApplicationAdapter(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One adapter configured for a target application.

    ``configuration_ref`` is an opaque pointer (for example a secret-manager
    reference). Credentials themselves are never stored here.
    """

    __tablename__ = "application_adapters"
    __table_args__ = (
        UniqueConstraint("target_app_id", "name", name="uq_application_adapters_app_name"),
        CheckConstraint(
            "status IN ('CONFIGURED','VALIDATED','INVALID')",
            name="ck_application_adapters_status",
        ),
        Index("ix_application_adapters_app_category", "target_app_id", "category"),
    )

    target_app_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("target_apps.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    adapter_type: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    capabilities: Mapped[list[str]] = mapped_column(JSONBType, nullable=False, default=list)
    enabled_triggers: Mapped[list[str]] = mapped_column(
        JSONBType, nullable=False, default=list
    )
    configuration_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="CONFIGURED")
    validation: Mapped[dict[str, Any] | None] = mapped_column(JSONBType, nullable=True)
    validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class TestPlan(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A reviewed, approvable plan. Creating or approving it executes nothing."""

    __tablename__ = "test_plans"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT','VALIDATING','NEEDS_CHANGES','READY_FOR_REVIEW','APPROVED')",
            name="ck_test_plans_status",
        ),
        Index("ix_test_plans_app_status", "target_app_id", "status"),
    )

    target_app_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("target_apps.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="DRAFT")
    # Selected registered task ids (strings) as chosen by the developer.
    task_ids: Mapped[list[str]] = mapped_column(JSONBType, nullable=False, default=list)
    current_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    approved_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    revisions: Mapped[list["TestPlanRevision"]] = relationship(
        "TestPlanRevision",
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="TestPlanRevision.revision",
    )


class TestPlanRevision(Base, UUIDPrimaryKeyMixin):
    """Immutable generated matrix revision with its configuration snapshot."""

    __tablename__ = "test_plan_revisions"
    __table_args__ = (
        UniqueConstraint("test_plan_id", "revision", name="uq_test_plan_revisions_plan_revision"),
        CheckConstraint(
            "status IN ('DRAFT','VALIDATING','NEEDS_CHANGES','READY_FOR_REVIEW','APPROVED')",
            name="ck_test_plan_revisions_status",
        ),
    )

    test_plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("test_plans.id", ondelete="CASCADE"), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="VALIDATING")
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONBType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    invalidated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    plan: Mapped["TestPlan"] = relationship("TestPlan", back_populates="revisions")
    cases: Mapped[list["TestPlanTestCase"]] = relationship(
        "TestPlanTestCase", back_populates="revision", cascade="all, delete-orphan"
    )


class TestPlanTestCase(Base, UUIDPrimaryKeyMixin):
    """One generated, reproducible matrix row belonging to a plan revision."""

    __tablename__ = "test_plan_test_cases"
    __table_args__ = (
        UniqueConstraint(
            "test_plan_revision_id", "case_key", name="uq_test_plan_test_cases_revision_case"
        ),
        CheckConstraint(
            "status IN ('READY','BLOCKED')", name="ck_test_plan_test_cases_status"
        ),
        Index("ix_test_plan_test_cases_revision", "test_plan_revision_id"),
    )

    test_plan_revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("test_plan_revisions.id", ondelete="CASCADE"), nullable=False
    )
    case_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="READY")
    target_app_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("target_apps.id", ondelete="CASCADE"), nullable=False
    )
    registered_task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("registered_tasks.id", ondelete="CASCADE"), nullable=False
    )
    task_name: Mapped[str] = mapped_column(String(255), nullable=False)
    scenario_id: Mapped[str] = mapped_column(String(100), nullable=False)
    scenario_version: Mapped[int] = mapped_column(Integer, nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(30), nullable=False)
    checkpoint_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("task_checkpoints.id", ondelete="SET NULL"), nullable=True
    )
    checkpoint_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    contract_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    contract_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    adapter_refs: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONBType, nullable=False, default=list
    )
    test_input: Mapped[dict[str, Any] | None] = mapped_column(JSONBType, nullable=True)
    input_fixture_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    assertions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONBType, nullable=False, default=list
    )
    cleanup: Mapped[dict[str, Any] | None] = mapped_column(JSONBType, nullable=True)
    scenario_config: Mapped[dict[str, Any] | None] = mapped_column(JSONBType, nullable=True)
    compatibility: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False)
    configuration_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    revision: Mapped["TestPlanRevision"] = relationship(
        "TestPlanRevision", back_populates="cases"
    )
