from __future__ import annotations

from sqlalchemy import CheckConstraint, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

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

    experiments: Mapped[list["Experiment"]] = relationship(
        "Experiment", back_populates="target_app", passive_deletes=False
    )
