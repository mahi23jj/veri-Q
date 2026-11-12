from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

try:
    from sqlalchemy.dialects.postgresql import JSONB as _JSONB

    JSONBType = _JSONB().with_variant(JSON(), "sqlite")
except Exception:  # pragma: no cover
    JSONBType = JSON()

# Initial scenario supported by the platform.
SUPPORTED_SCENARIOS = ("crash_after_commit",)
# Status is stored as a plain string so future statuses can be added without
# widening this foundation; new rows always start as DRAFT.
MAX_TIMEOUT_SECONDS = 3600


class Experiment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "experiments"
    __table_args__ = (
        CheckConstraint(
            "timeout_seconds > 0 AND timeout_seconds <= 3600",
            name="ck_experiments_timeout_seconds",
        ),
    )

    target_app_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("target_apps.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_name: Mapped[str] = mapped_column(String(255), nullable=False)
    scenario: Mapped[str] = mapped_column(String(100), nullable=False, default="crash_after_commit")
    checkpoint_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="DRAFT")
    # config_snapshot is only populated when a run preserves the config at
    # run-creation time; it is not the mutable "current" configuration.
    config_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONBType, nullable=True)

    target_app: Mapped["TargetApp"] = relationship("TargetApp", back_populates="experiments")
    runs: Mapped[list["ExperimentRun"]] = relationship("ExperimentRun", back_populates="experiment")
