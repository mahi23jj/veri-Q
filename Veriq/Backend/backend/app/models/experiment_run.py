from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin

try:
    from sqlalchemy.dialects.postgresql import JSONB as _JSONB

    JSONBType = _JSONB().with_variant(JSON(), "sqlite")
except Exception:  # pragma: no cover
    JSONBType = JSON()

RUN_STATUSES = (
    "PENDING",
    "PREPARING",
    "RUNNING",
    "VERIFYING",
    "COMPLETED",
    "FAILED",
    "ERROR",
    "INCONCLUSIVE",
    "CANCELLED",
)
RUN_VERDICTS = ("PASSED", "FAILED", "INCONCLUSIVE")

# Execution status (where the run is in the lifecycle) is deliberately kept
# separate from verdict (whether the business invariant held). A run whose
# status is FAILED/ERROR means the execution/infrastructure failed; it does
# not by itself mean the invariant check failed — that is the verdict.
FINISHED_STATUSES = {"COMPLETED", "FAILED", "ERROR", "INCONCLUSIVE", "CANCELLED"}


class ExperimentRun(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "experiment_runs"
    __table_args__ = (
        UniqueConstraint("experiment_id", "run_number", name="uq_experiment_runs_experiment_run_number"),
        CheckConstraint(
            "status IN ('PENDING','PREPARING','RUNNING','VERIFYING','COMPLETED','FAILED','ERROR','INCONCLUSIVE','CANCELLED')",
            name="ck_experiment_runs_status",
        ),
        CheckConstraint(
            "verdict IS NULL OR verdict IN ('PASSED','FAILED','INCONCLUSIVE')",
            name="ck_experiment_runs_verdict",
        ),
        CheckConstraint("run_number > 0", name="ck_experiment_runs_run_number"),
    )

    experiment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("experiments.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    run_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")
    verdict: Mapped[str | None] = mapped_column(String(30), nullable=True)
    operation_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    # Immutable snapshot of the experiment configuration at run creation.
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    experiment: Mapped["Experiment"] = relationship("Experiment", back_populates="runs")
    events: Mapped[list["ExperimentEvent"]] = relationship("ExperimentEvent", back_populates="experiment_run")
