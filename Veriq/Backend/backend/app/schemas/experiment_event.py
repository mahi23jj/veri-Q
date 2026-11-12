from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# The API-key-authenticated ingestion route always records source="SDK"; the
# caller cannot spoof it. Other sources are written by the runner/observer.
SDK_EVENT_SOURCE = "SDK"


class ExperimentEventCreate(BaseModel):
    """Body accepted by ``POST /experiment-runs/{run_id}/events``.

    ``event_id`` is optional and used as an idempotency key: retrying the same
    event (same ``event_id``) never appends a second row.
    """

    event_id: uuid.UUID | None = None
    event_type: str = Field(..., min_length=1, max_length=100)
    occurred_at: datetime | None = None
    payload: dict[str, Any] | None = None

    @field_validator("event_type")
    @classmethod
    def _event_type_not_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @field_validator("occurred_at")
    @classmethod
    def _occurred_at_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("must be timezone-aware (UTC preferred)")
        return value.astimezone(timezone.utc)


class ExperimentEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    experiment_run_id: uuid.UUID
    event_type: str
    source: str
    payload: dict[str, Any] | None
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def _occurred_at_as_utc(cls, value: datetime) -> datetime:
        # Postgres returns timezone-aware values; SQLite (tests) drops the
        # offset. The API contract is always UTC, so normalize here.
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
