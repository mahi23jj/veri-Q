"""initial schema: target_apps, experiments, experiment_runs, experiment_events

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-08

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "target_apps",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("environment", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("environment IN ('development', 'test')", name="ck_target_apps_environment"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_target_apps_name"),
    )
    op.create_table(
        "experiments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("target_app_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("task_name", sa.String(length=255), nullable=False),
        sa.Column("scenario", sa.String(length=100), nullable=False),
        sa.Column("checkpoint_name", sa.String(length=150), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("config_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("timeout_seconds > 0 AND timeout_seconds <= 3600", name="ck_experiments_timeout_seconds"),
        sa.ForeignKeyConstraint(["target_app_id"], ["target_apps.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_experiments_target_app_id", "experiments", ["target_app_id"])
    op.create_table(
        "experiment_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("experiment_id", sa.Uuid(), nullable=False),
        sa.Column("run_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("verdict", sa.String(length=30), nullable=True),
        sa.Column("operation_id", sa.Uuid(), nullable=True),
        sa.Column("config_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('PENDING','PREPARING','RUNNING','VERIFYING','COMPLETED','FAILED','ERROR','INCONCLUSIVE','CANCELLED')",
            name="ck_experiment_runs_status",
        ),
        sa.CheckConstraint("verdict IS NULL OR verdict IN ('PASSED','FAILED','INCONCLUSIVE')", name="ck_experiment_runs_verdict"),
        sa.CheckConstraint("run_number > 0", name="ck_experiment_runs_run_number"),
        sa.ForeignKeyConstraint(["experiment_id"], ["experiments.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("experiment_id", "run_number", name="uq_experiment_runs_experiment_run_number"),
    )
    op.create_index("ix_experiment_runs_experiment_id", "experiment_runs", ["experiment_id"])
    op.create_table(
        "experiment_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("experiment_run_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source IN ('API','RUNNER','SDK','OBSERVER','INVARIANT_CHECKER')",
            name="ck_experiment_events_source",
        ),
        sa.ForeignKeyConstraint(["experiment_run_id"], ["experiment_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_experiment_events_run_occurred_at", "experiment_events", ["experiment_run_id", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_experiment_events_run_occurred_at", table_name="experiment_events")
    op.drop_table("experiment_events")
    op.drop_index("ix_experiment_runs_experiment_id", table_name="experiment_runs")
    op.drop_table("experiment_runs")
    op.drop_index("ix_experiments_target_app_id", table_name="experiments")
    op.drop_table("experiments")
    op.drop_table("target_apps")
