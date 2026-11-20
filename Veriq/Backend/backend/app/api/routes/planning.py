"""Reliability-test planning API.

Every application-scoped route resolves the application first and then verifies
that each nested resource belongs to it, so one application can never read or
change another's contracts, adapters, checkpoints or plans.

These routes plan only. Nothing here executes a task, launches a worker, injects
a failure or approves an experiment run.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import TargetApp
from app.schemas.observation import RegisteredTaskResponse
from app.schemas.planning import (
    AdapterCreate,
    AdapterDefinitionCreate,
    AdapterResponse,
    AdapterTypeResponse,
    AdapterUpdate,
    CheckpointReliabilityUpdate,
    CheckpointResponse,
    CheckpointScenarioItem,
    CheckpointWithScenarios,
    CompatibilityEvaluateRequest,
    CompatibilityEvaluateResponse,
    ContractIssue,
    ContractValidationResponse,
    ScenarioSelectionUpsert,
    TaskReliabilityOverview,
    TaskScenarioItem,
    TaskScenarioUpsert,
    TaskTestContractPayload,
    TaskTestContractResponse,
    TaskTestContractVersionResponse,
    TestCaseResponse,
    TestPlanApproveRequest,
    TestPlanCreate,
    TestPlanDetail,
    TestPlanGenerateResponse,
    TestPlanResponse,
    TestPlanRevisionResponse,
    TestPlanUpdate,
    TestPlanValidationResponse,
)
from app.services import (
    adapter_registry_service,
    checkpoint_service,
    compatibility_service,
    scenario_catalog_service,
    task_contract_service,
    task_test_configuration_service,
    test_plan_service,
)

router = APIRouter(tags=["reliability-planning"])

_APP_ONLY_NOTE = (
    "Planning only: approval does not execute tasks, launch workers, terminate "
    "processes or modify the target environment."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _application(db: Session, application_id: uuid.UUID) -> TargetApp:
    from app.services import discovery_service

    try:
        return discovery_service.get_target_app(db, application_id)
    except discovery_service.TargetAppNotFoundError as exc:
        raise HTTPException(status_code=404, detail="application not found") from exc


def _task(db: Session, target_app: TargetApp, task_id: uuid.UUID):
    try:
        return compatibility_service.get_task_in_application(db, target_app.id, task_id)
    except compatibility_service.TaskNotInApplicationError as exc:
        raise HTTPException(status_code=404, detail="registered task not found") from exc


def _checkpoint(db: Session, target_app: TargetApp, checkpoint_id: uuid.UUID):
    try:
        return checkpoint_service.get_checkpoint(
            db, checkpoint_id, target_app_id=target_app.id
        )
    except checkpoint_service.CheckpointNotFoundError as exc:
        raise HTTPException(status_code=404, detail="checkpoint not found") from exc


def _contract(db: Session, target_app: TargetApp, contract_id: uuid.UUID):
    try:
        return task_contract_service.get_contract(
            db, contract_id, target_app_id=target_app.id
        )
    except task_contract_service.ContractNotFoundError as exc:
        raise HTTPException(status_code=404, detail="contract not found") from exc


def _plan(db: Session, target_app: TargetApp, plan_id: uuid.UUID):
    try:
        return test_plan_service.get_plan(db, plan_id, target_app_id=target_app.id)
    except test_plan_service.TestPlanNotFoundError as exc:
        raise HTTPException(status_code=404, detail="test plan not found") from exc


def _plan_response(plan) -> TestPlanResponse:
    response = TestPlanResponse.model_validate(plan)
    response.ready_for_execution = test_plan_service.plan_ready_for_execution(plan)
    response.execution_available = False
    return response


def _validation_error(issues: list[dict[str, Any]]) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={"message": "configuration is not valid", "issues": issues},
    )


# ---------------------------------------------------------------------------
# Catalog (global, read-only)
# ---------------------------------------------------------------------------


@router.get("/scenarios", tags=["planning:catalog"])
def list_scenarios(
    category: str | None = None, trigger_type: str | None = None
) -> dict[str, Any]:
    return {
        **scenario_catalog_service.catalog_metadata(),
        "items": scenario_catalog_service.scenarios(
            category=category, trigger_type=trigger_type
        ),
    }


@router.get("/scenarios/{scenario_id}", tags=["planning:catalog"])
def get_scenario(scenario_id: str) -> dict[str, Any]:
    try:
        return scenario_catalog_service.scenario_detail(scenario_id)
    except scenario_catalog_service.ScenarioNotFoundError as exc:
        raise HTTPException(status_code=404, detail="scenario not found") from exc


@router.get("/adapter-types", tags=["planning:catalog"], response_model=list[AdapterTypeResponse])
def list_adapter_types(db: Session = Depends(get_db)):
    return scenario_catalog_service.adapter_types(db)


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------


@router.get(
    "/applications/{application_id}/adapter-types",
    tags=["planning:adapters"],
    response_model=list[AdapterTypeResponse],
)
def list_application_adapter_types(
    application_id: uuid.UUID, db: Session = Depends(get_db)
):
    target_app = _application(db, application_id)
    return scenario_catalog_service.adapter_types(db, target_app_id=target_app.id)


@router.post(
    "/applications/{application_id}/adapter-definitions",
    tags=["planning:adapters"],
    response_model=AdapterTypeResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_adapter_definition(
    application_id: uuid.UUID,
    payload: AdapterDefinitionCreate,
    db: Session = Depends(get_db),
):
    """Register custom adapter type metadata (no executable plugin is loaded)."""
    target_app = _application(db, application_id)
    try:
        row = adapter_registry_service.register_definition(db, target_app, payload)
    except adapter_registry_service.DuplicateAdapterTypeError as exc:
        raise HTTPException(
            status_code=409, detail=f"adapter type already exists: {exc}"
        ) from exc
    return {
        "slug": row.slug,
        "name": row.name,
        "category": row.category,
        "description": row.description or "",
        "capabilities": list(row.capabilities or []),
        "supported_triggers": list(row.supported_triggers or []),
        "version": row.version,
        "builtin": False,
    }


@router.get(
    "/applications/{application_id}/adapters",
    tags=["planning:adapters"],
    response_model=list[AdapterResponse],
)
def list_adapters(application_id: uuid.UUID, db: Session = Depends(get_db)):
    target_app = _application(db, application_id)
    return adapter_registry_service.list_adapters(db, target_app.id)


@router.post(
    "/applications/{application_id}/adapters",
    tags=["planning:adapters"],
    response_model=AdapterResponse,
    status_code=status.HTTP_201_CREATED,
)
def configure_adapter(
    application_id: uuid.UUID, payload: AdapterCreate, db: Session = Depends(get_db)
):
    target_app = _application(db, application_id)
    try:
        return adapter_registry_service.create_adapter(db, target_app, payload)
    except adapter_registry_service.AdapterTypeNotFoundError as exc:
        raise HTTPException(
            status_code=422, detail=f"unknown adapter type: {exc}"
        ) from exc
    except adapter_registry_service.InvalidAdapterConfigurationError as exc:
        raise _validation_error(
            [{"code": "INVALID_ADAPTER", "severity": "error", "message": i} for i in exc.issues]
        ) from exc
    except adapter_registry_service.DuplicateAdapterNameError as exc:
        raise HTTPException(
            status_code=409, detail=f"adapter name already exists: {exc}"
        ) from exc


@router.patch(
    "/applications/{application_id}/adapters/{adapter_id}",
    tags=["planning:adapters"],
    response_model=AdapterResponse,
)
def update_adapter(
    application_id: uuid.UUID,
    adapter_id: uuid.UUID,
    payload: AdapterUpdate,
    db: Session = Depends(get_db),
):
    target_app = _application(db, application_id)
    try:
        adapter = adapter_registry_service.get_adapter(
            db, adapter_id, target_app_id=target_app.id
        )
        return adapter_registry_service.update_adapter(db, adapter, payload)
    except adapter_registry_service.AdapterNotFoundError as exc:
        raise HTTPException(status_code=404, detail="adapter not found") from exc
    except adapter_registry_service.InvalidAdapterConfigurationError as exc:
        raise _validation_error(
            [{"code": "INVALID_ADAPTER", "severity": "error", "message": i} for i in exc.issues]
        ) from exc


@router.post(
    "/applications/{application_id}/adapters/{adapter_id}/validate",
    tags=["planning:adapters"],
    response_model=AdapterResponse,
)
def validate_adapter(
    application_id: uuid.UUID, adapter_id: uuid.UUID, db: Session = Depends(get_db)
):
    target_app = _application(db, application_id)
    try:
        adapter = adapter_registry_service.get_adapter(
            db, adapter_id, target_app_id=target_app.id
        )
    except adapter_registry_service.AdapterNotFoundError as exc:
        raise HTTPException(status_code=404, detail="adapter not found") from exc
    return adapter_registry_service.validate_adapter(db, adapter)


@router.delete(
    "/applications/{application_id}/adapters/{adapter_id}",
    tags=["planning:adapters"],
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_adapter(
    application_id: uuid.UUID, adapter_id: uuid.UUID, db: Session = Depends(get_db)
):
    target_app = _application(db, application_id)
    try:
        adapter = adapter_registry_service.get_adapter(
            db, adapter_id, target_app_id=target_app.id
        )
    except adapter_registry_service.AdapterNotFoundError as exc:
        raise HTTPException(status_code=404, detail="adapter not found") from exc
    adapter_registry_service.delete_adapter(db, adapter)
    return None


# ---------------------------------------------------------------------------
# Task test contracts
# ---------------------------------------------------------------------------


@router.get(
    "/applications/{application_id}/contracts",
    tags=["planning:contracts"],
    response_model=list[TaskTestContractResponse],
)
def list_contracts(application_id: uuid.UUID, db: Session = Depends(get_db)):
    target_app = _application(db, application_id)
    return task_contract_service.list_contracts(db, target_app.id)


@router.post(
    "/applications/{application_id}/registered-tasks/{task_id}/contract",
    tags=["planning:contracts"],
    response_model=TaskTestContractResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_contract(
    application_id: uuid.UUID,
    task_id: uuid.UUID,
    payload: TaskTestContractPayload,
    db: Session = Depends(get_db),
):
    target_app = _application(db, application_id)
    task = _task(db, target_app, task_id)
    try:
        return task_contract_service.create_contract(db, target_app, task, payload)
    except task_contract_service.ContractAlreadyExistsError as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "this task already has a contract; PATCH it to create a new version"
            ),
        ) from exc
    except task_contract_service.ContractValidationError as exc:
        raise _validation_error(exc.issues) from exc


@router.get(
    "/applications/{application_id}/registered-tasks/{task_id}/contract",
    tags=["planning:contracts"],
    response_model=TaskTestContractResponse,
)
def get_contract_for_task(
    application_id: uuid.UUID, task_id: uuid.UUID, db: Session = Depends(get_db)
):
    target_app = _application(db, application_id)
    task = _task(db, target_app, task_id)
    contract = task_contract_service.get_contract_for_task(db, task.id)
    if contract is None:
        raise HTTPException(status_code=404, detail="contract not found")
    return contract


@router.get(
    "/applications/{application_id}/contracts/{contract_id}",
    tags=["planning:contracts"],
    response_model=TaskTestContractResponse,
)
def get_contract(
    application_id: uuid.UUID, contract_id: uuid.UUID, db: Session = Depends(get_db)
):
    target_app = _application(db, application_id)
    return _contract(db, target_app, contract_id)


@router.patch(
    "/applications/{application_id}/contracts/{contract_id}",
    tags=["planning:contracts"],
    response_model=TaskTestContractResponse,
)
def update_contract(
    application_id: uuid.UUID,
    contract_id: uuid.UUID,
    payload: TaskTestContractPayload,
    db: Session = Depends(get_db),
):
    target_app = _application(db, application_id)
    contract = _contract(db, target_app, contract_id)
    try:
        return task_contract_service.update_contract(db, contract, payload)
    except task_contract_service.ContractValidationError as exc:
        raise _validation_error(exc.issues) from exc


@router.post(
    "/applications/{application_id}/contracts/{contract_id}/validate",
    tags=["planning:contracts"],
    response_model=ContractValidationResponse,
)
def validate_contract(
    application_id: uuid.UUID, contract_id: uuid.UUID, db: Session = Depends(get_db)
):
    target_app = _application(db, application_id)
    contract = _contract(db, target_app, contract_id)
    validation = task_contract_service.revalidate_contract(db, contract)
    return ContractValidationResponse(
        valid=validation["valid"],
        issues=[ContractIssue(**issue) for issue in validation["issues"]],
    )


@router.get(
    "/applications/{application_id}/contracts/{contract_id}/versions",
    tags=["planning:contracts"],
    response_model=list[TaskTestContractVersionResponse],
)
def list_contract_versions(
    application_id: uuid.UUID, contract_id: uuid.UUID, db: Session = Depends(get_db)
):
    target_app = _application(db, application_id)
    contract = _contract(db, target_app, contract_id)
    return task_contract_service.list_versions(db, contract)


# ---------------------------------------------------------------------------
# Checkpoints and selection configuration
# ---------------------------------------------------------------------------


@router.get(
    "/applications/{application_id}/checkpoints",
    tags=["planning:checkpoints"],
    response_model=list[CheckpointResponse],
)
def list_checkpoints(
    application_id: uuid.UUID,
    task_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
):
    target_app = _application(db, application_id)
    if task_id is not None:
        _task(db, target_app, task_id)
    return checkpoint_service.list_checkpoints(
        db, target_app_id=target_app.id, task_id=task_id
    )


@router.get(
    "/applications/{application_id}/checkpoints/{checkpoint_id}",
    tags=["planning:checkpoints"],
    response_model=CheckpointWithScenarios,
)
def get_checkpoint(
    application_id: uuid.UUID, checkpoint_id: uuid.UUID, db: Session = Depends(get_db)
):
    target_app = _application(db, application_id)
    checkpoint = _checkpoint(db, target_app, checkpoint_id)
    task = _task(db, target_app, checkpoint.registered_task_id)
    selections = checkpoint_service.list_selections(db, checkpoint)
    adapters = compatibility_service.adapter_views(db, target_app.id)
    contract = task_contract_service.get_contract_for_task(db, task.id)

    scenarios: list[CheckpointScenarioItem] = []
    for scenario in scenario_catalog_service.scenarios():
        definition = compatibility_service.resolve_scenario(scenario["id"])
        if not definition.supports_checkpoint:
            continue
        result = compatibility_service.evaluate_task_scenario(
            db,
            task,
            definition,
            trigger_type="checkpoint",
            checkpoint=checkpoint,
            contract=contract,
            adapters=adapters,
        )
        stored = selections.get(definition.id)
        scenarios.append(
            CheckpointScenarioItem(
                scenario_id=definition.id,
                scenario_version=definition.version,
                name=definition.name,
                category=definition.category,
                enabled=bool(stored.enabled) if stored is not None else False,
                config=stored.config if stored is not None else None,
                assertion_overrides=(
                    list(stored.assertion_overrides or []) if stored is not None else None
                ),
                compatibility=result.to_dict(),
            )
        )
    return CheckpointWithScenarios(
        **CheckpointResponse.model_validate(checkpoint).model_dump(),
        scenarios=scenarios,
    )


@router.patch(
    "/applications/{application_id}/checkpoints/{checkpoint_id}",
    tags=["planning:checkpoints"],
    response_model=CheckpointResponse,
)
def update_checkpoint_reliability(
    application_id: uuid.UUID,
    checkpoint_id: uuid.UUID,
    payload: CheckpointReliabilityUpdate,
    db: Session = Depends(get_db),
):
    target_app = _application(db, application_id)
    checkpoint = _checkpoint(db, target_app, checkpoint_id)
    return checkpoint_service.set_reliability(
        db, checkpoint, reliability_enabled=payload.reliability_enabled
    )


@router.put(
    "/applications/{application_id}/checkpoints/{checkpoint_id}/scenarios/{scenario_id}",
    tags=["planning:checkpoints"],
    response_model=CheckpointScenarioItem,
)
def select_checkpoint_scenario(
    application_id: uuid.UUID,
    checkpoint_id: uuid.UUID,
    scenario_id: str,
    payload: ScenarioSelectionUpsert,
    db: Session = Depends(get_db),
):
    target_app = _application(db, application_id)
    checkpoint = _checkpoint(db, target_app, checkpoint_id)
    task = _task(db, target_app, checkpoint.registered_task_id)
    try:
        scenario = compatibility_service.resolve_scenario(scenario_id)
    except compatibility_service.ScenarioNotFoundError as exc:
        raise HTTPException(status_code=404, detail="scenario not found") from exc
    try:
        selection = checkpoint_service.upsert_selection(
            db, checkpoint, scenario_id, payload
        )
    except checkpoint_service.InvalidCheckpointConfigurationError as exc:
        raise _validation_error(
            [
                {"code": "INVALID_CHECKPOINT_SCENARIO", "severity": "error", "message": i}
                for i in exc.issues
            ]
        ) from exc

    result = compatibility_service.evaluate_task_scenario(
        db,
        task,
        scenario,
        trigger_type="checkpoint",
        checkpoint=checkpoint,
    )
    return CheckpointScenarioItem(
        scenario_id=scenario.id,
        scenario_version=scenario.version,
        name=scenario.name,
        category=scenario.category,
        enabled=selection.enabled,
        config=selection.config,
        assertion_overrides=list(selection.assertion_overrides or []) or None,
        compatibility=result.to_dict(),
    )


@router.get(
    "/applications/{application_id}/checkpoints/{checkpoint_id}/scenarios",
    tags=["planning:checkpoints"],
    response_model=list[CheckpointScenarioItem],
)
def list_checkpoint_scenarios(
    application_id: uuid.UUID, checkpoint_id: uuid.UUID, db: Session = Depends(get_db)
):
    return get_checkpoint(application_id, checkpoint_id, db).scenarios


@router.get(
    "/applications/{application_id}/registered-tasks/{task_id}/scenarios",
    tags=["planning:checkpoints"],
    response_model=list[TaskScenarioItem],
)
def list_task_scenarios(
    application_id: uuid.UUID, task_id: uuid.UUID, db: Session = Depends(get_db)
):
    target_app = _application(db, application_id)
    task = _task(db, target_app, task_id)
    automatic, _checkpoints = compatibility_service.task_overview(db, task)
    return automatic


@router.put(
    "/applications/{application_id}/registered-tasks/{task_id}/scenarios/{scenario_id}",
    tags=["planning:checkpoints"],
    response_model=TaskScenarioItem,
)
def select_task_scenario(
    application_id: uuid.UUID,
    task_id: uuid.UUID,
    scenario_id: str,
    payload: TaskScenarioUpsert,
    db: Session = Depends(get_db),
):
    target_app = _application(db, application_id)
    task = _task(db, target_app, task_id)
    try:
        scenario = compatibility_service.resolve_scenario(scenario_id)
    except compatibility_service.ScenarioNotFoundError as exc:
        raise HTTPException(status_code=404, detail="scenario not found") from exc
    try:
        selection = task_test_configuration_service.upsert_selection(
            db, task, scenario, enabled=payload.enabled, config=payload.config
        )
    except task_test_configuration_service.InvalidTaskScenarioConfigurationError as exc:
        raise _validation_error(
            [
                {"code": "INVALID_TASK_SCENARIO", "severity": "error", "message": i}
                for i in exc.issues
            ]
        ) from exc

    result = compatibility_service.evaluate_task_scenario(
        db, task, scenario, trigger_type="automatic"
    )
    return TaskScenarioItem(
        scenario_id=scenario.id,
        scenario_version=scenario.version,
        name=scenario.name,
        category=scenario.category,
        description=scenario.description,
        default_trigger_type=scenario.default_trigger_type,
        supported_status=scenario.supported_status,
        implementation_status=scenario.implementation_status,
        enabled=selection.enabled,
        selected_by_default=result.compatible,
        config=selection.config,
        compatibility=result.to_dict(),
    )


@router.get(
    "/applications/{application_id}/registered-tasks/{task_id}/reliability",
    tags=["planning:checkpoints"],
    response_model=TaskReliabilityOverview,
)
def get_task_reliability(
    application_id: uuid.UUID, task_id: uuid.UUID, db: Session = Depends(get_db)
):
    target_app = _application(db, application_id)
    task = _task(db, target_app, task_id)
    automatic, checkpoints = compatibility_service.task_overview(db, task)
    contract = task_contract_service.get_contract_for_task(db, task.id)
    return TaskReliabilityOverview(
        registered_task=RegisteredTaskResponse.model_validate(task).model_dump(mode="json"),
        automatic_scenarios=automatic,
        checkpoints=checkpoints,
        contract=(
            TaskTestContractResponse.model_validate(contract) if contract is not None else None
        ),
        contract_issues=[
            ContractIssue(**issue)
            for issue in ((contract.validation or {}).get("issues", []) if contract else [])
        ],
    )


# ---------------------------------------------------------------------------
# Compatibility
# ---------------------------------------------------------------------------


@router.post(
    "/applications/{application_id}/compatibility/evaluate",
    tags=["planning:compatibility"],
    response_model=CompatibilityEvaluateResponse,
)
def evaluate_compatibility(
    application_id: uuid.UUID,
    payload: CompatibilityEvaluateRequest,
    db: Session = Depends(get_db),
):
    target_app = _application(db, application_id)
    try:
        results = compatibility_service.evaluate_selections(
            db, target_app, payload.selections
        )
    except compatibility_service.ScenarioNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"scenario not found: {exc}") from exc
    except compatibility_service.TaskNotInApplicationError as exc:
        raise HTTPException(status_code=404, detail="registered task not found") from exc
    except checkpoint_service.CheckpointNotFoundError as exc:
        raise HTTPException(status_code=404, detail="checkpoint not found") from exc
    return {"results": results}


# ---------------------------------------------------------------------------
# Test plans
# ---------------------------------------------------------------------------


@router.post(
    "/applications/{application_id}/test-plans",
    tags=["planning:test-plans"],
    response_model=TestPlanResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_test_plan(
    application_id: uuid.UUID, payload: TestPlanCreate, db: Session = Depends(get_db)
):
    target_app = _application(db, application_id)
    try:
        plan = test_plan_service.create_plan(db, target_app, payload)
    except test_plan_service.TaskNotInApplicationError as exc:
        raise HTTPException(status_code=404, detail="registered task not found") from exc
    return _plan_response(plan)


@router.get(
    "/applications/{application_id}/test-plans",
    tags=["planning:test-plans"],
    response_model=list[TestPlanResponse],
)
def list_test_plans(application_id: uuid.UUID, db: Session = Depends(get_db)):
    target_app = _application(db, application_id)
    return [_plan_response(plan) for plan in test_plan_service.list_plans(db, target_app.id)]


@router.get(
    "/applications/{application_id}/test-plans/{plan_id}",
    tags=["planning:test-plans"],
    response_model=TestPlanDetail,
)
def get_test_plan(
    application_id: uuid.UUID, plan_id: uuid.UUID, db: Session = Depends(get_db)
):
    target_app = _application(db, application_id)
    plan = _plan(db, target_app, plan_id)
    revision = test_plan_service.latest_revision(db, plan)
    detail = TestPlanDetail(**_plan_response(plan).model_dump())
    detail.latest_revision = (
        TestPlanRevisionResponse.model_validate(revision) if revision is not None else None
    )
    detail.duplicates = list((revision.summary or {}).get("duplicates", [])) if revision else []
    return detail


@router.patch(
    "/applications/{application_id}/test-plans/{plan_id}",
    tags=["planning:test-plans"],
    response_model=TestPlanResponse,
)
def update_test_plan(
    application_id: uuid.UUID,
    plan_id: uuid.UUID,
    payload: TestPlanUpdate,
    db: Session = Depends(get_db),
):
    target_app = _application(db, application_id)
    plan = _plan(db, target_app, plan_id)
    try:
        return _plan_response(test_plan_service.update_plan(db, plan, payload))
    except test_plan_service.TaskNotInApplicationError as exc:
        raise HTTPException(status_code=404, detail="registered task not found") from exc


@router.post(
    "/applications/{application_id}/test-plans/{plan_id}/generate",
    tags=["planning:test-plans"],
    response_model=TestPlanGenerateResponse,
)
def generate_test_plan(
    application_id: uuid.UUID, plan_id: uuid.UUID, db: Session = Depends(get_db)
):
    target_app = _application(db, application_id)
    plan = _plan(db, target_app, plan_id)
    try:
        plan, revision, summary, duplicates = test_plan_service.generate(db, plan)
    except test_plan_service.TaskNotInApplicationError as exc:
        raise HTTPException(status_code=404, detail="registered task not found") from exc
    return TestPlanGenerateResponse(
        plan=_plan_response(plan),
        revision=TestPlanRevisionResponse.model_validate(revision),
        summary=summary,
        duplicates=duplicates,
    )


@router.post(
    "/applications/{application_id}/test-plans/{plan_id}/validate",
    tags=["planning:test-plans"],
    response_model=TestPlanValidationResponse,
)
def validate_test_plan(
    application_id: uuid.UUID, plan_id: uuid.UUID, db: Session = Depends(get_db)
):
    target_app = _application(db, application_id)
    plan = _plan(db, target_app, plan_id)
    try:
        report = test_plan_service.validate(db, plan)
    except test_plan_service.InvalidPlanStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return TestPlanValidationResponse(
        plan=_plan_response(plan),
        revision=plan.current_revision,
        **report,
    )


@router.post(
    "/applications/{application_id}/test-plans/{plan_id}/submit",
    tags=["planning:test-plans"],
    response_model=TestPlanResponse,
)
def submit_test_plan(
    application_id: uuid.UUID, plan_id: uuid.UUID, db: Session = Depends(get_db)
):
    target_app = _application(db, application_id)
    plan = _plan(db, target_app, plan_id)
    try:
        return _plan_response(test_plan_service.submit(db, plan))
    except test_plan_service.InvalidPlanStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/applications/{application_id}/test-plans/{plan_id}/approve",
    tags=["planning:test-plans"],
    response_model=TestPlanResponse,
)
def approve_test_plan(
    application_id: uuid.UUID,
    plan_id: uuid.UUID,
    payload: TestPlanApproveRequest,
    db: Session = Depends(get_db),
):
    target_app = _application(db, application_id)
    plan = _plan(db, target_app, plan_id)
    try:
        plan = test_plan_service.approve(db, plan, payload.revision)
    except test_plan_service.RevisionMismatchError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except test_plan_service.InvalidPlanStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    response = _plan_response(plan)
    return response


@router.post(
    "/applications/{application_id}/test-plans/{plan_id}/revoke",
    tags=["planning:test-plans"],
    response_model=TestPlanResponse,
)
def revoke_test_plan(
    application_id: uuid.UUID, plan_id: uuid.UUID, db: Session = Depends(get_db)
):
    target_app = _application(db, application_id)
    plan = _plan(db, target_app, plan_id)
    try:
        return _plan_response(test_plan_service.revoke(db, plan))
    except test_plan_service.InvalidPlanStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get(
    "/applications/{application_id}/test-plans/{plan_id}/revisions/{revision}",
    tags=["planning:test-plans"],
    response_model=TestPlanRevisionResponse,
)
def get_plan_revision(
    application_id: uuid.UUID,
    plan_id: uuid.UUID,
    revision: int,
    db: Session = Depends(get_db),
):
    target_app = _application(db, application_id)
    plan = _plan(db, target_app, plan_id)
    try:
        return test_plan_service.get_revision(db, plan, revision)
    except test_plan_service.TestPlanNotFoundError as exc:
        raise HTTPException(status_code=404, detail="plan revision not found") from exc


@router.get(
    "/applications/{application_id}/test-plans/{plan_id}/revisions/{revision}/test-cases",
    tags=["planning:test-plans"],
    response_model=list[TestCaseResponse],
)
def list_plan_test_cases(
    application_id: uuid.UUID,
    plan_id: uuid.UUID,
    revision: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    target_app = _application(db, application_id)
    plan = _plan(db, target_app, plan_id)
    try:
        row = test_plan_service.get_revision(db, plan, revision)
    except test_plan_service.TestPlanNotFoundError as exc:
        raise HTTPException(status_code=404, detail="plan revision not found") from exc
    cases = test_plan_service.list_cases(db, row)
    return cases[skip : skip + limit]
