"""Checkpoint discovery and reliability-test configuration.

Two concepts stay separate:

* ``veriq.checkpoint("after_save")`` in normal execution is ordinary telemetry.
  It is stored in ``execution_events`` exactly as before and never blocks.
* The discovered ``task_checkpoints`` row is planning metadata: it records that
  this task reaches this boundary, and holds the developer's reliability-test
  choices for it.

Recording a checkpoint never reads or applies reliability configuration, so a
test configuration can never affect production execution.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.planning.schema_validation import validate_scenario_config
from app.domain.scenarios.catalog import get_scenario
from app.models import CheckpointScenarioSelection, RegisteredTask, TargetApp, TaskCheckpoint
from app.schemas.planning import ScenarioSelectionUpsert

CHECKPOINT_NAME_MAX_LENGTH = 150
# Only a bounded slice of the reported payload is kept as discovery metadata.
_MAX_METADATA_KEYS = 20
_MAX_METADATA_VALUE_LENGTH = 500


class CheckpointNotFoundError(Exception):
    pass


class InvalidCheckpointConfigurationError(Exception):
    def __init__(self, issues: list[str]):
        super().__init__("; ".join(issues))
        self.issues = issues


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def checkpoint_name_from_payload(payload: dict[str, Any] | None) -> str | None:
    """Extract the checkpoint name from an SDK event payload."""
    if not isinstance(payload, dict):
        return None
    value = payload.get("checkpoint")
    if not isinstance(value, str):
        return None
    name = value.strip()
    if not name:
        return None
    return name[:CHECKPOINT_NAME_MAX_LENGTH]


def _safe_metadata(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Keep bounded, non-checkpoint metadata; drop anything unserializable."""
    if not isinstance(payload, dict):
        return None
    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        if key == "checkpoint" or len(cleaned) >= _MAX_METADATA_KEYS:
            continue
        if not isinstance(key, str):
            continue
        name = key[:100]
        if isinstance(value, str):
            cleaned[name] = value[:_MAX_METADATA_VALUE_LENGTH]
        elif isinstance(value, (int, float, bool)) or value is None:
            cleaned[name] = value
        elif isinstance(value, (dict, list)):
            try:
                encoded = json.dumps(value, default=str)
            except (TypeError, ValueError):  # pragma: no cover - defensive
                continue
            if len(encoded) <= _MAX_METADATA_VALUE_LENGTH:
                cleaned[name] = value
    return cleaned or None


def record_checkpoint(
    db: Session,
    target_app: TargetApp,
    registered_task: RegisteredTask,
    *,
    payload: dict[str, Any] | None,
    occurred_at: datetime,
) -> TaskCheckpoint | None:
    """Upsert the discovered checkpoint for one reported event.

    Identity is (registered_task_id, name): repeated reports refresh
    ``last_seen_at`` and ``report_count`` rather than creating duplicates. The
    same name in another task is a different checkpoint.
    """
    name = checkpoint_name_from_payload(payload)
    if name is None:
        return None

    checkpoint = db.scalar(
        select(TaskCheckpoint).where(
            TaskCheckpoint.registered_task_id == registered_task.id,
            TaskCheckpoint.name == name,
        )
    )
    seen_at = _ensure_utc(occurred_at)
    metadata = _safe_metadata(payload)
    if checkpoint is None:
        checkpoint = TaskCheckpoint(
            target_app_id=target_app.id,
            registered_task_id=registered_task.id,
            name=name,
            discovery_source="SDK",
            first_seen_at=seen_at,
            last_seen_at=seen_at,
            report_count=1,
            checkpoint_metadata=metadata,
            reliability_enabled=False,
        )
        try:
            # A savepoint keeps a concurrent duplicate report from aborting the
            # surrounding execution-event transaction.
            with db.begin_nested():
                db.add(checkpoint)
                db.flush()
        except IntegrityError:
            checkpoint = db.scalar(
                select(TaskCheckpoint).where(
                    TaskCheckpoint.registered_task_id == registered_task.id,
                    TaskCheckpoint.name == name,
                )
            )
            if checkpoint is None:  # pragma: no cover - defensive
                return None
            checkpoint.last_seen_at = max(_ensure_utc(checkpoint.last_seen_at), seen_at)
            checkpoint.report_count = int(checkpoint.report_count or 0) + 1
            return checkpoint
        return checkpoint

    checkpoint.last_seen_at = max(_ensure_utc(checkpoint.last_seen_at), seen_at)
    checkpoint.report_count = int(checkpoint.report_count or 0) + 1
    if metadata:
        checkpoint.checkpoint_metadata = metadata
    return checkpoint


def list_checkpoints(
    db: Session, *, target_app_id: uuid.UUID, task_id: uuid.UUID | None = None
) -> list[TaskCheckpoint]:
    stmt = select(TaskCheckpoint).where(TaskCheckpoint.target_app_id == target_app_id)
    if task_id is not None:
        stmt = stmt.where(TaskCheckpoint.registered_task_id == task_id)
    return list(
        db.scalars(
            stmt.order_by(TaskCheckpoint.registered_task_id, TaskCheckpoint.first_seen_at)
        ).all()
    )


def get_checkpoint(
    db: Session, checkpoint_id: uuid.UUID, *, target_app_id: uuid.UUID | None = None
) -> TaskCheckpoint:
    checkpoint = db.get(TaskCheckpoint, checkpoint_id)
    if checkpoint is None or (
        target_app_id is not None and checkpoint.target_app_id != target_app_id
    ):
        raise CheckpointNotFoundError(str(checkpoint_id))
    return checkpoint


def set_reliability(
    db: Session, checkpoint: TaskCheckpoint, *, reliability_enabled: bool
) -> TaskCheckpoint:
    checkpoint.reliability_enabled = bool(reliability_enabled)
    db.commit()
    db.refresh(checkpoint)
    return checkpoint


def upsert_selection(
    db: Session,
    checkpoint: TaskCheckpoint,
    scenario_id: str,
    payload: ScenarioSelectionUpsert,
) -> CheckpointScenarioSelection:
    """Enable/disable one scenario at one checkpoint.

    Checkpoint selections are independent of task-level automatic selections.
    """
    scenario = get_scenario(scenario_id)
    issues: list[str] = []
    if scenario is None:
        raise InvalidCheckpointConfigurationError([f"unknown scenario '{scenario_id}'"])
    if not scenario.supports_checkpoint:
        issues.append(
            f"scenario '{scenario_id}' does not support checkpoint-triggered testing"
        )
    issues.extend(validate_scenario_config(scenario.configuration_schema, payload.config))
    if issues:
        raise InvalidCheckpointConfigurationError(issues)

    selection = db.scalar(
        select(CheckpointScenarioSelection).where(
            CheckpointScenarioSelection.checkpoint_id == checkpoint.id,
            CheckpointScenarioSelection.scenario_id == scenario_id,
        )
    )
    if selection is None:
        selection = CheckpointScenarioSelection(
            checkpoint_id=checkpoint.id,
            scenario_id=scenario_id,
            scenario_version=scenario.version,
        )
        db.add(selection)
    selection.enabled = bool(payload.enabled)
    selection.config = payload.config or None
    selection.scenario_version = scenario.version
    selection.assertion_overrides = (
        [assertion.model_dump(mode="json") for assertion in payload.assertion_overrides]
        if payload.assertion_overrides
        else None
    )
    db.commit()
    db.refresh(selection)
    return selection


def list_selections(
    db: Session, checkpoint: TaskCheckpoint
) -> dict[str, CheckpointScenarioSelection]:
    rows = db.scalars(
        select(CheckpointScenarioSelection).where(
            CheckpointScenarioSelection.checkpoint_id == checkpoint.id
        )
    ).all()
    return {row.scenario_id: row for row in rows}


def assertion_overrides_for(
    db: Session, checkpoint_ids: list[uuid.UUID]
) -> dict[tuple[uuid.UUID, str], list[dict[str, Any]]]:
    """Return overrides keyed by (checkpoint_id, scenario_id)."""
    if not checkpoint_ids:
        return {}
    rows = db.scalars(
        select(CheckpointScenarioSelection).where(
            CheckpointScenarioSelection.checkpoint_id.in_(checkpoint_ids),
            CheckpointScenarioSelection.enabled.is_(True),
        )
    ).all()
    return {
        (row.checkpoint_id, row.scenario_id): list(row.assertion_overrides or [])
        for row in rows
        if row.assertion_overrides
    }


__all__ = [
    "CheckpointNotFoundError",
    "InvalidCheckpointConfigurationError",
    "checkpoint_name_from_payload",
    "assertion_overrides_for",
    "get_checkpoint",
    "list_checkpoints",
    "list_selections",
    "record_checkpoint",
    "set_reliability",
    "upsert_selection",
]
