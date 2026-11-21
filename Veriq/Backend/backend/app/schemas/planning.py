"""Request/response schemas for reliability-test planning.

Contract bodies are validated here (structure and internal consistency) and
again in the service layer against the application's configured adapters.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.adapters.catalog import ADAPTER_CAPABILITIES, ADAPTER_CATEGORIES

_ID_PATTERN = r"^[a-z][a-z0-9_]{1,63}$"
_SLUG_PATTERN = r"^[a-z][a-z0-9_-]{1,63}$"
_SECRET_KEY_PATTERN = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|credential|private[_-]?key|authorization)",
    re.IGNORECASE,
)
_MAX_SAFE_INPUT_CHARS = 8000
_MAX_SAFE_INPUT_KEYS = 50
_MAX_SAFE_INPUT_DEPTH = 5

AssertionType = Literal[
    "effect_exists", "effect_count", "effect_absent", "effect_value", "execution_status"
]
TriggerType = Literal["automatic", "checkpoint"]
PlanStatus = Literal[
    "DRAFT", "VALIDATING", "NEEDS_CHANGES", "READY_FOR_REVIEW", "APPROVED"
]


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


def _check_safe_input(value: dict[str, Any]) -> dict[str, Any]:
    if len(value) > _MAX_SAFE_INPUT_KEYS:
        raise ValueError(f"safe_input supports at most {_MAX_SAFE_INPUT_KEYS} keys")

    def walk(node: Any, depth: int) -> None:
        if depth > _MAX_SAFE_INPUT_DEPTH:
            raise ValueError("safe_input is nested too deeply")
        if isinstance(node, dict):
            for key, child in node.items():
                if not isinstance(key, str) or not key.strip():
                    raise ValueError("safe_input keys must be non-empty strings")
                if _SECRET_KEY_PATTERN.search(key):
                    raise ValueError(
                        f"safe_input key '{key}' looks like a secret; contracts must "
                        "never contain credentials"
                    )
                walk(child, depth + 1)
        elif isinstance(node, list):
            for child in node:
                walk(child, depth + 1)
        elif node is not None and not isinstance(node, (str, int, float, bool)):
            raise ValueError("safe_input values must be JSON scalars, lists or objects")

    walk(value, 1)
    if len(json.dumps(value, default=str)) > _MAX_SAFE_INPUT_CHARS:
        raise ValueError("safe_input is too large")
    return value


class EffectMeasurementInput(BaseModel):
    id: str = Field(..., pattern=_ID_PATTERN)
    description: str | None = Field(default=None, max_length=500)
    adapter_id: uuid.UUID
    measurement_type: str = Field(..., min_length=1, max_length=100)
    config: dict[str, Any] = Field(default_factory=dict)
    authoritative: bool = False


class AssertionInput(BaseModel):
    id: str = Field(..., pattern=_ID_PATTERN)
    description: str = Field(..., min_length=1, max_length=500)
    type: AssertionType
    measurement_id: str | None = Field(default=None, pattern=_ID_PATTERN)
    expected: Any = None
    path: str | None = Field(default=None, max_length=200)
    severity: Literal["required", "warning"] = "required"

    @model_validator(mode="after")
    def _type_requirements(self) -> "AssertionInput":
        if self.type == "execution_status":
            if not isinstance(self.expected, str) or not self.expected.strip():
                raise ValueError(
                    "execution_status assertions require an expected status string"
                )
            if self.measurement_id is not None:
                raise ValueError(
                    "execution_status assertions must not reference a measurement"
                )
            return self
        if self.measurement_id is None:
            raise ValueError(
                f"'{self.type}' assertions must reference a measurement_id"
            )
        if self.type == "effect_count":
            if not isinstance(self.expected, int) or isinstance(self.expected, bool):
                raise ValueError("effect_count assertions require an integer expected value")
            if self.expected < 0:
                raise ValueError("effect_count expected value must be >= 0")
        elif self.type == "effect_value":
            if not self.path:
                raise ValueError("effect_value assertions require a path")
            if self.expected is None:
                raise ValueError("effect_value assertions require an expected value")
        return self


class CleanupInput(BaseModel):
    mode: Literal["none", "adapter_managed", "fixture_managed"] = "none"
    adapter_id: uuid.UUID | None = None
    resource_scope: Literal["test_owned"] = "test_owned"
    description: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _adapter_required(self) -> "CleanupInput":
        if self.mode == "adapter_managed" and self.adapter_id is None:
            raise ValueError("adapter_managed cleanup requires an adapter_id")
        return self


class RecoveryPolicyInput(BaseModel):
    """What "recovered" means for this task's reliability tests.

    The runner evaluates these expectations against observed execution evidence
    only; no business-effect verification is performed in this phase.
    """

    max_attempts: int = Field(default=3, ge=1, le=20)
    per_attempt_timeout_seconds: int = Field(default=60, ge=1, le=3600)
    recovery_deadline_seconds: int = Field(default=120, ge=1, le=3600)
    expected_terminal_state: Literal["SUCCEEDED", "FAILED", "ANY"] = "SUCCEEDED"
    expect_retry: bool | None = None
    expect_redelivery: bool | None = None
    settle_seconds: int = Field(default=3, ge=1, le=120)


class TaskTestContractPayload(BaseModel):
    safe_input: dict[str, Any] = Field(default_factory=dict)
    input_fixture_ref: str | None = Field(default=None, max_length=500)
    effect_measurements: list[EffectMeasurementInput] = Field(default_factory=list)
    assertions: list[AssertionInput] = Field(default_factory=list)
    cleanup: CleanupInput = Field(default_factory=CleanupInput)
    recovery: RecoveryPolicyInput = Field(default_factory=RecoveryPolicyInput)
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("safe_input")
    @classmethod
    def _safe_input_ok(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _check_safe_input(value)

    @field_validator("assertions")
    @classmethod
    def _assertions_consistent(
        cls, value: list[AssertionInput]
    ) -> list[AssertionInput]:
        ids = [assertion.id for assertion in value]
        if len(ids) != len(set(ids)):
            raise ValueError("assertion ids must be unique")
        return value

    @field_validator("effect_measurements")
    @classmethod
    def _measurements_consistent(
        cls, value: list[EffectMeasurementInput]
    ) -> list[EffectMeasurementInput]:
        ids = [measurement.id for measurement in value]
        if len(ids) != len(set(ids)):
            raise ValueError("effect measurement ids must be unique")
        return value

    @model_validator(mode="after")
    def _assertions_reference_measurements(self) -> "TaskTestContractPayload":
        measurement_ids = {measurement.id for measurement in self.effect_measurements}
        for assertion in self.assertions:
            if assertion.measurement_id and assertion.measurement_id not in measurement_ids:
                raise ValueError(
                    f"assertion '{assertion.id}' references unknown measurement "
                    f"'{assertion.measurement_id}'"
                )
        return self


class ContractIssue(BaseModel):
    code: str
    severity: Literal["error", "warning"]
    message: str
    field: str | None = None


class ContractValidationResponse(BaseModel):
    valid: bool
    issues: list[ContractIssue] = Field(default_factory=list)


class TaskTestContractResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    target_app_id: uuid.UUID
    registered_task_id: uuid.UUID
    version: int
    payload: dict[str, Any]
    validation: dict[str, Any] | None
    last_validated_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TaskTestContractVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    contract_id: uuid.UUID
    version: int
    payload: dict[str, Any]
    validation: dict[str, Any] | None
    created_at: datetime


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------


class AdapterTypeResponse(BaseModel):
    slug: str
    name: str
    category: str
    description: str
    capabilities: list[str]
    supported_triggers: list[str]
    version: str
    builtin: bool


class AdapterDefinitionCreate(BaseModel):
    slug: str = Field(..., pattern=_SLUG_PATTERN)
    name: str = Field(..., min_length=1, max_length=150)
    category: Literal["http", "database", "broker", "storage", "custom"] = "custom"
    description: str | None = Field(default=None, max_length=2000)
    capabilities: list[str] = Field(default_factory=list)
    supported_triggers: list[str] = Field(default_factory=list)
    version: str = Field(default="1.0", max_length=20)

    @field_validator("capabilities")
    @classmethod
    def _capabilities_known(cls, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - set(ADAPTER_CAPABILITIES))
        if unknown:
            raise ValueError(f"unknown capabilities: {', '.join(unknown)}")
        return list(dict.fromkeys(value))

    @field_validator("supported_triggers")
    @classmethod
    def _triggers_clean(cls, value: list[str]) -> list[str]:
        cleaned = [trigger.strip() for trigger in value if trigger.strip()]
        return list(dict.fromkeys(cleaned))


class AdapterCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    adapter_type: str = Field(..., min_length=1, max_length=100)
    capabilities: list[str] | None = None
    enabled_triggers: list[str] = Field(default_factory=list)
    configuration_ref: str | None = Field(default=None, max_length=500)

    @field_validator("configuration_ref")
    @classmethod
    def _no_inline_credentials(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            return None
        if _SECRET_KEY_PATTERN.search(text) and "=" in text:
            raise ValueError(
                "configuration_ref must be an opaque reference, not an inline credential"
            )
        return text

    @field_validator("enabled_triggers")
    @classmethod
    def _triggers_deduped(cls, value: list[str]) -> list[str]:
        cleaned = [trigger.strip() for trigger in value if trigger.strip()]
        return list(dict.fromkeys(cleaned))


class AdapterUpdate(BaseModel):
    enabled_triggers: list[str] | None = None
    configuration_ref: str | None = Field(default=None, max_length=500)

    @field_validator("enabled_triggers")
    @classmethod
    def _triggers_deduped(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned = [trigger.strip() for trigger in value if trigger.strip()]
        return list(dict.fromkeys(cleaned))


class AdapterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    target_app_id: uuid.UUID
    name: str
    adapter_type: str
    category: str
    capabilities: list[str]
    enabled_triggers: list[str]
    configuration_ref: str | None
    status: str
    validation: dict[str, Any] | None
    validated_at: datetime | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Checkpoints and selections
# ---------------------------------------------------------------------------


class CheckpointResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    target_app_id: uuid.UUID
    registered_task_id: uuid.UUID
    name: str
    discovery_source: str
    first_seen_at: datetime
    last_seen_at: datetime
    report_count: int
    checkpoint_metadata: dict[str, Any] | None
    reliability_enabled: bool

    @field_validator("first_seen_at", "last_seen_at")
    @classmethod
    def _timestamps_utc(cls, value: datetime) -> datetime:
        return _as_utc(value) or value


class CheckpointReliabilityUpdate(BaseModel):
    reliability_enabled: bool


class ScenarioSelectionUpsert(BaseModel):
    enabled: bool = True
    config: dict[str, Any] | None = None
    assertion_overrides: list[AssertionInput] | None = None


class TaskScenarioUpsert(BaseModel):
    enabled: bool
    config: dict[str, Any] | None = None


class TaskScenarioItem(BaseModel):
    scenario_id: str
    scenario_version: int
    name: str
    category: str
    description: str
    default_trigger_type: str
    supported_status: str
    implementation_status: str
    enabled: bool
    selected_by_default: bool
    config: dict[str, Any] | None
    compatibility: dict[str, Any]


class CheckpointScenarioItem(BaseModel):
    scenario_id: str
    scenario_version: int
    name: str
    category: str
    enabled: bool
    config: dict[str, Any] | None
    assertion_overrides: list[dict[str, Any]] | None
    compatibility: dict[str, Any]


class CheckpointWithScenarios(CheckpointResponse):
    scenarios: list[CheckpointScenarioItem] = Field(default_factory=list)


class TaskReliabilityOverview(BaseModel):
    registered_task: dict[str, Any]
    automatic_scenarios: list[TaskScenarioItem]
    checkpoints: list[CheckpointWithScenarios]
    contract: TaskTestContractResponse | None
    contract_issues: list[ContractIssue] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Compatibility
# ---------------------------------------------------------------------------


class CompatibilitySelection(BaseModel):
    task_id: uuid.UUID
    scenario_id: str = Field(..., min_length=1, max_length=100)
    trigger_type: TriggerType = "automatic"
    checkpoint_id: uuid.UUID | None = None


class CompatibilityEvaluateRequest(BaseModel):
    selections: list[CompatibilitySelection] = Field(..., min_length=1, max_length=200)


class CompatibilityEvaluation(BaseModel):
    task_id: uuid.UUID
    task_name: str
    scenario_id: str
    scenario_version: int
    trigger_type: str
    checkpoint_id: uuid.UUID | None = None
    checkpoint_name: str | None = None
    status: str
    reasons: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    selected_adapters: list[dict[str, Any]]
    execution_available: bool
    execution_note: str


class CompatibilityEvaluateResponse(BaseModel):
    results: list[CompatibilityEvaluation]


# ---------------------------------------------------------------------------
# Test plans
# ---------------------------------------------------------------------------


class TestPlanCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    task_ids: list[uuid.UUID] = Field(..., min_length=1, max_length=100)


class TestPlanUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    task_ids: list[uuid.UUID] | None = Field(default=None, min_length=1, max_length=100)


class TestPlanRevisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    test_plan_id: uuid.UUID
    revision: int
    status: str
    snapshot: dict[str, Any]
    summary: dict[str, Any] | None
    created_at: datetime
    approved_at: datetime | None
    invalidated_at: datetime | None


class TestPlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    target_app_id: uuid.UUID
    name: str
    description: str | None
    status: str
    task_ids: list[uuid.UUID]
    current_revision: int
    approved_revision: int | None
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime
    ready_for_execution: bool = False
    execution_available: bool = False


class TestCaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_key: str
    status: str
    task_name: str
    scenario_id: str
    scenario_version: int
    trigger_type: str
    checkpoint_name: str | None
    contract_version: int | None
    adapter_refs: list[dict[str, Any]]
    test_input: dict[str, Any] | None
    input_fixture_ref: str | None
    assertions: list[dict[str, Any]]
    cleanup: dict[str, Any] | None
    scenario_config: dict[str, Any] | None = None
    recovery_policy: dict[str, Any] | None = None
    compatibility: dict[str, Any]
    configuration_fingerprint: str


class TestPlanDetail(TestPlanResponse):
    latest_revision: TestPlanRevisionResponse | None = None
    duplicates: list[dict[str, Any]] = Field(default_factory=list)


class TestPlanGenerateResponse(BaseModel):
    plan: TestPlanResponse
    revision: TestPlanRevisionResponse
    summary: dict[str, Any]
    duplicates: list[dict[str, Any]] = Field(default_factory=list)


class TestPlanValidationResponse(BaseModel):
    plan: TestPlanResponse
    revision: int
    ok: bool
    blocking_issues: list[dict[str, Any]] = Field(default_factory=list)
    drift: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    total_cases: int = 0
    ready_cases: int = 0
    blocked_cases: int = 0


class TestPlanApproveRequest(BaseModel):
    revision: int = Field(..., ge=1)
