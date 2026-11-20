"""Task Test Contract lifecycle.

A contract describes how one registered task may be safely tested and how its
business effect is judged. It is separate from the adapter registry: the
contract declares what the task needs, adapters supply reusable capabilities.

Saving a contract never executes the task.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import ApplicationAdapter, RegisteredTask, TargetApp, TaskTestContract
from app.models.planning import TaskTestContractVersion
from app.schemas.planning import TaskTestContractPayload


class ContractNotFoundError(Exception):
    pass


class ContractAlreadyExistsError(Exception):
    pass


class ContractValidationError(Exception):
    def __init__(self, issues: list[dict[str, Any]]):
        super().__init__("contract is not internally valid")
        self.issues = issues


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _issue(code: str, severity: str, message: str, field: str | None = None) -> dict:
    payload: dict[str, Any] = {"code": code, "severity": severity, "message": message}
    if field is not None:
        payload["field"] = field
    return payload


def _app_adapters(db: Session, target_app_id: uuid.UUID) -> dict[str, ApplicationAdapter]:
    rows = db.scalars(
        select(ApplicationAdapter).where(ApplicationAdapter.target_app_id == target_app_id)
    ).all()
    return {str(row.id): row for row in rows}


def validate_payload(
    db: Session, target_app_id: uuid.UUID, payload: dict[str, Any]
) -> list[dict[str, Any]]:
    """Semantic validation against this application's configured adapters.

    Deterministic: issues are returned in a fixed order (measurements, cleanup,
    assertions, contract completeness).
    """
    adapters = _app_adapters(db, target_app_id)
    issues: list[dict[str, Any]] = []

    for measurement in payload.get("effect_measurements") or []:
        adapter = adapters.get(str(measurement.get("adapter_id")))
        if adapter is None:
            issues.append(
                _issue(
                    "MEASUREMENT_ADAPTER_NOT_CONFIGURED",
                    "error",
                    (
                        f"Measurement '{measurement.get('id')}' references an adapter that "
                        "is not configured for this application."
                    ),
                    f"effect_measurements.{measurement.get('id')}.adapter_id",
                )
            )
            continue
        if "effect_measurement" not in (adapter.capabilities or []):
            issues.append(
                _issue(
                    "MEASUREMENT_CAPABILITY_MISSING",
                    "error",
                    (
                        f"Adapter '{adapter.name}' does not declare the "
                        "effect_measurement capability."
                    ),
                    f"effect_measurements.{measurement.get('id')}.adapter_id",
                )
            )
        elif adapter.status != "VALIDATED":
            issues.append(
                _issue(
                    "MEASUREMENT_ADAPTER_NOT_VALIDATED",
                    "warning",
                    (
                        f"Adapter '{adapter.name}' is not validated yet; the "
                        "combination will need configuration."
                    ),
                    f"effect_measurements.{measurement.get('id')}.adapter_id",
                )
            )

    cleanup = payload.get("cleanup") or {}
    if cleanup.get("mode") == "adapter_managed":
        adapter = adapters.get(str(cleanup.get("adapter_id")))
        if adapter is None:
            issues.append(
                _issue(
                    "CLEANUP_ADAPTER_NOT_CONFIGURED",
                    "error",
                    "Cleanup references an adapter that is not configured for this application.",
                    "cleanup.adapter_id",
                )
            )
        elif "resource_cleanup" not in (adapter.capabilities or []):
            issues.append(
                _issue(
                    "CLEANUP_CAPABILITY_MISSING",
                    "error",
                    f"Adapter '{adapter.name}' does not declare resource_cleanup.",
                    "cleanup.adapter_id",
                )
            )
        if cleanup.get("resource_scope") != "test_owned":
            issues.append(
                _issue(
                    "CLEANUP_SCOPE_INVALID",
                    "error",
                    "Cleanup must be scoped to test-owned resources.",
                    "cleanup.resource_scope",
                )
            )

    if not payload.get("assertions"):
        issues.append(
            _issue(
                "ASSERTIONS_MISSING",
                "warning",
                (
                    "No assertions are declared; scenarios that require measurable "
                    "outcomes will report NEEDS_CONFIGURATION."
                ),
                "assertions",
            )
        )
    if not payload.get("effect_measurements"):
        issues.append(
            _issue(
                "EFFECT_MEASUREMENTS_MISSING",
                "warning",
                (
                    "No effect measurement is declared; outcome will rest on "
                    "assertions only."
                ),
                "effect_measurements",
            )
        )
    if not (payload.get("safe_input") or payload.get("input_fixture_ref")):
        issues.append(
            _issue(
                "SAFE_INPUT_MISSING",
                "warning",
                "No safe test input or fixture reference is declared.",
                "safe_input",
            )
        )
    if cleanup.get("mode", "none") == "none":
        issues.append(
            _issue(
                "CLEANUP_NOT_CONFIGURED",
                "warning",
                "No cleanup is configured; test-owned resources may be left behind.",
                "cleanup",
            )
        )
    return issues


def _validation_document(issues: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "valid": not any(issue["severity"] == "error" for issue in issues),
        "issues": issues,
    }


def get_contract_for_task(
    db: Session, registered_task_id: uuid.UUID
) -> TaskTestContract | None:
    return db.scalar(
        select(TaskTestContract).where(
            TaskTestContract.registered_task_id == registered_task_id
        )
    )


def get_contract(
    db: Session, contract_id: uuid.UUID, *, target_app_id: uuid.UUID
) -> TaskTestContract:
    contract = db.get(TaskTestContract, contract_id)
    if contract is None or contract.target_app_id != target_app_id:
        raise ContractNotFoundError(str(contract_id))
    return contract


def list_contracts(db: Session, target_app_id: uuid.UUID) -> list[TaskTestContract]:
    return list(
        db.scalars(
            select(TaskTestContract)
            .where(TaskTestContract.target_app_id == target_app_id)
            .order_by(TaskTestContract.created_at)
        ).all()
    )


def _store_version(
    db: Session,
    contract: TaskTestContract,
    payload: dict[str, Any],
    validation: dict[str, Any],
) -> None:
    contract.payload = payload
    contract.validation = validation
    contract.last_validated_at = _now()
    db.add(
        TaskTestContractVersion(
            contract_id=contract.id,
            version=contract.version,
            payload=payload,
            validation=validation,
        )
    )


def create_contract(
    db: Session,
    target_app: TargetApp,
    registered_task: RegisteredTask,
    payload_model: TaskTestContractPayload,
) -> TaskTestContract:
    if get_contract_for_task(db, registered_task.id) is not None:
        raise ContractAlreadyExistsError(str(registered_task.id))

    payload = payload_model.model_dump(mode="json")
    issues = validate_payload(db, target_app.id, payload)
    if any(issue["severity"] == "error" for issue in issues):
        raise ContractValidationError(issues)

    contract = TaskTestContract(
        target_app_id=target_app.id,
        registered_task_id=registered_task.id,
        version=1,
        payload=payload,
    )
    db.add(contract)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ContractAlreadyExistsError(str(registered_task.id)) from exc
    _store_version(db, contract, payload, _validation_document(issues))
    db.commit()
    db.refresh(contract)
    return contract


def update_contract(
    db: Session,
    contract: TaskTestContract,
    payload_model: TaskTestContractPayload,
) -> TaskTestContract:
    """Replace the contract, appending an immutable version.

    Existing plans keep referencing the version they were generated from.
    """
    payload = payload_model.model_dump(mode="json")
    issues = validate_payload(db, contract.target_app_id, payload)
    if any(issue["severity"] == "error" for issue in issues):
        raise ContractValidationError(issues)

    contract.version = int(contract.version) + 1
    _store_version(db, contract, payload, _validation_document(issues))
    db.commit()
    db.refresh(contract)
    return contract


def revalidate_contract(db: Session, contract: TaskTestContract) -> dict[str, Any]:
    issues = validate_payload(db, contract.target_app_id, contract.payload)
    validation = _validation_document(issues)
    contract.validation = validation
    contract.last_validated_at = _now()
    db.commit()
    db.refresh(contract)
    return validation


def list_versions(db: Session, contract: TaskTestContract) -> list[TaskTestContractVersion]:
    return list(
        db.scalars(
            select(TaskTestContractVersion)
            .where(TaskTestContractVersion.contract_id == contract.id)
            .order_by(TaskTestContractVersion.version)
        ).all()
    )
