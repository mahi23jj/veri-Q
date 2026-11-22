"""Deterministic compatibility engine.

Answers one question: can the selected scenario be tested *meaningfully and
safely* against this task and configuration? It is not a verdict about a
reliability test — nothing has executed. It is also not a capability probe:
it reasons over declared configuration only.

Pure functions, no I/O, no ORM, no clock. Given the same inputs it returns the
same reasons in the same order.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from app.domain.scenarios.catalog import (
    IMPLEMENTATION_STATUS_RUNNER,
    SUPPORTED_STATUS_SUPPORTED,
    ScenarioDefinition,
)

STATUS_COMPATIBLE = "COMPATIBLE"
STATUS_NEEDS_CONFIGURATION = "NEEDS_CONFIGURATION"
STATUS_UNSUPPORTED = "UNSUPPORTED"

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_CONFIGURATION = "configuration"
SEVERITY_UNSUPPORTED = "unsupported"

_EXECUTION_NOTE = (
    "Compatible means the configuration is well-formed. Starting a run is a "
    "separate explicit action on an approved plan revision; this evaluation "
    "never executes anything."
)
_EXECUTION_UNAVAILABLE_NOTE = (
    "No runner injector is implemented for this scenario yet, so it cannot be "
    "executed even when the configuration is compatible."
)


@dataclass(frozen=True)
class TaskView:
    id: str
    task_name: str
    status: str = "DISCOVERED"


@dataclass(frozen=True)
class CheckpointView:
    id: str
    name: str
    reliability_enabled: bool = False


@dataclass(frozen=True)
class AdapterView:
    id: str
    name: str
    adapter_type: str
    category: str
    capabilities: frozenset[str]
    enabled_triggers: frozenset[str]
    status: str = "CONFIGURED"

    @property
    def validated(self) -> bool:
        return self.status == "VALIDATED"


@dataclass(frozen=True)
class ContractView:
    id: str
    version: int
    payload: Mapping[str, Any]
    valid: bool = True

    @property
    def safe_input(self) -> Mapping[str, Any]:
        value = self.payload.get("safe_input")
        return value if isinstance(value, Mapping) else {}

    @property
    def input_fixture_ref(self) -> str | None:
        value = self.payload.get("input_fixture_ref")
        return value if isinstance(value, str) and value.strip() else None

    @property
    def measurements(self) -> tuple[Mapping[str, Any], ...]:
        value = self.payload.get("effect_measurements")
        return tuple(m for m in value if isinstance(m, Mapping)) if isinstance(value, list) else ()

    @property
    def assertions(self) -> tuple[Mapping[str, Any], ...]:
        value = self.payload.get("assertions")
        return tuple(a for a in value if isinstance(a, Mapping)) if isinstance(value, list) else ()

    @property
    def cleanup(self) -> Mapping[str, Any]:
        value = self.payload.get("cleanup")
        return value if isinstance(value, Mapping) else {}


@dataclass(frozen=True)
class Reason:
    code: str
    severity: str
    message: str
    field: str | None = None

    def to_dict(self) -> dict:
        payload = {"code": self.code, "severity": self.severity, "message": self.message}
        if self.field is not None:
            payload["field"] = self.field
        return payload


@dataclass(frozen=True)
class CompatibilityResult:
    status: str
    reasons: tuple[Reason, ...]
    selected_adapters: tuple[dict, ...] = ()
    scenario_id: str | None = None
    scenario_version: int | None = None
    trigger_type: str | None = None
    checkpoint_name: str | None = None
    execution_available: bool = False

    @property
    def blocking_reasons(self) -> tuple[Reason, ...]:
        return tuple(
            r for r in self.reasons if r.severity in (SEVERITY_CONFIGURATION, SEVERITY_UNSUPPORTED)
        )

    @property
    def warnings(self) -> tuple[Reason, ...]:
        return tuple(r for r in self.reasons if r.severity == SEVERITY_WARNING)

    @property
    def compatible(self) -> bool:
        return self.status == STATUS_COMPATIBLE

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "reasons": [reason.to_dict() for reason in self.reasons],
            "warnings": [reason.to_dict() for reason in self.warnings],
            "selected_adapters": list(self.selected_adapters),
            "scenario_id": self.scenario_id,
            "scenario_version": self.scenario_version,
            "trigger_type": self.trigger_type,
            "checkpoint_name": self.checkpoint_name,
            "execution_available": self.execution_available,
            "execution_note": (
                _EXECUTION_NOTE if self.execution_available else _EXECUTION_UNAVAILABLE_NOTE
            ),
        }


def _reasons_by_severity(reasons: Iterable[Reason]) -> str:
    reasons = tuple(reasons)
    if any(r.severity == SEVERITY_UNSUPPORTED for r in reasons):
        return STATUS_UNSUPPORTED
    if any(r.severity == SEVERITY_CONFIGURATION for r in reasons):
        return STATUS_NEEDS_CONFIGURATION
    return STATUS_COMPATIBLE


def _adapter_for(
    adapters: Sequence[AdapterView], *, category: str, capability: str, trigger: str | None
) -> tuple[AdapterView | None, list[Reason]]:
    """Pick the adapter that satisfies one requirement, plus reasons why not.

    Preference order is deterministic: validated adapters first, then by id.
    """
    reasons: list[Reason] = []
    candidates = [
        adapter
        for adapter in adapters
        if adapter.category == category and capability in adapter.capabilities
    ]
    if not candidates:
        reasons.append(
            Reason(
                code="ADAPTER_NOT_CONFIGURED",
                severity=SEVERITY_CONFIGURATION,
                message=(
                    f"No configured {category} adapter declares the "
                    f"'{capability}' capability for this application."
                ),
                field=f"adapters.{category}",
            )
        )
        return None, reasons

    validated = [adapter for adapter in candidates if adapter.validated]
    if not validated:
        reasons.append(
            Reason(
                code="ADAPTER_NOT_VALIDATED",
                severity=SEVERITY_CONFIGURATION,
                message=(
                    f"The {category} adapter is configured but has not passed "
                    "configuration validation."
                ),
                field=f"adapters.{category}.status",
            )
        )
        return None, reasons

    if trigger is not None:
        trigger_ready = [
            adapter for adapter in validated if trigger in adapter.enabled_triggers
        ]
        if trigger_ready:
            chosen = sorted(trigger_ready, key=lambda adapter: adapter.id)[0]
        else:
            chosen = sorted(validated, key=lambda adapter: adapter.id)[0]
    else:
        chosen = sorted(validated, key=lambda adapter: adapter.id)[0]

    if trigger is not None and trigger not in chosen.enabled_triggers:
        reasons.append(
            Reason(
                code="TRIGGER_CAPABILITY_NOT_ENABLED",
                severity=SEVERITY_CONFIGURATION,
                message=(
                    f"The {category} adapter '{chosen.name}' does not have the "
                    f"'{trigger}' trigger enabled."
                ),
                field=f"adapters.{category}.enabled_triggers",
            )
        )
        return chosen, reasons
    return chosen, reasons


def _measurement_reasons(
    contract: ContractView,
    adapters: Sequence[AdapterView],
    scenario: ScenarioDefinition,
) -> tuple[list[Reason], list[dict]]:
    reasons: list[Reason] = []
    by_id = {adapter.id: adapter for adapter in adapters}
    usable: list[tuple[Mapping[str, Any], AdapterView]] = []
    for measurement in contract.measurements:
        adapter_id = measurement.get("adapter_id")
        adapter = by_id.get(str(adapter_id)) if adapter_id is not None else None
        if adapter is None:
            reasons.append(
                Reason(
                    code="MEASUREMENT_ADAPTER_NOT_CONFIGURED",
                    severity=SEVERITY_CONFIGURATION,
                    message=(
                        f"Effect measurement '{measurement.get('id')}' references an "
                        "adapter that is not configured for this application."
                    ),
                    field=f"effect_measurements.{measurement.get('id')}",
                )
            )
            continue
        if "effect_measurement" not in adapter.capabilities:
            reasons.append(
                Reason(
                    code="MEASUREMENT_CAPABILITY_MISSING",
                    severity=SEVERITY_CONFIGURATION,
                    message=(
                        f"Adapter '{adapter.name}' cannot measure effects "
                        "(it does not declare effect_measurement)."
                    ),
                    field=f"effect_measurements.{measurement.get('id')}.adapter_id",
                )
            )
            continue
        usable.append((measurement, adapter))

    authoritative = [m for m, _ in usable if bool(m.get("authoritative"))]
    if scenario.requires_effect_measurement and not usable:
        reasons.append(
            Reason(
                code="MISSING_EFFECT_MEASUREMENT",
                severity=SEVERITY_CONFIGURATION,
                message=(
                    "The scenario needs a business-effect measurement; the task test "
                    "contract defines none that uses a configured adapter."
                ),
                field="effect_measurements",
            )
        )
    elif scenario.requires_authoritative_measurement and not authoritative:
        reasons.append(
            Reason(
                code="NON_AUTHORITATIVE_MEASUREMENT",
                severity=SEVERITY_CONFIGURATION,
                message=(
                    "The scenario needs an authoritative effect measurement so the "
                    "business outcome can be judged; all configured measurements are "
                    "advisory."
                ),
                field="effect_measurements.authoritative",
            )
        )
    elif not usable:
        reasons.append(
            Reason(
                code="NO_EFFECT_MEASUREMENT",
                severity=SEVERITY_WARNING,
                message=(
                    "No effect measurement is configured: the outcome will be judged "
                    "from assertions only, not from business effects."
                ),
                field="effect_measurements",
            )
        )

    refs = [
        {"measurement_id": m.get("id"), "adapter_id": adapter.id, "adapter_name": adapter.name}
        for m, adapter in usable
    ]
    return reasons, refs


def evaluate(
    *,
    task: TaskView,
    scenario: ScenarioDefinition,
    trigger_type: str,
    checkpoint: CheckpointView | None,
    contract: ContractView | None,
    adapters: Sequence[AdapterView],
) -> CompatibilityResult:
    """Evaluate one (task, scenario, trigger, checkpoint) combination.

    ``trigger_type`` is the concrete mode: ``automatic`` or ``checkpoint``.
    """
    reasons: list[Reason] = []
    adapters = tuple(adapters)

    # 1. Scenario / trigger support.
    if scenario.supported_status != SUPPORTED_STATUS_SUPPORTED:
        reasons.append(
            Reason(
                code="SCENARIO_UNSUPPORTED",
                severity=SEVERITY_UNSUPPORTED,
                message=f"VeriQ does not support scenario '{scenario.id}'.",
                field="scenario_id",
            )
        )
    if trigger_type not in scenario.supported_trigger_modes:
        reasons.append(
            Reason(
                code="TRIGGER_MODE_UNSUPPORTED",
                severity=SEVERITY_UNSUPPORTED,
                message=(
                    f"Scenario '{scenario.id}' does not support the "
                    f"'{trigger_type}' trigger mode."
                ),
                field="trigger_type",
            )
        )

    # 2. Adapter requirements.
    selected: list[dict] = []
    for requirement in scenario.adapter_requirements:
        adapter, adapter_reasons = _adapter_for(
            adapters,
            category=requirement.category,
            capability=requirement.capability,
            trigger=requirement.trigger,
        )
        reasons.extend(adapter_reasons)
        if adapter is not None:
            selected.append(
                {
                    "adapter_id": adapter.id,
                    "adapter_name": adapter.name,
                    "adapter_type": adapter.adapter_type,
                    "category": adapter.category,
                    "trigger": requirement.trigger,
                }
            )

    # 3. Checkpoint availability (only for checkpoint-triggered cases).
    if trigger_type == "checkpoint":
        if checkpoint is None:
            reasons.append(
                Reason(
                    code="CHECKPOINT_NOT_SELECTED",
                    severity=SEVERITY_CONFIGURATION,
                    message="A checkpoint-triggered scenario needs a selected checkpoint.",
                    field="checkpoint_id",
                )
            )
        elif not checkpoint.reliability_enabled:
            reasons.append(
                Reason(
                    code="CHECKPOINT_NOT_ENABLED",
                    severity=SEVERITY_CONFIGURATION,
                    message=(
                        f"Checkpoint '{checkpoint.name}' is not enabled for "
                        "reliability testing."
                    ),
                    field="checkpoint.reliability_enabled",
                )
            )
    elif scenario.requires_checkpoint and checkpoint is None:
        reasons.append(
            Reason(
                code="CHECKPOINT_REQUIRED",
                severity=SEVERITY_CONFIGURATION,
                message="This scenario can only run at a discovered checkpoint.",
                field="checkpoint_id",
            )
        )

    # 4. Contract completeness.
    needs_contract = (
        scenario.requires_safe_input
        or scenario.requires_assertions
        or scenario.requires_effect_measurement
    )
    if contract is None:
        if needs_contract:
            reasons.append(
                Reason(
                    code="CONTRACT_MISSING",
                    severity=SEVERITY_CONFIGURATION,
                    message=(
                        f"Task '{task.task_name}' has no test contract, so VeriQ has no "
                        "safe input, assertions or effect measurement to evaluate."
                    ),
                    field="contract",
                )
            )
    else:
        if not contract.valid:
            reasons.append(
                Reason(
                    code="CONTRACT_INVALID",
                    severity=SEVERITY_CONFIGURATION,
                    message="The task test contract failed validation.",
                    field="contract",
                )
            )
        if scenario.requires_safe_input and not (
            contract.safe_input or contract.input_fixture_ref
        ):
            reasons.append(
                Reason(
                    code="MISSING_SAFE_INPUT",
                    severity=SEVERITY_CONFIGURATION,
                    message=(
                        "The contract declares no safe test input or fixture reference."
                    ),
                    field="contract.safe_input",
                )
            )
        if scenario.requires_assertions and not contract.assertions:
            reasons.append(
                Reason(
                    code="MISSING_ASSERTIONS",
                    severity=SEVERITY_CONFIGURATION,
                    message=(
                        "The contract declares no measurable assertions, so the "
                        "outcome could not be judged."
                    ),
                    field="contract.assertions",
                )
            )

        measurement_reasons, measurement_refs = _measurement_reasons(contract, adapters, scenario)
        reasons.extend(measurement_reasons)
        if measurement_refs:
            selected.append({"measurement_refs": measurement_refs})

        cleanup = contract.cleanup
        mode = cleanup.get("mode") or "none"
        scope = cleanup.get("resource_scope") or "test_owned"
        if mode == "none":
            reasons.append(
                Reason(
                    code="NO_CLEANUP_CONFIGURED",
                    severity=SEVERITY_WARNING,
                    message=(
                        "No cleanup is configured; the plan will leave test-owned "
                        "resources behind after execution."
                    ),
                    field="contract.cleanup",
                )
            )
        else:
            if scope != "test_owned":
                reasons.append(
                    Reason(
                        code="CLEANUP_SCOPE_INVALID",
                        severity=SEVERITY_CONFIGURATION,
                        message="Cleanup must be scoped to test-owned resources only.",
                        field="contract.cleanup.resource_scope",
                    )
                )
            if mode == "adapter_managed":
                cleanup_adapter = next(
                    (
                        adapter
                        for adapter in adapters
                        if adapter.id == str(cleanup.get("adapter_id"))
                    ),
                    None,
                )
                if cleanup_adapter is None or "resource_cleanup" not in cleanup_adapter.capabilities:
                    reasons.append(
                        Reason(
                            code="CLEANUP_ADAPTER_NOT_CONFIGURED",
                            severity=SEVERITY_CONFIGURATION,
                            message=(
                                "Cleanup is adapter-managed but no configured adapter "
                                "declares resource_cleanup."
                            ),
                            field="contract.cleanup.adapter_id",
                        )
                    )

    # 5. Scenario-specific warnings.
    for warning in scenario.warnings:
        reasons.append(
            Reason(code="SCENARIO_WARNING", severity=SEVERITY_WARNING, message=warning)
        )

    status = _reasons_by_severity(reasons)
    return CompatibilityResult(
        status=status,
        reasons=tuple(reasons),
        selected_adapters=tuple(selected),
        scenario_id=scenario.id,
        scenario_version=scenario.version,
        trigger_type=trigger_type,
        checkpoint_name=checkpoint.name if checkpoint is not None else None,
        # Executable by the runner once the plan revision is approved, and only
        # when the configuration is compatible and an injector exists.
        execution_available=(
            status == STATUS_COMPATIBLE
            and scenario.implementation_status == IMPLEMENTATION_STATUS_RUNNER
        ),
    )
