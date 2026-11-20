"""reliability test planning: checkpoints, contracts, adapters, scenarios, plans

Revision ID: 0004_planning
Revises: 0003_observation
Create Date: 2026-11-19

Purely additive: existing observability tables and the experiment tables are
unchanged. Checkpoint identity is scoped to (registered_task_id, name).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_planning"
down_revision: str | None = "0003_observation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "task_checkpoints",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("target_app_id", sa.Uuid(), nullable=False),
        sa.Column("registered_task_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("discovery_source", sa.String(length=50), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("report_count", sa.Integer(), nullable=False),
        sa.Column("checkpoint_metadata", postgresql.JSONB(), nullable=True),
        sa.Column("reliability_enabled", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["target_app_id"], ["target_apps.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["registered_task_id"], ["registered_tasks.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "registered_task_id", "name", name="uq_task_checkpoints_task_name"
        ),
    )
    op.create_index(
        "ix_task_checkpoints_app_task",
        "task_checkpoints",
        ["target_app_id", "registered_task_id"],
    )

    op.create_table(
        "task_scenario_selections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("target_app_id", sa.Uuid(), nullable=False),
        sa.Column("registered_task_id", sa.Uuid(), nullable=False),
        sa.Column("scenario_id", sa.String(length=100), nullable=False),
        sa.Column("scenario_version", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["target_app_id"], ["target_apps.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["registered_task_id"], ["registered_tasks.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "registered_task_id",
            "scenario_id",
            name="uq_task_scenario_selections_task_scenario",
        ),
    )
    op.create_index(
        "ix_task_scenario_selections_app",
        "task_scenario_selections",
        ["target_app_id", "registered_task_id"],
    )

    op.create_table(
        "checkpoint_scenario_selections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("checkpoint_id", sa.Uuid(), nullable=False),
        sa.Column("scenario_id", sa.String(length=100), nullable=False),
        sa.Column("scenario_version", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=True),
        sa.Column("assertion_overrides", postgresql.JSONB(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["checkpoint_id"], ["task_checkpoints.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "checkpoint_id", "scenario_id", name="uq_checkpoint_scenario_selections_cp_scenario"
        ),
    )

    op.create_table(
        "task_test_contracts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("target_app_id", sa.Uuid(), nullable=False),
        sa.Column("registered_task_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("validation", postgresql.JSONB(), nullable=True),
        sa.Column("last_validated_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["target_app_id"], ["target_apps.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["registered_task_id"], ["registered_tasks.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("registered_task_id", name="uq_task_test_contracts_task"),
    )
    op.create_index("ix_task_test_contracts_app", "task_test_contracts", ["target_app_id"])

    op.create_table(
        "task_test_contract_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("contract_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("validation", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["contract_id"], ["task_test_contracts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "contract_id", "version", name="uq_task_test_contract_versions_contract_version"
        ),
    )

    op.create_table(
        "adapter_definitions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("target_app_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("capabilities", postgresql.JSONB(), nullable=False),
        sa.Column("supported_triggers", postgresql.JSONB(), nullable=False),
        sa.Column("version", sa.String(length=20), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["target_app_id"], ["target_apps.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("target_app_id", "slug", name="uq_adapter_definitions_app_slug"),
    )

    op.create_table(
        "application_adapters",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("target_app_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("adapter_type", sa.String(length=100), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("capabilities", postgresql.JSONB(), nullable=False),
        sa.Column("enabled_triggers", postgresql.JSONB(), nullable=False),
        sa.Column("configuration_ref", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("validation", postgresql.JSONB(), nullable=True),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('CONFIGURED','VALIDATED','INVALID')",
            name="ck_application_adapters_status",
        ),
        sa.ForeignKeyConstraint(["target_app_id"], ["target_apps.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("target_app_id", "name", name="uq_application_adapters_app_name"),
    )
    op.create_index(
        "ix_application_adapters_app_category",
        "application_adapters",
        ["target_app_id", "category"],
    )

    op.create_table(
        "test_plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("target_app_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("task_ids", postgresql.JSONB(), nullable=False),
        sa.Column("current_revision", sa.Integer(), nullable=False),
        sa.Column("approved_revision", sa.Integer(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('DRAFT','VALIDATING','NEEDS_CHANGES','READY_FOR_REVIEW','APPROVED')",
            name="ck_test_plans_status",
        ),
        sa.ForeignKeyConstraint(["target_app_id"], ["target_apps.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_test_plans_app_status", "test_plans", ["target_app_id", "status"])

    op.create_table(
        "test_plan_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("test_plan_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("summary", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('DRAFT','VALIDATING','NEEDS_CHANGES','READY_FOR_REVIEW','APPROVED')",
            name="ck_test_plan_revisions_status",
        ),
        sa.ForeignKeyConstraint(["test_plan_id"], ["test_plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "test_plan_id", "revision", name="uq_test_plan_revisions_plan_revision"
        ),
    )

    op.create_table(
        "test_plan_test_cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("test_plan_revision_id", sa.Uuid(), nullable=False),
        sa.Column("case_key", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("target_app_id", sa.Uuid(), nullable=False),
        sa.Column("registered_task_id", sa.Uuid(), nullable=False),
        sa.Column("task_name", sa.String(length=255), nullable=False),
        sa.Column("scenario_id", sa.String(length=100), nullable=False),
        sa.Column("scenario_version", sa.Integer(), nullable=False),
        sa.Column("trigger_type", sa.String(length=30), nullable=False),
        sa.Column("checkpoint_id", sa.Uuid(), nullable=True),
        sa.Column("checkpoint_name", sa.String(length=150), nullable=True),
        sa.Column("contract_id", sa.Uuid(), nullable=True),
        sa.Column("contract_version", sa.Integer(), nullable=True),
        sa.Column("adapter_refs", postgresql.JSONB(), nullable=False),
        sa.Column("test_input", postgresql.JSONB(), nullable=True),
        sa.Column("input_fixture_ref", sa.String(length=500), nullable=True),
        sa.Column("assertions", postgresql.JSONB(), nullable=False),
        sa.Column("cleanup", postgresql.JSONB(), nullable=True),
        sa.Column("scenario_config", postgresql.JSONB(), nullable=True),
        sa.Column("compatibility", postgresql.JSONB(), nullable=False),
        sa.Column("configuration_fingerprint", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "status IN ('READY','BLOCKED')", name="ck_test_plan_test_cases_status"
        ),
        sa.ForeignKeyConstraint(
            ["test_plan_revision_id"], ["test_plan_revisions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["target_app_id"], ["target_apps.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["registered_task_id"], ["registered_tasks.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["checkpoint_id"], ["task_checkpoints.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "test_plan_revision_id", "case_key", name="uq_test_plan_test_cases_revision_case"
        ),
    )
    op.create_index(
        "ix_test_plan_test_cases_revision", "test_plan_test_cases", ["test_plan_revision_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_test_plan_test_cases_revision", table_name="test_plan_test_cases")
    op.drop_table("test_plan_test_cases")
    op.drop_table("test_plan_revisions")
    op.drop_index("ix_test_plans_app_status", table_name="test_plans")
    op.drop_table("test_plans")
    op.drop_index("ix_application_adapters_app_category", table_name="application_adapters")
    op.drop_table("application_adapters")
    op.drop_table("adapter_definitions")
    op.drop_table("task_test_contract_versions")
    op.drop_index("ix_task_test_contracts_app", table_name="task_test_contracts")
    op.drop_table("task_test_contracts")
    op.drop_table("checkpoint_scenario_selections")
    op.drop_index("ix_task_scenario_selections_app", table_name="task_scenario_selections")
    op.drop_table("task_scenario_selections")
    op.drop_index("ix_task_checkpoints_app_task", table_name="task_checkpoints")
    op.drop_table("task_checkpoints")
