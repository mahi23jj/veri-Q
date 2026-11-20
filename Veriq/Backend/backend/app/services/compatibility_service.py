"""Compatibility service: assembles domain views from the database.

All business rules live in :mod:`app.domain.compatibility.engine`; this module
only loads configuration and maps ORM rows to immutable views.
"""

from __future__ import annotations

import uuid
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.compatibility.engine import (
    AdapterView,
    CheckpointView,
    CompatibilityResult,
    ContractView,
    TaskView,
    evaluate,
)
from app.domain.planning.matrix import merge_assertions
from app.domain.scenarios.catalog import ScenarioDefinition, get_scenario
from app.models import (
    ApplicationAdapter,
    RegisteredTask,
    TargetApp,
    TaskCheckpoint,
    TaskScenarioSelection,
    TaskTestContract,
)
from app.services import checkpoint_service, task_contract_service


class ScenarioNotFoundError(Exception):
    pass


class TaskNotInApplicationError(Exception):
    pass


def adapter_views(db: Session, target_app_id: uuid.UUID) -> list[AdapterView]:
    rows = db.scalars(
        select(ApplicationAdapter)
        .where(ApplicationAdapter.target_app_id == target_app_id)
        .order_by(ApplicationAdapter.id)
    ).all()
    return [
        AdapterView(
            id=str(row.id),
            name=row.name,
            adapter_type=row.adapter_type,
            category=row.category,
            capabilities=frozenset(row.capabilities or []),
            enabled_triggers=frozenset(row.enabled_triggers or []),
            status=row.status,
        )
        for row in rows
    ]


def contract_view(contract: TaskTestContract | None) -> ContractView | None:
    if contract is None:
        return None
    return ContractView(
        id=str(contract.id),
        version=contract.version,
        payload=contract.payload or {},
        valid=bool((contract.validation or {}).get("valid", True)),
    )


def checkpoint_view(checkpoint: TaskCheckpoint | None) -> CheckpointView | None:
    if checkpoint is None:
        return None
    return CheckpointView(
        id=str(checkpoint.id),
        name=checkpoint.name,
        reliability_enabled=bool(checkpoint.reliability_enabled),
    )


def task_view(task: RegisteredTask) -> TaskView:
    return TaskView(id=str(task.id), task_name=task.task_name, status=task.status)


def get_task_in_application(
    db: Session, target_app_id: uuid.UUID, task_id: uuid.UUID
) -> RegisteredTask:
    task = db.get(RegisteredTask, task_id)
    if task is None or task.target_app_id != target_app_id:
        raise TaskNotInApplicationError(str(task_id))
    return task


def resolve_scenario(scenario_id: str) -> ScenarioDefinition:
    scenario = get_scenario(scenario_id)
    if scenario is None:
        raise ScenarioNotFoundError(scenario_id)
    return scenario


def evaluate_task_scenario(
    db: Session,
    task: RegisteredTask,
    scenario: ScenarioDefinition,
    *,
    trigger_type: str,
    checkpoint: TaskCheckpoint | None = None,
    contract: TaskTestContract | None = None,
    adapters: Sequence[AdapterView] | None = None,
) -> CompatibilityResult:
    """Evaluate one combination for a task already scoped to its application."""
    if contract is None:
        contract = task_contract_service.get_contract_for_task(db, task.id)
    if adapters is None:
        adapters = adapter_views(db, task.target_app_id)
    return evaluate(
        task=task_view(task),
        scenario=scenario,
        trigger_type=trigger_type,
        checkpoint=checkpoint_view(checkpoint),
        contract=contract_view(contract),
        adapters=adapters,
    )


def evaluate_selections(
    db: Session, target_app: TargetApp, selections: Iterable[Any]
) -> list[dict[str, Any]]:
    adapters = adapter_views(db, target_app.id)
    results: list[dict[str, Any]] = []
    for selection in selections:
        task = get_task_in_application(db, target_app.id, selection.task_id)
        scenario = resolve_scenario(selection.scenario_id)
        checkpoint = None
        if selection.checkpoint_id is not None:
            checkpoint = checkpoint_service.get_checkpoint(
                db, selection.checkpoint_id, target_app_id=target_app.id
            )
            if checkpoint.registered_task_id != task.id:
                raise TaskNotInApplicationError(
                    f"checkpoint {checkpoint.id} does not belong to task {task.id}"
                )
        result = evaluate_task_scenario(
            db,
            task,
            scenario,
            trigger_type=selection.trigger_type,
            checkpoint=checkpoint,
            adapters=adapters,
        )
        payload = result.to_dict()
        payload.update(
            {
                "task_id": task.id,
                "task_name": task.task_name,
                "checkpoint_id": checkpoint.id if checkpoint is not None else None,
            }
        )
        results.append(payload)
    return results


def task_overview(db: Session, task: RegisteredTask) -> tuple[list[dict], list[dict]]:
    """Automatic scenario choices and checkpoint choices for one task.

    A scenario with no stored selection is recommended (enabled) only when it is
    currently COMPATIBLE; an explicit row always wins, including opt-out.
    """
    from app.domain.scenarios.catalog import list_scenarios

    adapters = adapter_views(db, task.target_app_id)
    contract = task_contract_service.get_contract_for_task(db, task.id)
    selections = {
        row.scenario_id: row
        for row in db.scalars(
            select(TaskScenarioSelection).where(
                TaskScenarioSelection.registered_task_id == task.id
            )
        ).all()
    }

    automatic: list[dict] = []
    for scenario in list_scenarios():
        if not scenario.supports_automatic:
            continue
        result = evaluate_task_scenario(
            db,
            task,
            scenario,
            trigger_type="automatic",
            contract=contract,
            adapters=adapters,
        )
        stored = selections.get(scenario.id)
        selected_by_default = result.compatible
        automatic.append(
            {
                "scenario_id": scenario.id,
                "scenario_version": scenario.version,
                "name": scenario.name,
                "category": scenario.category,
                "description": scenario.description,
                "default_trigger_type": scenario.default_trigger_type,
                "supported_status": scenario.supported_status,
                "implementation_status": scenario.implementation_status,
                "enabled": stored.enabled if stored is not None else selected_by_default,
                "selected_by_default": selected_by_default,
                "config": stored.config if stored is not None else None,
                "compatibility": result.to_dict(),
            }
        )

    checkpoints = checkpoint_service.list_checkpoints(
        db, target_app_id=task.target_app_id, task_id=task.id
    )
    checkpoint_payloads: list[dict] = []
    for checkpoint in checkpoints:
        selections_by_scenario = checkpoint_service.list_selections(db, checkpoint)
        items: list[dict] = []
        for scenario in list_scenarios():
            if not scenario.supports_checkpoint:
                continue
            result = evaluate_task_scenario(
                db,
                task,
                scenario,
                trigger_type="checkpoint",
                checkpoint=checkpoint,
                contract=contract,
                adapters=adapters,
            )
            stored = selections_by_scenario.get(scenario.id)
            items.append(
                {
                    "scenario_id": scenario.id,
                    "scenario_version": scenario.version,
                    "name": scenario.name,
                    "category": scenario.category,
                    "enabled": bool(stored.enabled) if stored is not None else False,
                    "config": stored.config if stored is not None else None,
                    "assertion_overrides": (
                        list(stored.assertion_overrides or [])
                        if stored is not None
                        else None
                    ),
                    "compatibility": result.to_dict(),
                }
            )
        checkpoint_payloads.append(
            {
                "id": checkpoint.id,
                "target_app_id": checkpoint.target_app_id,
                "registered_task_id": checkpoint.registered_task_id,
                "name": checkpoint.name,
                "discovery_source": checkpoint.discovery_source,
                "first_seen_at": checkpoint.first_seen_at,
                "last_seen_at": checkpoint.last_seen_at,
                "report_count": checkpoint.report_count,
                "checkpoint_metadata": checkpoint.checkpoint_metadata,
                "reliability_enabled": checkpoint.reliability_enabled,
                "scenarios": items,
            }
        )
    return automatic, checkpoint_payloads


def merged_assertions(
    contract: TaskTestContract | None,
    overrides: Sequence[dict] | None,
) -> tuple[dict, ...]:
    task_level = (contract.payload or {}).get("assertions") if contract is not None else []
    return merge_assertions(task_level or [], overrides)


__all__ = [
    "ScenarioNotFoundError",
    "TaskNotInApplicationError",
    "adapter_views",
    "checkpoint_view",
    "contract_view",
    "evaluate_selections",
    "evaluate_task_scenario",
    "get_task_in_application",
    "merged_assertions",
    "resolve_scenario",
    "task_overview",
    "task_view",
]
