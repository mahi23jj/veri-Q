"""runtime execution: test case runs, environments, workers, faults, recovery

Revision ID: 0005_runtime
Revises: 0004_planning
Create Date: 2026-11-20

Additive. Existing observability tables remain the single record of application
task telemetry; these tables record VeriQ's own runtime facts.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_runtime"
down_revision: str | None = "0004_planning"
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
    op.add_column("target_apps", sa.Column("runtime_config", postgresql.JSONB(), nullable=True))
    op.add_column(
        "test_plan_test_cases",
        sa.Column("recovery_policy", postgresql.JSONB(), nullable=True),
    )

    op.create_table(
        "test_case_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("target_app_id", sa.Uuid(), nullable=False),
        sa.Column("registered_task_id", sa.Uuid(), nullable=False),
        sa.Column("test_plan_id", sa.Uuid(), nullable=False),
        sa.Column("test_plan_revision_id", sa.Uuid(), nullable=False),
        sa.Column("test_plan_test_case_id", sa.Uuid(), nullable=False),
        sa.Column("case_key", sa.String(length=64), nullable=False),
        sa.Column("scenario_id", sa.String(length=100), nullable=False),
        sa.Column("scenario_version", sa.Integer(), nullable=False),
        sa.Column("trigger_type", sa.String(length=30), nullable=False),
        sa.Column("checkpoint_name", sa.String(length=150), nullable=True),
        sa.Column("lifecycle_state", sa.String(length=30), nullable=False),
        sa.Column("verdict", sa.String(length=30), nullable=True),
        sa.Column("verdict_detail", postgresql.JSONB(), nullable=True),
        sa.Column("configuration", postgresql.JSONB(), nullable=False),
        sa.Column("recovery_policy", postgresql.JSONB(), nullable=False),
        sa.Column("runtime_profile_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("logical_job_id", sa.Uuid(), nullable=False),
        sa.Column("celery_task_ids", postgresql.JSONB(), nullable=False),
        sa.Column("environment_id", sa.Uuid(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "lifecycle_state IN ('PENDING','VALIDATING','PROVISIONING','PREPARING_FAULT',"
            "'STARTING','RUNNING','INJECTING','OBSERVING_RECOVERY','EVALUATING',"
            "'FINALIZING','COMPLETED','FAILED','CANCELLED')",
            name="ck_test_case_runs_lifecycle",
        ),
        sa.CheckConstraint(
            "verdict IS NULL OR verdict IN ('PASS','FAIL','INCONCLUSIVE','INVALID_RUN','ERROR')",
            name="ck_test_case_runs_verdict",
        ),
        sa.ForeignKeyConstraint(["target_app_id"], ["target_apps.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["registered_task_id"], ["registered_tasks.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["test_plan_id"], ["test_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["test_plan_revision_id"], ["test_plan_revisions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["test_plan_test_case_id"], ["test_plan_test_cases.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_test_case_runs_app_created", "test_case_runs", ["target_app_id", "created_at"]
    )
    op.create_index("ix_test_case_runs_state", "test_case_runs", ["lifecycle_state"])
    op.create_index("ix_test_case_runs_case", "test_case_runs", ["test_plan_test_case_id"])

    op.create_table(
        "runner_environments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("test_case_run_id", sa.Uuid(), nullable=False),
        sa.Column("runtime_type", sa.String(length=30), nullable=False),
        sa.Column("namespace", sa.String(length=80), nullable=False),
        sa.Column("network_ref", sa.String(length=200), nullable=True),
        sa.Column("container_refs", postgresql.JSONB(), nullable=False),
        sa.Column("broker_ref", sa.String(length=500), nullable=True),
        sa.Column("database_ref", sa.String(length=500), nullable=True),
        sa.Column("proxy_refs", postgresql.JSONB(), nullable=False),
        sa.Column("runtime_config_version", sa.String(length=30), nullable=False),
        sa.Column("provisioning_state", sa.String(length=30), nullable=False),
        sa.Column("readiness", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("cleanup_state", sa.String(length=30), nullable=False),
        sa.Column("cleanup_error", sa.Text(), nullable=True),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cleaned_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "provisioning_state IN ('PENDING','PROVISIONING','READY','FAILED','STOPPED')",
            name="ck_runner_environments_provisioning",
        ),
        sa.CheckConstraint(
            "cleanup_state IN ('PENDING','CLEANING','CLEANED','FAILED')",
            name="ck_runner_environments_cleanup",
        ),
        sa.ForeignKeyConstraint(
            ["test_case_run_id"], ["test_case_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("test_case_run_id", name="uq_runner_environments_run"),
    )
    op.create_index(
        "ix_runner_environments_namespace", "runner_environments", ["namespace"]
    )

    op.create_table(
        "runner_workers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("test_case_run_id", sa.Uuid(), nullable=False),
        sa.Column("environment_id", sa.Uuid(), nullable=False),
        sa.Column("worker_key", sa.String(length=80), nullable=False),
        sa.Column("queue_name", sa.String(length=255), nullable=False),
        sa.Column("concurrency", sa.Integer(), nullable=False),
        sa.Column("lifecycle_state", sa.String(length=30), nullable=False),
        sa.Column("container_ref", sa.String(length=200), nullable=True),
        sa.Column("hostname", sa.String(length=255), nullable=True),
        sa.Column("worker_instance_id", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("termination_reason", sa.String(length=200), nullable=True),
        sa.Column("exit_info", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "lifecycle_state IN ('PENDING','STARTING','READY','RUNNING','TERMINATING',"
            "'TERMINATED','FAILED','STOPPED')",
            name="ck_runner_workers_state",
        ),
        sa.ForeignKeyConstraint(
            ["test_case_run_id"], ["test_case_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["environment_id"], ["runner_environments.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("test_case_run_id", "worker_key", name="uq_runner_workers_run_key"),
    )
    op.create_index("ix_runner_workers_run", "runner_workers", ["test_case_run_id"])

    op.create_table(
        "fault_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("test_case_run_id", sa.Uuid(), nullable=False),
        sa.Column("scenario_id", sa.String(length=100), nullable=False),
        sa.Column("injector_type", sa.String(length=50), nullable=False),
        sa.Column("trigger_type", sa.String(length=30), nullable=False),
        sa.Column("trigger_ref", sa.String(length=200), nullable=True),
        sa.Column("state", sa.String(length=30), nullable=False),
        sa.Column("detail", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activation_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deactivation_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('PREPARING','ARMED','TRIGGERED','ACTIVE','RELEASED','FAILED','SKIPPED')",
            name="ck_fault_events_state",
        ),
        sa.ForeignKeyConstraint(
            ["test_case_run_id"], ["test_case_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_fault_events_run_occurred", "fault_events", ["test_case_run_id", "occurred_at"]
    )

    op.create_table(
        "recovery_observations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("test_case_run_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("retry_request_count", sa.Integer(), nullable=False),
        sa.Column("subsequent_attempt_count", sa.Integer(), nullable=False),
        sa.Column("fault_activated", sa.Boolean(), nullable=False),
        sa.Column("recovery_duration_ms", sa.Integer(), nullable=True),
        sa.Column("final_execution_state", sa.String(length=30), nullable=True),
        sa.Column("evidence_complete", sa.Boolean(), nullable=False),
        sa.Column("missing_evidence", postgresql.JSONB(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
        sa.Column("observation", postgresql.JSONB(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["test_case_run_id"], ["test_case_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("test_case_run_id", name="uq_recovery_observations_run"),
    )

    op.create_table(
        "runtime_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("test_case_run_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source IN ('ORCHESTRATOR','RUNNER','INJECTOR','BROKER','OBSERVER','CLEANUP')",
            name="ck_runtime_events_source",
        ),
        sa.ForeignKeyConstraint(
            ["test_case_run_id"], ["test_case_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_runtime_events_run_occurred", "runtime_events", ["test_case_run_id", "occurred_at"]
    )

    op.create_table(
        "checkpoint_waits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("test_case_run_id", sa.Uuid(), nullable=False),
        sa.Column("checkpoint_name", sa.String(length=150), nullable=False),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column("execution_id", sa.Uuid(), nullable=True),
        sa.Column("state", sa.String(length=30), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timeout_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("detail", postgresql.JSONB(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "state IN ('WAITING','ACKNOWLEDGED','TIMED_OUT','STALE','DUPLICATE')",
            name="ck_checkpoint_waits_state",
        ),
        sa.ForeignKeyConstraint(
            ["test_case_run_id"], ["test_case_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_checkpoint_waits_run", "checkpoint_waits", ["test_case_run_id", "checkpoint_name"]
    )

    op.create_table(
        "runner_credentials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("test_case_run_id", sa.Uuid(), nullable=False),
        sa.Column("target_app_id", sa.Uuid(), nullable=False),
        sa.Column("api_key_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["test_case_run_id"], ["test_case_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["target_app_id"], ["target_apps.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("api_key_hash", name="uq_runner_credentials_hash"),
    )
    op.create_index(
        "ix_runner_credentials_run", "runner_credentials", ["test_case_run_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_runner_credentials_run", table_name="runner_credentials")
    op.drop_table("runner_credentials")
    op.drop_index("ix_checkpoint_waits_run", table_name="checkpoint_waits")
    op.drop_table("checkpoint_waits")
    op.drop_index("ix_runtime_events_run_occurred", table_name="runtime_events")
    op.drop_table("runtime_events")
    op.drop_table("recovery_observations")
    op.drop_index("ix_fault_events_run_occurred", table_name="fault_events")
    op.drop_table("fault_events")
    op.drop_index("ix_runner_workers_run", table_name="runner_workers")
    op.drop_table("runner_workers")
    op.drop_index("ix_runner_environments_namespace", table_name="runner_environments")
    op.drop_table("runner_environments")
    op.drop_index("ix_test_case_runs_case", table_name="test_case_runs")
    op.drop_index("ix_test_case_runs_state", table_name="test_case_runs")
    op.drop_index("ix_test_case_runs_app_created", table_name="test_case_runs")
    op.drop_table("test_case_runs")
    op.drop_column("test_plan_test_cases", "recovery_policy")
    op.drop_column("target_apps", "runtime_config")
