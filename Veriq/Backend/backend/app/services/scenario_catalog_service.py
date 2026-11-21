"""Read-only scenario catalogue access used by the API layer."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.domain.scenarios.catalog import (
    IMPLEMENTATION_STATUS_RUNNER,
    SCENARIO_CATALOG_VERSION,
    list_scenarios,
)
from app.services import adapter_registry_service


class ScenarioNotFoundError(Exception):
    pass


def scenarios(
    *, category: str | None = None, trigger_type: str | None = None
) -> list[dict[str, Any]]:
    return [
        scenario.to_dict()
        for scenario in list_scenarios(category=category, trigger_type=trigger_type)
    ]


def scenario_detail(scenario_id: str) -> dict[str, Any]:
    for scenario in list_scenarios():
        if scenario.id == scenario_id:
            return scenario.to_dict()
    raise ScenarioNotFoundError(scenario_id)


def catalog_metadata() -> dict[str, Any]:
    return {
        "catalog_version": SCENARIO_CATALOG_VERSION,
        "implementation_status": IMPLEMENTATION_STATUS_RUNNER,
        "note": (
            "Scenarios are represented, compatibility-checked and injected by the "
            "isolated runner. Planning and execution stay separate: an approved plan "
            "revision is required before a run can be started."
        ),
    }


def adapter_types(
    db: Session, *, target_app_id: uuid.UUID | None = None
) -> list[dict[str, Any]]:
    return [
        definition.to_dict()
        for definition in adapter_registry_service.list_adapter_types(
            db, target_app_id=target_app_id
        )
    ]
