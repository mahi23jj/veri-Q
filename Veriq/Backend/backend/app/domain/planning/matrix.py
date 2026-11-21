"""Scenario matrix generation (pure).

One matrix row is: task + scenario + trigger type + injection point + the
configuration snapshot used to evaluate it. Generation is deterministic: the
same combinations always produce the same case keys and fingerprints.

Rows are only generated for selected combinations. A selected combination that
is no longer compatible is kept as ``BLOCKED`` with its reasons instead of being
silently dropped — the developer must see why the plan needs changes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from app.domain.compatibility.engine import CompatibilityResult

CASE_READY = "READY"
CASE_BLOCKED = "BLOCKED"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EvaluatedCombination:
    """Everything needed to turn one selected combination into a matrix row."""

    target_app_id: str
    task_id: str
    task_name: str
    scenario_id: str
    scenario_version: int
    scenario_name: str
    scenario_category: str
    trigger_type: str
    checkpoint_id: str | None
    checkpoint_name: str | None
    contract_id: str | None
    contract_version: int | None
    safe_input: Mapping[str, Any]
    input_fixture_ref: str | None
    assertions: tuple[Mapping[str, Any], ...]
    cleanup: Mapping[str, Any]
    adapter_refs: tuple[Mapping[str, Any], ...]
    compatibility: CompatibilityResult
    scenario_config: Mapping[str, Any] = field(default_factory=dict)
    recovery_policy: Mapping[str, Any] = field(default_factory=dict)

    def configuration(self) -> dict:
        """The reproducible part of the case (no compatibility verdict)."""
        return {
            "target_app_id": self.target_app_id,
            "task_id": self.task_id,
            "task_name": self.task_name,
            "scenario_id": self.scenario_id,
            "scenario_version": self.scenario_version,
            "trigger_type": self.trigger_type,
            "checkpoint_id": self.checkpoint_id,
            "checkpoint_name": self.checkpoint_name,
            "contract_id": self.contract_id,
            "contract_version": self.contract_version,
            "safe_input": dict(self.safe_input),
            "input_fixture_ref": self.input_fixture_ref,
            "assertions": [dict(a) for a in self.assertions],
            "cleanup": dict(self.cleanup),
            "adapter_refs": [dict(a) for a in self.adapter_refs],
            "scenario_config": dict(self.scenario_config),
            "recovery_policy": dict(self.recovery_policy),
        }

    @property
    def configuration_fingerprint(self) -> str:
        return _digest(self.configuration())

    @property
    def case_key(self) -> str:
        return _digest(
            {
                "target_app_id": self.target_app_id,
                "task_id": self.task_id,
                "scenario_id": self.scenario_id,
                "trigger_type": self.trigger_type,
                "checkpoint_name": self.checkpoint_name,
                "configuration_fingerprint": self.configuration_fingerprint,
            }
        )[:32]


@dataclass(frozen=True)
class MatrixRow:
    case_key: str
    status: str
    combination: EvaluatedCombination

    @property
    def configuration_fingerprint(self) -> str:
        return self.combination.configuration_fingerprint

    def to_dict(self) -> dict:
        combination = self.combination
        return {
            "case_key": self.case_key,
            "status": self.status,
            "target_app_id": combination.target_app_id,
            "registered_task_id": combination.task_id,
            "task_name": combination.task_name,
            "scenario_id": combination.scenario_id,
            "scenario_version": combination.scenario_version,
            "scenario_name": combination.scenario_name,
            "scenario_category": combination.scenario_category,
            "trigger_type": combination.trigger_type,
            "checkpoint_id": combination.checkpoint_id,
            "checkpoint_name": combination.checkpoint_name,
            "contract_id": combination.contract_id,
            "contract_version": combination.contract_version,
            "adapter_refs": [dict(a) for a in combination.adapter_refs],
            "test_input": dict(combination.safe_input),
            "input_fixture_ref": combination.input_fixture_ref,
            "assertions": [dict(a) for a in combination.assertions],
            "cleanup": dict(combination.cleanup),
            "scenario_config": dict(combination.scenario_config),
            "recovery_policy": dict(combination.recovery_policy),
            "compatibility": combination.compatibility.to_dict(),
            "configuration_fingerprint": combination.configuration_fingerprint,
        }


@dataclass(frozen=True)
class MatrixResult:
    rows: tuple[MatrixRow, ...]
    duplicates: tuple[dict, ...]
    summary: dict

    @property
    def blocked_count(self) -> int:
        return sum(1 for row in self.rows if row.status == CASE_BLOCKED)


def generate_matrix(combinations: Iterable[EvaluatedCombination]) -> MatrixResult:
    """Deduplicate and order combinations into reproducible matrix rows."""
    ordered = sorted(
        combinations,
        key=lambda c: (
            c.task_name,
            c.scenario_id,
            c.trigger_type,
            c.checkpoint_name or "",
            c.configuration_fingerprint,
        ),
    )

    seen: dict[str, MatrixRow] = {}
    duplicates: list[dict] = []
    for combination in ordered:
        fingerprint = combination.configuration_fingerprint
        if fingerprint in seen:
            kept = seen[fingerprint]
            duplicates.append(
                {
                    "compatibility": combination.compatibility.trigger_type,
                    "scenario_id": combination.scenario_id,
                    "task_name": combination.task_name,
                    "same_as_case_key": kept.case_key,
                    "reason": (
                        "identical task, scenario, trigger, injection point and "
                        "configuration snapshot"
                    ),
                }
            )
            continue
        status = CASE_READY if combination.compatibility.compatible else CASE_BLOCKED
        seen[fingerprint] = MatrixRow(
            case_key=combination.case_key, status=status, combination=combination
        )

    rows = tuple(seen.values())
    summary = {
        "total_cases": len(rows),
        "ready_cases": sum(1 for row in rows if row.status == CASE_READY),
        "blocked_cases": sum(1 for row in rows if row.status == CASE_BLOCKED),
        "deduplicated_cases": len(duplicates),
        "tasks": sorted({row.combination.task_name for row in rows}),
        "scenarios": sorted({row.combination.scenario_id for row in rows}),
        "checkpoints": sorted(
            {
                row.combination.checkpoint_name
                for row in rows
                if row.combination.checkpoint_name is not None
            }
        ),
    }
    return MatrixResult(rows=rows, duplicates=tuple(duplicates), summary=summary)


def merge_assertions(
    task_assertions: Sequence[Mapping[str, Any]],
    overrides: Sequence[Mapping[str, Any]] | None,
) -> tuple[dict, ...]:
    """Checkpoint assertions extend task-level defaults unless overridden by id."""
    merged: dict[str, dict] = {}
    for assertion in task_assertions:
        key = str(assertion.get("id"))
        merged[key] = dict(assertion)
    for assertion in overrides or ():
        key = str(assertion.get("id"))
        merged[key] = dict(assertion)
    return tuple(merged[key] for key in sorted(merged))
