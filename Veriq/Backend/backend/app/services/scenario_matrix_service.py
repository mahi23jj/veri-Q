"""Assemble and generate the scenario matrix for an application.

Selection rules:

* automatic scenario: a stored selection wins (including opt-out); otherwise the
  scenario is recommended and enabled only when it is currently COMPATIBLE.
* checkpoint scenario: an explicit enabled selection is required. Checkpoints
  are opt-in, and each checkpoint's selections are independent.

Only selected combinations are emitted. A selected combination that is no
longer compatible is emitted as BLOCKED with its reasons.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.compatibility.engine import (
    SEVERITY_CONFIGURATION,
    SEVERITY_WARNING,
    STATUS_NEEDS_CONFIGURATION,
    CompatibilityResult,
    Reason,
)
from app.domain.runtime.dependencies import (
    HTTP_PROXY_SCENARIOS,
    PROXY_NOT_ROUTED,
    dependency_issue,
    proxy_routes_requests,
)
from app.domain.planning.matrix import (
    EvaluatedCombination,
    MatrixResult,
    generate_matrix,
    merge_assertions,
)
from app.domain.runtime.recovery import RecoveryPolicy
from app.domain.scenarios.catalog import SCENARIO_CATALOG_VERSION, list_scenarios
from app.models import (
    CheckpointScenarioSelection,
    TargetApp,
    TaskScenarioSelection,
)
from app.services import checkpoint_service, compatibility_service, task_contract_service


def _adapter_refs(result) -> tuple[dict, ...]:
    refs: list[dict] = []
    for entry in result.selected_adapters:
        if "adapter_id" in entry:
            refs.append(dict(entry))
    return tuple(refs)


def _with_dependency_preflight(
    result: CompatibilityResult,
    *,
    scenario_id: str,
    scenario_config: dict[str, Any],
    safe_input: dict[str, Any],
    runtime_profile: dict[str, Any],
) -> CompatibilityResult:
    """Block an HTTP-proxy case when no upstream dependency can be resolved.

    The fault proxy is a real hop, so a case without an upstream could never
    activate its fault. Blocking it at generation keeps approval honest instead
    of surfacing the problem as a failed run.
    """
    if scenario_id not in HTTP_PROXY_SCENARIOS:
        return result
    configuration = {"test_input": safe_input, "scenario_config": scenario_config}
    issue = dependency_issue(configuration, runtime_profile)
    if issue is not None:
        return replace(
        result,
        status=STATUS_NEEDS_CONFIGURATION,
        reasons=result.reasons
        + (
            Reason(
                code=str(issue["code"]),
                severity=SEVERITY_CONFIGURATION,
                message=str(issue["message"]),
                field=issue.get("field"),
            ),
        ),
    )
    if proxy_routes_requests(configuration, runtime_profile):
        return result
    return replace(
        result,
        reasons=result.reasons
        + (
            Reason(
                code=PROXY_NOT_ROUTED,
                severity=SEVERITY_WARNING,
                message=(
                    "The fault proxy has an upstream URL, but nothing points the "
                    "task at it: add the dependency's absolute URL to the contract "
                    "safe input (or an http runtime profile input_field/url_env). "
                    "Otherwise the task calls the real dependency and the fault "
                    "never activates."
                ),
                field="contract.safe_input",
            ),
        ),
    )


def build_matrix(
    db: Session, target_app: TargetApp, task_ids: Sequence[uuid.UUID]
) -> tuple[MatrixResult, dict[str, Any]]:
    tasks = [
        compatibility_service.get_task_in_application(db, target_app.id, task_id)
        for task_id in dict.fromkeys(task_ids)
    ]
    tasks.sort(key=lambda task: task.task_name)
    adapters = compatibility_service.adapter_views(db, target_app.id)
    runtime_profile = dict(target_app.runtime_config or {})

    combinations: list[EvaluatedCombination] = []
    selection_snapshot: list[dict[str, Any]] = []

    for task in tasks:
        contract = task_contract_service.get_contract_for_task(db, task.id)
        automatic_rows = {
            row.scenario_id: row
            for row in db.scalars(
                select(TaskScenarioSelection).where(
                    TaskScenarioSelection.registered_task_id == task.id
                )
            ).all()
        }
        checkpoints = checkpoint_service.list_checkpoints(
            db, target_app_id=target_app.id, task_id=task.id
        )
        checkpoint_ids = [checkpoint.id for checkpoint in checkpoints]
        checkpoint_rows: dict[tuple[uuid.UUID, str], CheckpointScenarioSelection] = {}
        if checkpoint_ids:
            for row in db.scalars(
                select(CheckpointScenarioSelection).where(
                    CheckpointScenarioSelection.checkpoint_id.in_(checkpoint_ids)
                )
            ).all():
                checkpoint_rows[(row.checkpoint_id, row.scenario_id)] = row

        contract_payload = contract.payload if contract is not None else {}
        task_assertions = (contract_payload or {}).get("assertions") or []
        # Frozen into the generated case so later contract edits cannot change
        # what an existing approval means.
        recovery_policy = RecoveryPolicy.from_contract(contract_payload).to_dict()
        task_snapshot: dict[str, Any] = {
            "task_id": str(task.id),
            "task_name": task.task_name,
            "contract": (
                {"contract_id": str(contract.id), "version": contract.version}
                if contract is not None
                else None
            ),
            "automatic_scenarios": [],
            "checkpoints": [],
        }

        for scenario in list_scenarios():
            if not scenario.supports_automatic:
                continue
            result = compatibility_service.evaluate_task_scenario(
                db,
                task,
                scenario,
                trigger_type="automatic",
                contract=contract,
                adapters=adapters,
            )
            stored = automatic_rows.get(scenario.id)
            scenario_config = dict(stored.config or {}) if stored is not None else {}
            recommended = result.compatible
            # A recommended scenario with no usable upstream stays selected (so
            # the developer sees it) but is emitted as BLOCKED.
            result = _with_dependency_preflight(
                result,
                scenario_id=scenario.id,
                scenario_config=scenario_config,
                safe_input=dict((contract_payload or {}).get("safe_input") or {}),
                runtime_profile=runtime_profile,
            )
            enabled = stored.enabled if stored is not None else recommended
            task_snapshot["automatic_scenarios"].append(
                {
                    "scenario_id": scenario.id,
                    "scenario_version": scenario.version,
                    "enabled": enabled,
                    "explicitly_configured": stored is not None,
                    "config": stored.config if stored is not None else None,
                    "recommended_by_default": recommended,
                }
            )
            if not enabled:
                continue
            combinations.append(
                EvaluatedCombination(
                    target_app_id=str(target_app.id),
                    task_id=str(task.id),
                    task_name=task.task_name,
                    scenario_id=scenario.id,
                    scenario_version=scenario.version,
                    scenario_name=scenario.name,
                    scenario_category=scenario.category,
                    trigger_type="automatic",
                    checkpoint_id=None,
                    checkpoint_name=None,
                    contract_id=str(contract.id) if contract is not None else None,
                    contract_version=contract.version if contract is not None else None,
                    safe_input=dict((contract_payload or {}).get("safe_input") or {}),
                    input_fixture_ref=(contract_payload or {}).get("input_fixture_ref"),
                    assertions=merge_assertions(task_assertions, None),
                    cleanup=dict((contract_payload or {}).get("cleanup") or {}),
                    adapter_refs=_adapter_refs(result),
                    compatibility=result,
                    scenario_config=scenario_config,
                    recovery_policy=recovery_policy,
                )
            )

        for checkpoint in checkpoints:
            checkpoint_snapshot: dict[str, Any] = {
                "checkpoint_id": str(checkpoint.id),
                "name": checkpoint.name,
                "reliability_enabled": checkpoint.reliability_enabled,
                "scenarios": [],
            }
            for scenario in list_scenarios():
                if not scenario.supports_checkpoint:
                    continue
                stored = checkpoint_rows.get((checkpoint.id, scenario.id))
                enabled = bool(stored.enabled) if stored is not None else False
                result = compatibility_service.evaluate_task_scenario(
                    db,
                    task,
                    scenario,
                    trigger_type="checkpoint",
                    checkpoint=checkpoint,
                    contract=contract,
                    adapters=adapters,
                )
                scenario_config = dict(stored.config or {}) if stored is not None else {}
                result = _with_dependency_preflight(
                    result,
                    scenario_id=scenario.id,
                    scenario_config=scenario_config,
                    safe_input=dict((contract_payload or {}).get("safe_input") or {}),
                    runtime_profile=runtime_profile,
                )
                checkpoint_snapshot["scenarios"].append(
                    {
                        "scenario_id": scenario.id,
                        "scenario_version": scenario.version,
                        "enabled": enabled,
                        "config": stored.config if stored is not None else None,
                        "assertion_overrides": (
                            list(stored.assertion_overrides or [])
                            if stored is not None
                            else None
                        ),
                    }
                )
                if not enabled:
                    continue
                overrides = (
                    list(stored.assertion_overrides or []) if stored is not None else None
                )
                combinations.append(
                    EvaluatedCombination(
                        target_app_id=str(target_app.id),
                        task_id=str(task.id),
                        task_name=task.task_name,
                        scenario_id=scenario.id,
                        scenario_version=scenario.version,
                        scenario_name=scenario.name,
                        scenario_category=scenario.category,
                        trigger_type="checkpoint",
                        checkpoint_id=str(checkpoint.id),
                        checkpoint_name=checkpoint.name,
                        contract_id=str(contract.id) if contract is not None else None,
                        contract_version=contract.version if contract is not None else None,
                        safe_input=dict((contract_payload or {}).get("safe_input") or {}),
                        input_fixture_ref=(contract_payload or {}).get("input_fixture_ref"),
                        assertions=merge_assertions(task_assertions, overrides),
                        cleanup=dict((contract_payload or {}).get("cleanup") or {}),
                        adapter_refs=_adapter_refs(result),
                        compatibility=result,
                        scenario_config=scenario_config,
                        recovery_policy=recovery_policy,
                    )
                )
            task_snapshot["checkpoints"].append(checkpoint_snapshot)

        selection_snapshot.append(task_snapshot)

    snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scenario_catalog_version": SCENARIO_CATALOG_VERSION,
        "planning_engine_version": "1.0",
        "selection": selection_snapshot,
        "adapters": [
            {
                "adapter_id": adapter.id,
                "name": adapter.name,
                "adapter_type": adapter.adapter_type,
                "capabilities": sorted(adapter.capabilities),
                "enabled_triggers": sorted(adapter.enabled_triggers),
                "status": adapter.status,
            }
            for adapter in adapters
        ],
        "notes": "Execution is deferred; this snapshot only records planning inputs.",
    }
    return generate_matrix(combinations), snapshot


__all__ = ["build_matrix"]
