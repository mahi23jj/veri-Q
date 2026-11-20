"""Task-level scenario selection (automatic test opt-in / opt-out)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.planning.schema_validation import validate_scenario_config
from app.domain.scenarios.catalog import ScenarioDefinition
from app.models import RegisteredTask, TaskScenarioSelection


class InvalidTaskScenarioConfigurationError(Exception):
    def __init__(self, issues: list[str]):
        super().__init__("; ".join(issues))
        self.issues = issues


def selections_for_task(
    db: Session, registered_task_id: uuid.UUID
) -> dict[str, TaskScenarioSelection]:
    rows = db.scalars(
        select(TaskScenarioSelection).where(
            TaskScenarioSelection.registered_task_id == registered_task_id
        )
    ).all()
    return {row.scenario_id: row for row in rows}


def upsert_selection(
    db: Session,
    registered_task: RegisteredTask,
    scenario: ScenarioDefinition,
    *,
    enabled: bool,
    config: dict[str, Any] | None,
) -> TaskScenarioSelection:
    """Persist one task-level opt-in/opt-out.

    Checkpoint selections live elsewhere and are never touched here.
    """
    if not scenario.supports_automatic:
        raise InvalidTaskScenarioConfigurationError(
            [f"scenario '{scenario.id}' does not support automatic testing"]
        )
    issues = validate_scenario_config(scenario.configuration_schema, config)
    if issues:
        raise InvalidTaskScenarioConfigurationError(issues)

    selection = db.scalar(
        select(TaskScenarioSelection).where(
            TaskScenarioSelection.registered_task_id == registered_task.id,
            TaskScenarioSelection.scenario_id == scenario.id,
        )
    )
    if selection is None:
        selection = TaskScenarioSelection(
            target_app_id=registered_task.target_app_id,
            registered_task_id=registered_task.id,
            scenario_id=scenario.id,
            scenario_version=scenario.version,
        )
        db.add(selection)
    selection.enabled = bool(enabled)
    selection.config = config or None
    selection.scenario_version = scenario.version
    try:
        db.commit()
    except IntegrityError as exc:  # pragma: no cover - unique race
        db.rollback()
        raise InvalidTaskScenarioConfigurationError(
            ["concurrent selection update; retry"]
        ) from exc
    db.refresh(selection)
    return selection
