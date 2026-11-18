"""discovery + observation: registered_tasks, workers, worker_queues,
task_executions, execution_events

Revision ID: 0003_observation
Revises: 0002_sdk_auth
Create Date: 2026-11-12

Ordinary background-job telemetry is stored separately from experiment
evidence. ``task_executions.experiment_run_id`` is nullable, so an execution
does not need an ExperimentRun, while experiment-linked executions can still
be associated with one.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_observation"
down_revision: str | None = "0002_sdk_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "registered_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("target_app_id", sa.Uuid(), nullable=False),
        sa.Column("task_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("discovery_source", sa.String(length=50), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("task_metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('DISCOVERED','OBSERVING','DISABLED')",
            name="ck_registered_tasks_status",
        ),
        sa.ForeignKeyConstraint(["target_app_id"], ["target_apps.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("target_app_id", "task_name", name="uq_registered_tasks_app_task_name"),
    )
    op.create_index(
        "ix_registered_tasks_app_status", "registered_tasks", ["target_app_id", "status"]
    )

    op.create_table(
        "workers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("target_app_id", sa.Uuid(), nullable=False),
        sa.Column("worker_instance_id", sa.String(length=64), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=True),
        sa.Column("worker_hostname", sa.String(length=255), nullable=True),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.Column("process_start_identity", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("registered_task_names", postgresql.JSONB(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('ONLINE','OFFLINE','UNKNOWN')", name="ck_workers_status"),
        sa.ForeignKeyConstraint(["target_app_id"], ["target_apps.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "target_app_id", "worker_instance_id", name="uq_workers_app_worker_instance"
        ),
    )
    op.create_index("ix_workers_app_status", "workers", ["target_app_id", "status"])

    op.create_table(
        "worker_queues",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("worker_id", sa.Uuid(), nullable=False),
        sa.Column("queue_name", sa.String(length=255), nullable=False),
        sa.Column("exchange", sa.String(length=255), nullable=True),
        sa.Column("routing_key", sa.String(length=255), nullable=True),
        sa.Column("is_configured", sa.Boolean(), nullable=False),
        sa.Column("is_consumed", sa.Boolean(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["worker_id"], ["workers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("worker_id", "queue_name", name="uq_worker_queues_worker_queue"),
    )
    op.create_index("ix_worker_queues_queue_name", "worker_queues", ["queue_name"])

    op.create_table(
        "task_executions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("target_app_id", sa.Uuid(), nullable=False),
        sa.Column("registered_task_id", sa.Uuid(), nullable=True),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column("task_name", sa.String(length=255), nullable=False),
        sa.Column("worker_id", sa.Uuid(), nullable=True),
        sa.Column("worker_instance_id", sa.String(length=64), nullable=True),
        sa.Column("worker_hostname", sa.String(length=255), nullable=True),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.Column("process_start_identity", sa.String(length=255), nullable=True),
        sa.Column("queue_name", sa.String(length=255), nullable=True),
        sa.Column("experiment_run_id", sa.Uuid(), nullable=True),
        sa.Column("veriq_operation_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('RUNNING','SUCCEEDED','FAILED','RETRYING')",
            name="ck_task_executions_status",
        ),
        sa.ForeignKeyConstraint(["target_app_id"], ["target_apps.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["registered_task_id"], ["registered_tasks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["worker_id"], ["workers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["experiment_run_id"], ["experiment_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("execution_id", name="uq_task_executions_execution_id"),
    )
    op.create_index(
        "ix_task_executions_app_started_at", "task_executions", ["target_app_id", "started_at"]
    )
    op.create_index(
        "ix_task_executions_task_name", "task_executions", ["target_app_id", "task_name"]
    )
    op.create_index("ix_task_executions_celery_task_id", "task_executions", ["celery_task_id"])
    op.create_index("ix_task_executions_registered_task_id", "task_executions", ["registered_task_id"])
    op.create_index("ix_task_executions_experiment_run_id", "task_executions", ["experiment_run_id"])

    op.create_table(
        "execution_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_execution_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("client_event_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "source IN ('SDK','BACKEND','OBSERVER')", name="ck_execution_events_source"
        ),
        sa.ForeignKeyConstraint(
            ["task_execution_id"], ["task_executions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_execution_id",
            "client_event_id",
            name="uq_execution_events_execution_client_event",
        ),
    )
    op.create_index(
        "ix_execution_events_execution_occurred",
        "execution_events",
        ["task_execution_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_execution_events_execution_occurred", table_name="execution_events")
    op.drop_table("execution_events")
    op.drop_index("ix_task_executions_experiment_run_id", table_name="task_executions")
    op.drop_index("ix_task_executions_registered_task_id", table_name="task_executions")
    op.drop_index("ix_task_executions_celery_task_id", table_name="task_executions")
    op.drop_index("ix_task_executions_task_name", table_name="task_executions")
    op.drop_index("ix_task_executions_app_started_at", table_name="task_executions")
    op.drop_table("task_executions")
    op.drop_index("ix_worker_queues_queue_name", table_name="worker_queues")
    op.drop_table("worker_queues")
    op.drop_index("ix_workers_app_status", table_name="workers")
    op.drop_table("workers")
    op.drop_index("ix_registered_tasks_app_status", table_name="registered_tasks")
    op.drop_table("registered_tasks")
