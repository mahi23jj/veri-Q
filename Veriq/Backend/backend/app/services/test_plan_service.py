"""Test plan lifecycle: generate, validate, review, approve, revoke.

Approval authorises a plan revision for *future* execution. Nothing here
launches a worker, injects a failure or touches the target application.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    RegisteredTask,
    TargetApp,
    TestPlan,
    TestPlanRevision,
    TestPlanTestCase,
)
from app.schemas.planning import TestPlanCreate, TestPlanUpdate
from app.services import scenario_matrix_service


class TestPlanNotFoundError(Exception):
    pass


class TaskNotInApplicationError(Exception):
    pass


class InvalidPlanStateError(Exception):
    """The requested transition is not allowed from the plan's current state."""


class RevisionMismatchError(Exception):
    """Approval did not reference the current plan revision."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _resolve_tasks(
    db: Session, target_app_id: uuid.UUID, task_ids: Sequence[uuid.UUID]
) -> list[RegisteredTask]:
    unique_ids = list(dict.fromkeys(task_ids))
    rows = db.scalars(select(RegisteredTask).where(RegisteredTask.id.in_(unique_ids))).all()
    by_id = {row.id: row for row in rows}
    tasks: list[RegisteredTask] = []
    for task_id in unique_ids:
        task = by_id.get(task_id)
        if task is None or task.target_app_id != target_app_id:
            raise TaskNotInApplicationError(str(task_id))
        tasks.append(task)
    return tasks


def create_plan(
    db: Session, target_app: TargetApp, payload: TestPlanCreate
) -> TestPlan:
    _resolve_tasks(db, target_app.id, payload.task_ids)
    plan = TestPlan(
        target_app_id=target_app.id,
        name=payload.name,
        description=payload.description,
        status="DRAFT",
        task_ids=[str(task_id) for task_id in dict.fromkeys(payload.task_ids)],
        current_revision=0,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


def list_plans(db: Session, target_app_id: uuid.UUID) -> list[TestPlan]:
    return list(
        db.scalars(
            select(TestPlan)
            .where(TestPlan.target_app_id == target_app_id)
            .order_by(TestPlan.created_at.desc())
        ).all()
    )


def get_plan(db: Session, plan_id: uuid.UUID, *, target_app_id: uuid.UUID) -> TestPlan:
    plan = db.get(TestPlan, plan_id)
    if plan is None or plan.target_app_id != target_app_id:
        raise TestPlanNotFoundError(str(plan_id))
    return plan


def latest_revision(db: Session, plan: TestPlan) -> TestPlanRevision | None:
    if plan.current_revision <= 0:
        return None
    return db.scalar(
        select(TestPlanRevision).where(
            TestPlanRevision.test_plan_id == plan.id,
            TestPlanRevision.revision == plan.current_revision,
        )
    )


def get_revision(db: Session, plan: TestPlan, revision: int) -> TestPlanRevision:
    row = db.scalar(
        select(TestPlanRevision).where(
            TestPlanRevision.test_plan_id == plan.id,
            TestPlanRevision.revision == revision,
        )
    )
    if row is None:
        raise TestPlanNotFoundError(f"revision {revision}")
    return row


def list_cases(db: Session, revision: TestPlanRevision) -> list[TestPlanTestCase]:
    return list(
        db.scalars(
            select(TestPlanTestCase)
            .where(TestPlanTestCase.test_plan_revision_id == revision.id)
            .order_by(TestPlanTestCase.task_name, TestPlanTestCase.scenario_id)
        ).all()
    )


def _invalidate_approval(db: Session, plan: TestPlan) -> None:
    plan.approved_revision = None
    plan.approved_at = None
    current = latest_revision(db, plan)
    if current is not None and current.approved_at is not None:
        current.invalidated_at = _now()


def update_plan(db: Session, plan: TestPlan, payload: TestPlanUpdate) -> TestPlan:
    changes = payload.model_dump(exclude_unset=True)
    if "task_ids" in changes and changes["task_ids"] is not None:
        _resolve_tasks(db, plan.target_app_id, changes["task_ids"])
        plan.task_ids = [str(task_id) for task_id in dict.fromkeys(changes["task_ids"])]
    if "name" in changes and changes["name"] is not None:
        plan.name = changes["name"]
    if "description" in changes:
        plan.description = changes["description"]

    # Any change after approval requires review again, and the matrix must be
    # regenerated because it was produced from the previous configuration.
    if plan.approved_revision is not None:
        _invalidate_approval(db, plan)
        plan.status = "DRAFT"
    db.commit()
    db.refresh(plan)
    return plan


def generate(db: Session, plan: TestPlan) -> tuple[TestPlan, TestPlanRevision, dict, list]:
    """Generate the next immutable revision of the matrix."""
    task_ids = [uuid.UUID(str(task_id)) for task_id in plan.task_ids]
    _resolve_tasks(db, plan.target_app_id, task_ids)

    target_app = db.get(TargetApp, plan.target_app_id)
    if target_app is None:  # pragma: no cover - FK guarantees this
        raise TestPlanNotFoundError(str(plan.id))

    matrix, snapshot = scenario_matrix_service.build_matrix(db, target_app, task_ids)

    previous = latest_revision(db, plan)
    if previous is not None and plan.approved_revision is not None:
        previous.invalidated_at = _now()

    revision_number = int(plan.current_revision) + 1
    revision = TestPlanRevision(
        test_plan_id=plan.id,
        revision=revision_number,
        status=(
            "NEEDS_CHANGES"
            if matrix.blocked_count or not matrix.rows
            else "VALIDATING"
        ),
        snapshot=snapshot,
        summary={**matrix.summary, "duplicates": list(matrix.duplicates)},
    )
    db.add(revision)
    db.flush()

    for row in matrix.rows:
        payload = row.to_dict()
        db.add(
            TestPlanTestCase(
                test_plan_revision_id=revision.id,
                case_key=row.case_key,
                status=row.status,
                target_app_id=plan.target_app_id,
                registered_task_id=uuid.UUID(payload["registered_task_id"]),
                task_name=payload["task_name"],
                scenario_id=payload["scenario_id"],
                scenario_version=payload["scenario_version"],
                trigger_type=payload["trigger_type"],
                checkpoint_id=(
                    uuid.UUID(payload["checkpoint_id"])
                    if payload["checkpoint_id"] is not None
                    else None
                ),
                checkpoint_name=payload["checkpoint_name"],
                contract_id=(
                    uuid.UUID(payload["contract_id"])
                    if payload["contract_id"] is not None
                    else None
                ),
                contract_version=payload["contract_version"],
                adapter_refs=payload["adapter_refs"],
                test_input=payload["test_input"] or None,
                input_fixture_ref=payload["input_fixture_ref"],
                assertions=payload["assertions"],
                cleanup=payload["cleanup"] or None,
                scenario_config=payload["scenario_config"] or None,
                recovery_policy=payload.get("recovery_policy") or None,
                compatibility=payload["compatibility"],
                configuration_fingerprint=payload["configuration_fingerprint"],
            )
        )

    plan.current_revision = revision_number
    plan.status = revision.status
    plan.approved_revision = None
    plan.approved_at = None
    db.commit()
    db.refresh(plan)
    db.refresh(revision)
    return plan, revision, matrix.summary, list(matrix.duplicates)


def validate(db: Session, plan: TestPlan) -> dict[str, Any]:
    """Re-check the current revision against the current configuration.

    Reports drift (configuration changed since generation) and blocked cases.
    It never creates a revision and never approves anything.
    """
    revision = latest_revision(db, plan)
    if revision is None:
        raise InvalidPlanStateError("generate a matrix before validating the plan")

    task_ids = [uuid.UUID(str(task_id)) for task_id in plan.task_ids]
    target_app = db.get(TargetApp, plan.target_app_id)
    if target_app is None:  # pragma: no cover
        raise TestPlanNotFoundError(str(plan.id))
    matrix, _snapshot = scenario_matrix_service.build_matrix(db, target_app, task_ids)

    stored_cases = list_cases(db, revision)
    stored_by_key = {case.case_key: case for case in stored_cases}
    current_by_key = {row.case_key: row for row in matrix.rows}

    drift: list[dict[str, Any]] = []
    for case_key, case in stored_by_key.items():
        if case_key not in current_by_key:
            drift.append(
                {
                    "case_key": case_key,
                    "kind": "changed_or_removed",
                    "task_name": case.task_name,
                    "scenario_id": case.scenario_id,
                    "checkpoint_name": case.checkpoint_name,
                    "message": (
                        "The stored configuration no longer produces this case; "
                        "generate a new revision."
                    ),
                }
            )
    for case_key, row in current_by_key.items():
        if case_key not in stored_by_key:
            drift.append(
                {
                    "case_key": case_key,
                    "kind": "new_case",
                    "task_name": row.combination.task_name,
                    "scenario_id": row.combination.scenario_id,
                    "checkpoint_name": row.combination.checkpoint_name,
                    "message": "Current configuration produces an additional case.",
                }
            )

    blocking_issues: list[dict[str, Any]] = []
    for row in matrix.rows:
        if row.status == "BLOCKED":
            blocking_issues.append(
                {
                    "case_key": row.case_key,
                    "task_name": row.combination.task_name,
                    "scenario_id": row.combination.scenario_id,
                    "checkpoint_name": row.combination.checkpoint_name,
                    "status": row.combination.compatibility.status,
                    "reasons": [
                        reason
                        for reason in row.combination.compatibility.to_dict()["reasons"]
                        if reason["severity"] in ("configuration", "unsupported")
                    ],
                }
            )
    if not stored_cases:
        blocking_issues.append(
            {
                "code": "NO_TEST_CASES",
                "message": (
                    "The plan produced no test cases. Enable scenarios or add a "
                    "compatible task test contract."
                ),
            }
        )

    warnings: dict[str, dict[str, Any]] = {}
    for row in matrix.rows:
        for warning in row.combination.compatibility.warnings:
            warnings.setdefault(warning.code, warning.to_dict())

    ok = not drift and not blocking_issues
    plan.status = "VALIDATING" if ok else "NEEDS_CHANGES"
    if not ok:
        # Configuration moved away from the approved snapshot: the approval no
        # longer describes this plan and requires review again.
        _invalidate_approval(db, plan)
    revision.status = plan.status
    revision.summary = {**(revision.summary or {}), "last_validated_at": _now().isoformat()}
    db.commit()
    db.refresh(plan)

    return {
        "ok": ok,
        "blocking_issues": blocking_issues,
        "drift": drift,
        "warnings": list(warnings.values()),
        "total_cases": len(stored_cases),
        "ready_cases": sum(1 for case in stored_cases if case.status == "READY"),
        "blocked_cases": sum(1 for case in stored_cases if case.status == "BLOCKED"),
    }


def submit(db: Session, plan: TestPlan) -> TestPlan:
    revision = latest_revision(db, plan)
    if revision is None:
        raise InvalidPlanStateError("generate a matrix before submitting the plan")
    if plan.status == "NEEDS_CHANGES":
        raise InvalidPlanStateError(
            "the plan has blocking compatibility issues; fix them and regenerate"
        )
    if plan.status not in {"VALIDATING", "READY_FOR_REVIEW"}:
        raise InvalidPlanStateError(f"cannot submit a plan in status {plan.status}")

    plan.status = "READY_FOR_REVIEW"
    revision.status = "READY_FOR_REVIEW"
    db.commit()
    db.refresh(plan)
    return plan


def approve(db: Session, plan: TestPlan, revision_number: int) -> TestPlan:
    revision = latest_revision(db, plan)
    if revision is None:
        raise InvalidPlanStateError("the plan has no generated matrix")
    if revision_number != plan.current_revision:
        raise RevisionMismatchError(
            f"revision {revision_number} is not the current revision "
            f"({plan.current_revision})"
        )
    if plan.status != "READY_FOR_REVIEW":
        raise InvalidPlanStateError(
            f"only READY_FOR_REVIEW plans can be approved; plan is {plan.status}"
        )
    blocked = [case for case in list_cases(db, revision) if case.status != "READY"]
    if blocked:
        raise InvalidPlanStateError(
            f"{len(blocked)} test case(s) are blocked; regenerate the plan first"
        )

    now = _now()
    plan.status = "APPROVED"
    plan.approved_revision = revision.revision
    plan.approved_at = now
    revision.status = "APPROVED"
    revision.approved_at = now
    revision.invalidated_at = None
    db.commit()
    db.refresh(plan)
    return plan


def revoke(db: Session, plan: TestPlan) -> TestPlan:
    if plan.approved_revision is None:
        raise InvalidPlanStateError("the plan has no approval to revoke")
    revision = latest_revision(db, plan)
    if revision is not None:
        revision.invalidated_at = _now()
        revision.status = "READY_FOR_REVIEW"
    plan.approved_revision = None
    plan.approved_at = None
    plan.status = "READY_FOR_REVIEW"
    db.commit()
    db.refresh(plan)
    return plan


def plan_ready_for_execution(plan: TestPlan) -> bool:
    """True only for the exact approved revision (planning authorization)."""
    return (
        plan.status == "APPROVED"
        and plan.approved_revision is not None
        and plan.approved_revision == plan.current_revision
    )
