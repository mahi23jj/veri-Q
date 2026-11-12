from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin

try:
    from sqlalchemy.dialects.postgresql import JSONB as _JSONB

    JSONBType = _JSONB().with_variant(JSON(), "sqlite")
except Exception:  # pragma: no cover
    JSONBType = JSON()

EVENT_SOURCES = ("API", "RUNNER", "SDK", "OBSERVER", "INVARIANT_CHECKER")


class ExperimentEvent(Base, UUIDPrimaryKeyMixin):
    """Append-only historical evidence for one run.

    There is intentionally no update path: a new fact is a new row.
    ``occurred_at`` is the event's own timestamp, which may differ from
    arrival order, so callers must not assume insertion order is chronological.
    """

    __tablename__ = "experiment_events"
    __table_args__ = (
        Index("ix_experiment_events_run_occurred_at", "experiment_run_id", "occurred_at"),
        # Client-supplied idempotency key (SDK event_id). NULLs are not
        # considered duplicates, so server-written events need no key.
        UniqueConstraint(
            "experiment_run_id", "client_event_id", name="uq_experiment_events_run_client_event"
        ),
        CheckConstraint(
            "source IN ('API','RUNNER','SDK','OBSERVER','INVARIANT_CHECKER')",
            name="ck_experiment_events_source",
        ),
    )

    experiment_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("experiment_runs.id", ondelete="RESTRICT"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONBType, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    client_event_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    experiment_run: Mapped["ExperimentRun"] = relationship("ExperimentRun", back_populates="events")
