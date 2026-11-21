"""Fault injector interfaces and the scenario -> injector registry.

`FaultController` coordinates; each injector owns exactly one mechanism. Nothing
here decides whether a fault *was* activated: the injector reports the facts and
the controller persists them as evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol

from app.domain.adapters.catalog import (
    CAPABILITY_DEPENDENCY_OBSERVATION,
    CAPABILITY_FAILURE_TRIGGER,
)
from app.domain.scenarios.catalog import get_scenario

TRIGGER_AUTOMATIC = "automatic"
TRIGGER_CHECKPOINT = "checkpoint"


class InjectorError(Exception):
    """The injector could not be prepared, activated or released."""


@dataclass
class FaultContext:
    """Everything an injector may use, scoped to one test case run.

    Callbacks are provided by the orchestrator/supervisor so an injector never
    reaches into the database, the Celery submission path or Docker directly.
    """

    test_run_id: str
    scenario_id: str
    config: Mapping[str, Any]
    trigger_type: str
    checkpoint_name: str | None = None
    operation_id: str = ""
    queue_name: str = ""
    # HTTP / database fault proxies.
    dependency_url: str | None = None
    database_upstream: tuple[str, int] | None = None
    advertised_host: str = "127.0.0.1"
    # Callbacks (all optional so an injector can be exercised in isolation).
    record: Callable[[str, str, dict[str, Any]], None] | None = None
    wait_for_checkpoint: Callable[[float], bool] | None = None
    wait_for_task_running: Callable[[float], bool] | None = None
    submit_duplicate: Callable[[int], list[str]] | None = None
    terminate_worker: Callable[[str], dict[str, Any]] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def emit(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        if self.record is not None:
            self.record("INJECTOR", event_type, payload or {})

    def integer(self, key: str, default: int, *, minimum: int, maximum: int) -> int:
        value = self.config.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int):
            return default
        return max(minimum, min(maximum, value))


class FaultInjector(Protocol):
    injector_type: str
    scenario_id: str

    def validate(self, context: FaultContext) -> list[str]: ...

    def prepare(self, context: FaultContext) -> dict[str, Any]: ...

    def wait_for_trigger(self, context: FaultContext, timeout_seconds: float) -> bool: ...

    def activate(self, context: FaultContext) -> dict[str, Any]: ...

    def deactivate(self, context: FaultContext) -> dict[str, Any]: ...

    def status(self) -> dict[str, Any]: ...

    def close(self) -> None: ...


class BaseInjector:
    injector_type = "base"
    scenario_id = ""

    def validate(self, context: FaultContext) -> list[str]:
        scenario = get_scenario(self.scenario_id)
        if scenario is None:
            return [f"scenario '{self.scenario_id}' is not in the catalogue"]
        problems: list[str] = []
        if context.trigger_type not in scenario.supported_trigger_modes:
            problems.append(
                f"scenario '{self.scenario_id}' does not support trigger "
                f"'{context.trigger_type}'"
            )
        for requirement in scenario.adapter_requirements:
            if requirement.capability not in (
                CAPABILITY_FAILURE_TRIGGER,
                CAPABILITY_DEPENDENCY_OBSERVATION,
            ):
                continue
        return problems

    def prepare(self, context: FaultContext) -> dict[str, Any]:
        return {"prepared": True}

    def wait_for_trigger(self, context: FaultContext, timeout_seconds: float) -> bool:
        if context.trigger_type == TRIGGER_CHECKPOINT:
            if context.wait_for_checkpoint is None:
                raise InjectorError(
                    "checkpoint trigger selected but no checkpoint coordinator is available"
                )
            return bool(context.wait_for_checkpoint(timeout_seconds))
        return True

    def activate(self, context: FaultContext) -> dict[str, Any]:
        return {"activated": True}

    def deactivate(self, context: FaultContext) -> dict[str, Any]:
        return {"deactivated": True}

    def status(self) -> dict[str, Any]:
        return {"injector": self.injector_type}

    def close(self) -> None:  # pragma: no cover - overridden where needed
        return None


def api_key_scoped(context: FaultContext) -> str:
    """Small helper kept for injectors that need a stable per-run tag."""
    return f"veriq-run:{context.test_run_id}"


__all__ = [
    "BaseInjector",
    "FaultContext",
    "FaultInjector",
    "InjectorError",
    "TRIGGER_AUTOMATIC",
    "TRIGGER_CHECKPOINT",
]
