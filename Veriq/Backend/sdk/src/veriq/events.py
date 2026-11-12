"""Structured event model matching the backend ingestion contract.

The backend owns the row identifier, the ``source`` ("SDK" is forced by the
route) and authorization. The SDK owns the event's own ``event_id``, which the
backend also uses as an idempotency key, plus the occurrence timestamp.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from veriq.exceptions import VeriQValidationError

EVENT_TYPE_MAX_LENGTH = 100

__all__ = ["VeriQEvent", "EVENT_TYPE_MAX_LENGTH"]


def _parse_uuid(value: uuid.UUID | str, field_name: str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise VeriQValidationError(f"{field_name} must be a valid UUID") from exc


def _normalize_occurred_at(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if not isinstance(value, datetime):
        raise VeriQValidationError("occurred_at must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise VeriQValidationError("occurred_at must be timezone-aware")
    return value.astimezone(timezone.utc)


def _validate_event_type(value: str) -> str:
    if not isinstance(value, str):
        raise VeriQValidationError("event_type must be a string")
    event_type = value.strip()
    if not event_type:
        raise VeriQValidationError("event_type must not be empty")
    if len(event_type) > EVENT_TYPE_MAX_LENGTH:
        raise VeriQValidationError(
            f"event_type must be at most {EVENT_TYPE_MAX_LENGTH} characters"
        )
    return event_type


@dataclass(frozen=True)
class VeriQEvent:
    """One immutable SDK event waiting to be recorded against a run."""

    event_id: uuid.UUID
    experiment_run_id: uuid.UUID
    event_type: str
    occurred_at: datetime
    payload: dict[str, Any] | None = field(default=None)

    @classmethod
    def create(
        cls,
        experiment_run_id: uuid.UUID | str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        occurred_at: datetime | None = None,
        event_id: uuid.UUID | str | None = None,
    ) -> "VeriQEvent":
        """Build an event, generating a UUID and UTC timestamp by default.

        Pass ``event_id`` to reuse an existing identity when re-sending the
        same fact manually; keep it stable across retries of that attempt.
        """
        if payload is not None and not isinstance(payload, dict):
            raise VeriQValidationError("payload must be a dict or None")
        return cls(
            event_id=_parse_uuid(event_id, "event_id") if event_id is not None else uuid.uuid4(),
            experiment_run_id=_parse_uuid(experiment_run_id, "experiment_run_id"),
            event_type=_validate_event_type(event_type),
            occurred_at=_normalize_occurred_at(occurred_at),
            payload=payload,
        )

    def to_request_body(self) -> dict[str, Any]:
        """Serialize to the backend's ``ExperimentEventCreate`` schema."""
        body: dict[str, Any] = {
            "event_id": str(self.event_id),
            "event_type": self.event_type,
            "occurred_at": self.occurred_at.isoformat(),
        }
        if self.payload is not None:
            body["payload"] = self.payload
        return body
