"""VeriQ-owned, versioned scenario catalogue.

A scenario describes a *general* failure pattern. It is never tied to a
business task, and it never contains execution logic: injection is a future
runner concern. What it declares here is what planning needs — the capabilities
it requires, the configuration it accepts and the recovery characteristics the
developer should expect.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Bumped when any scenario definition changes semantically.
SCENARIO_CATALOG_VERSION = "2026.11"

# Planning support, not execution support. Every scenario in this catalogue is
# PLANNING_ONLY: represented, selectable and compatibility-checked, but its
# failure cannot be injected yet.
SUPPORTED_STATUS_SUPPORTED = "SUPPORTED"
IMPLEMENTATION_STATUS_PLANNING_ONLY = "PLANNING_ONLY"


@dataclass(frozen=True)
class AdapterRequirement:
    """One adapter an application must configure for a scenario to be testable."""

    category: str
    capability: str
    trigger: str | None = None
    description: str = ""


@dataclass(frozen=True)
class ScenarioDefinition:
    id: str
    name: str
    description: str
    category: str
    version: int
    default_trigger_type: str
    supported_trigger_modes: tuple[str, ...]
    adapter_requirements: tuple[AdapterRequirement, ...]
    preconditions: tuple[str, ...]
    configuration_schema: dict
    applicable_task_conditions: tuple[str, ...]
    measurement_requirements: tuple[str, ...]
    expected_recovery: tuple[str, ...]
    requires_safe_input: bool = True
    requires_assertions: bool = True
    requires_effect_measurement: bool = False
    requires_authoritative_measurement: bool = False
    requires_checkpoint: bool = False
    supported_status: str = SUPPORTED_STATUS_SUPPORTED
    implementation_status: str = IMPLEMENTATION_STATUS_PLANNING_ONLY
    warnings: tuple[str, ...] = ()

    @property
    def supports_automatic(self) -> bool:
        return "automatic" in self.supported_trigger_modes

    @property
    def supports_checkpoint(self) -> bool:
        return "checkpoint" in self.supported_trigger_modes

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "version": self.version,
            "default_trigger_type": self.default_trigger_type,
            "supported_trigger_modes": list(self.supported_trigger_modes),
            "adapter_requirements": [
                {
                    "category": req.category,
                    "capability": req.capability,
                    "trigger": req.trigger,
                    "description": req.description,
                }
                for req in self.adapter_requirements
            ],
            "preconditions": list(self.preconditions),
            "configuration_schema": self.configuration_schema,
            "applicable_task_conditions": list(self.applicable_task_conditions),
            "measurement_requirements": list(self.measurement_requirements),
            "expected_recovery": list(self.expected_recovery),
            "requires": {
                "safe_input": self.requires_safe_input,
                "assertions": self.requires_assertions,
                "effect_measurement": self.requires_effect_measurement,
                "authoritative_measurement": self.requires_authoritative_measurement,
                "checkpoint": self.requires_checkpoint,
            },
            "supported_status": self.supported_status,
            "implementation_status": self.implementation_status,
            "warnings": list(self.warnings),
        }


_DEPENDENCY_TIMEOUT = ScenarioDefinition(
    id="dependency_timeout",
    name="Dependency timeout",
    description=(
        "The task calls an external dependency, but the response takes longer "
        "than the configured timeout. Exercises timeout handling, retries, "
        "backoff and terminal failure behaviour."
    ),
    category="dependency",
    version=1,
    default_trigger_type="automatic",
    supported_trigger_modes=("automatic",),
    adapter_requirements=(
        AdapterRequirement(
            category="http",
            capability="failure_trigger",
            trigger="timeout_simulation",
            description="An HTTP adapter with timeout injection enabled.",
        ),
    ),
    preconditions=(
        "The task reaches at least one HTTP dependency through the configured adapter.",
        "A safe test input exists so the call can be replayed without real business effect.",
    ),
    configuration_schema={
        "type": "object",
        "properties": {
            "timeout_ms": {"type": "integer", "minimum": 1, "maximum": 600000},
            "dependency_url": {"type": "string", "maxLength": 500},
        },
        "additionalProperties": False,
    },
    applicable_task_conditions=(
        "task performs at least one HTTP request",
        "task handles or retries transport errors",
    ),
    measurement_requirements=(
        "Execution outcome assertions (SUCCEEDED / FAILED / RETRYING) are expected.",
        "Effect measurement is optional: timeout tests often assert on the terminal state.",
    ),
    expected_recovery=(
        "Retries with backoff, or a deterministic terminal failure.",
        "No partial business effect is left behind without an acknowledgement.",
    ),
    requires_effect_measurement=False,
    warnings=(
        "A connection timeout is not the same as a lost response; use "
        "successful_operation_lost_response when the request may have succeeded.",
    ),
)


_LOST_RESPONSE = ScenarioDefinition(
    id="successful_operation_lost_response",
    name="Successful operation, lost response",
    description=(
        "The external service processes the request successfully, but the task "
        "never receives the response. Exercises idempotency, reconciliation and "
        "retry safety under an uncertain external outcome."
    ),
    category="dependency",
    version=1,
    default_trigger_type="automatic",
    supported_trigger_modes=("automatic",),
    adapter_requirements=(
        AdapterRequirement(
            category="http",
            capability="failure_trigger",
            trigger="lost_response_simulation",
            description="An HTTP adapter with lost-response injection enabled.",
        ),
    ),
    preconditions=(
        "The dependency can be pointed at a sandbox endpoint.",
        "An authoritative effect measurement exists, because the task cannot tell "
        "success from failure locally.",
    ),
    configuration_schema={
        "type": "object",
        "properties": {
            "commit_then_drop_response": {"type": "boolean"},
            "dependency_url": {"type": "string", "maxLength": 500},
        },
        "additionalProperties": False,
    },
    applicable_task_conditions=(
        "task calls a non-idempotent external operation",
        "task retries on transport errors",
    ),
    measurement_requirements=(
        "An authoritative effect measurement (for example provider resource count) is required.",
        "Attempt execution count is NOT an acceptable substitute for the effect count.",
    ),
    expected_recovery=(
        "Exactly one business effect despite the retry.",
        "Reconciliation detects the already-applied operation.",
    ),
    requires_effect_measurement=True,
    requires_authoritative_measurement=True,
    warnings=(
        "The request must reach the dependency and succeed before the response is "
        "lost; this is not a connection timeout.",
    ),
)


_DUPLICATE_DELIVERY = ScenarioDefinition(
    id="duplicate_message_delivery",
    name="Duplicate message delivery",
    description=(
        "The same logical job is delivered more than once. Exercises duplicate "
        "processing, idempotency and duplicate business effects."
    ),
    category="messaging",
    version=1,
    default_trigger_type="automatic",
    supported_trigger_modes=("automatic", "checkpoint"),
    adapter_requirements=(
        AdapterRequirement(
            category="broker",
            capability="failure_trigger",
            trigger="duplicate_delivery",
            description="A broker adapter with duplicate-delivery injection enabled.",
        ),
    ),
    preconditions=(
        "The task's queue and routing are known to the broker adapter.",
        "An effect measurement counts business effects, not deliveries.",
    ),
    configuration_schema={
        "type": "object",
        "properties": {
            "delivery_count": {"type": "integer", "minimum": 2, "maximum": 10},
        },
        "additionalProperties": False,
    },
    applicable_task_conditions=(
        "task is not naturally idempotent",
        "task writes rows, files or external resources",
    ),
    measurement_requirements=(
        "Effect count assertion is expected (for example exactly one output row).",
        "Duplicate effects are a failure even when every execution reports SUCCESS.",
    ),
    expected_recovery=(
        "One business effect for two deliveries.",
        "Duplicate executions are detected or deduplicated by the application.",
    ),
    requires_effect_measurement=True,
    requires_authoritative_measurement=True,
)


_DATABASE_INTERRUPTION = ScenarioDefinition(
    id="database_connection_interruption",
    name="Database connection interruption",
    description=(
        "The database connection becomes unavailable during an operation. "
        "Exercises database error handling, transaction boundaries, retries and "
        "recovery from partial execution."
    ),
    category="database",
    version=1,
    default_trigger_type="automatic",
    supported_trigger_modes=("automatic", "checkpoint"),
    adapter_requirements=(
        AdapterRequirement(
            category="database",
            capability="failure_trigger",
            trigger="connection_interruption",
            description="A database adapter with connection-interruption injection enabled.",
        ),
    ),
    preconditions=(
        "A disposable test database is configured for the application.",
        "The task's writes are scoped to test-owned data.",
    ),
    configuration_schema={
        "type": "object",
        "properties": {
            "interrupt_after_statements": {"type": "integer", "minimum": 1, "maximum": 100},
            "preserve_existing_transaction": {"type": "boolean"},
        },
        "additionalProperties": False,
    },
    applicable_task_conditions=(
        "task writes to the application database",
        "task relies on transaction or retry semantics",
    ),
    measurement_requirements=(
        "Row-count or row-existence assertions are recommended.",
        "Partial writes must be distinguishable from committed effects.",
    ),
    expected_recovery=(
        "The transaction is rolled back or safely retried.",
        "No half-applied business state remains.",
    ),
    requires_effect_measurement=False,
    warnings=(
        "Never point the database adapter at production; only test-owned data is measured.",
    ),
)


_WORKER_TERMINATION = ScenarioDefinition(
    id="worker_termination",
    name="Worker termination during execution",
    description=(
        "The worker process executing the task is terminated. Supported conceptually "
        "in two trigger modes: during a general execution window, or immediately "
        "after a selected checkpoint."
    ),
    category="runtime",
    version=1,
    default_trigger_type="automatic",
    supported_trigger_modes=("automatic", "checkpoint"),
    adapter_requirements=(
        AdapterRequirement(
            category="broker",
            capability="dependency_observation",
            description="A broker adapter to observe acknowledgement and redelivery.",
        ),
    ),
    preconditions=(
        "The worker's acknowledgement policy is known (acks_late / acks_early).",
        "Task concurrency is 1 in the isolated runner so termination is attributable.",
    ),
    configuration_schema={
        "type": "object",
        "properties": {
            "termination_grace_seconds": {"type": "integer", "minimum": 0, "maximum": 300},
            "expect_redelivery": {"type": "boolean"},
        },
        "additionalProperties": False,
    },
    applicable_task_conditions=(
        "task performs multi-step work with observable intermediate state",
        "task may be retried after worker loss",
    ),
    measurement_requirements=(
        "Assertions about persisted intermediate state are recommended.",
        "Redelivery is a broker/acknowledgement property, not a guarantee.",
    ),
    expected_recovery=(
        "The job is redelivered or explicitly abandoned according to the ack policy.",
        "No duplicated or half-applied business effect.",
    ),
    requires_assertions=False,
    warnings=(
        "Worker loss does not always cause message redelivery: it depends on Celery "
        "acknowledgement settings and broker configuration.",
    ),
)


SCENARIO_CATALOG: tuple[ScenarioDefinition, ...] = (
    _DEPENDENCY_TIMEOUT,
    _LOST_RESPONSE,
    _DUPLICATE_DELIVERY,
    _DATABASE_INTERRUPTION,
    _WORKER_TERMINATION,
)

_BY_ID = {scenario.id: scenario for scenario in SCENARIO_CATALOG}


def get_scenario(scenario_id: str) -> ScenarioDefinition | None:
    return _BY_ID.get(scenario_id)


def list_scenarios(
    *, category: str | None = None, trigger_type: str | None = None
) -> list[ScenarioDefinition]:
    """List catalogue scenarios, optionally filtered (deterministic order)."""
    scenarios = list(SCENARIO_CATALOG)
    if category is not None:
        scenarios = [s for s in scenarios if s.category == category]
    if trigger_type is not None:
        scenarios = [s for s in scenarios if trigger_type in s.supported_trigger_modes]
    return scenarios
