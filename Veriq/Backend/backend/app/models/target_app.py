from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, CheckConstraint, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

try:
    from sqlalchemy.dialects.postgresql import JSONB as _JSONB

    JSONBType = _JSONB().with_variant(JSON(), "sqlite")
except Exception:  # pragma: no cover
    JSONBType = JSON()

SUPPORTED_ENVIRONMENTS = ("development", "test")


class TargetApp(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "target_apps"
    __table_args__ = (
        UniqueConstraint("name", name="uq_target_apps_name"),
        UniqueConstraint("api_key_hash", name="uq_target_apps_api_key_hash"),
        CheckConstraint("environment IN ('development', 'test')", name="ck_target_apps_environment"),
    )

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # No credentials (DB passwords, broker URLs) are stored on this table by design.
    environment: Mapped[str] = mapped_column(String(30), nullable=False, default="development")
    # SHA-256 hex digest of the SDK/runner API key. The plaintext key is only
    # ever returned once, at creation or rotation time.
    api_key_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # How the isolated runner launches this application's own code. Contains no
    # credentials: only image names, commands and non-secret environment.
    runtime_config: Mapped[dict[str, Any] | None] = mapped_column(JSONBType, nullable=True)

    experiments: Mapped[list["Experiment"]] = relationship(
        "Experiment", back_populates="target_app", passive_deletes=False
    )
