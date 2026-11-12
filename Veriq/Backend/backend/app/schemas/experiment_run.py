from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

_TZ_FIELDS = ("created_at", "started_at", "finished_at")


class ExperimentRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    experiment_id: uuid.UUID
    run_number: int
    status: str
    verdict: str | None
    operation_id: uuid.UUID | None
    config_snapshot: dict[str, Any]
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    @field_validator(*_TZ_FIELDS)
    @classmethod
    def _as_utc(cls, value: datetime | None) -> datetime | None:
        # SQLite (tests) drops the offset; Postgres keeps it. Normalize to UTC.
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
