"""sdk auth: target_apps.api_key_hash + experiment_events.client_event_id

Revision ID: 0002_sdk_auth
Revises: 0001_initial
Create Date: 2026-11-11

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_sdk_auth"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable: applications registered before this revision have no key yet
    # and must rotate one explicitly (POST /applications/{id}/api-key).
    op.add_column("target_apps", sa.Column("api_key_hash", sa.String(length=64), nullable=True))
    op.create_unique_constraint("uq_target_apps_api_key_hash", "target_apps", ["api_key_hash"])

    # SDK-supplied idempotency key; NULL means "no idempotency key supplied".
    op.add_column("experiment_events", sa.Column("client_event_id", sa.Uuid(), nullable=True))
    op.create_unique_constraint(
        "uq_experiment_events_run_client_event",
        "experiment_events",
        ["experiment_run_id", "client_event_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_experiment_events_run_client_event", "experiment_events", type_="unique"
    )
    op.drop_column("experiment_events", "client_event_id")
    op.drop_constraint("uq_target_apps_api_key_hash", "target_apps", type_="unique")
    op.drop_column("target_apps", "api_key_hash")
