"""One injector per supported failure scenario.

Each class implements exactly one mechanism and reports the facts it observed.
It never decides the verdict and never touches the database.
"""

from __future__ import annotations

import threading
from typing import Any

from app.runtime.contracts import RuntimeBackendError
from app.runtime.injectors.base import (
    BaseInjector,
    FaultContext,
    InjectorError,
    TRIGGER_CHECKPOINT,
)
from app.runtime.injectors.database_proxy import TcpFaultProxy
from app.runtime.injectors.http_proxy import (
    MODE_DELAY,
    MODE_LOST_RESPONSE,
    HttpFaultProxy,
)


class HttpProxyInjector(BaseInjector):
    """Shared implementation for delay and lost-response proxying."""

    mode = MODE_DELAY

    def __init__(self) -> None:
        self._proxy: HttpFaultProxy | None = None
        self._armed = False
        self._activated_at: float | None = None
        self._config: dict[str, Any] = {}

    def validate(self, context: FaultContext) -> list[str]:
        problems = super().validate(context)
        if not context.dependency_url:
            problems.append(
                "the HTTP fault proxy needs a dependency_url (the upstream test dependency)"
            )
        delay_ms = context.config.get("timeout_ms")
        if delay_ms is not None and (
            isinstance(delay_ms, bool) or not isinstance(delay_ms, int) or delay_ms <= 0
        ):
            problems.append("timeout_ms must be a positive integer")
        return problems

    def prepare(self, context: FaultContext) -> dict[str, Any]:
        proxy = HttpFaultProxy(
            context.dependency_url or "",
            advertised_host=context.advertised_host,
        )
        proxy.start()
        self._proxy = proxy
        self._config = dict(context.config)
        context.emit(
            "injector_prepared",
            {
                "injector": self.injector_type,
                "proxy_origin": proxy.origin,
                "mode": self.mode,
            },
        )
        return {
            "proxy_origin": proxy.origin,
            "proxy_port": proxy.port,
            "mode": self.mode,
            "upstream": context.dependency_url,
        }

    def activate(self, context: FaultContext) -> dict[str, Any]:
        if self._proxy is None:
            raise InjectorError("injector was not prepared")
        delay_ms = context.integer("timeout_ms", 2000, minimum=1, maximum=600000)
        fault_requests = context.integer("fault_requests", 1, minimum=1, maximum=10)
        self._proxy.arm(self.mode, delay_ms=delay_ms, fault_requests=fault_requests)
        self._armed = True
        self._activated_at = self._now()
        detail = {
            "mode": self.mode,
            "delay_ms": delay_ms if self.mode == MODE_DELAY else 0,
            "fault_requests": fault_requests,
            "proxy_origin": self._proxy.origin,
        }
        context.emit("fault_activated", detail)
        return detail

    def deactivate(self, context: FaultContext) -> dict[str, Any]:
        if self._proxy is None:
            return {"deactivated": False, "reason": "not prepared"}
        self._proxy.disarm()
        self._armed = False
        context.emit("fault_released", {"mode": self.mode})
        return {"deactivated": True}

    def wait_for_trigger(self, context: FaultContext, timeout_seconds: float) -> bool:
        if context.trigger_type == TRIGGER_CHECKPOINT:
            return super().wait_for_trigger(context, timeout_seconds)
        return True

    def status(self) -> dict[str, Any]:
        return {
            "injector": self.injector_type,
            "mode": self.mode,
            "armed": self._armed,
            "proxy": self._proxy.status() if self._proxy is not None else None,
            "events": self._proxy.events() if self._proxy is not None else [],
        }

    def close(self) -> None:
        if self._proxy is not None:
            self._proxy.stop()
            self._proxy = None
        self._armed = False

    @staticmethod
    def _now() -> float:
        import time

        return time.time()


class DependencyTimeoutInjector(HttpProxyInjector):
    scenario_id = "dependency_timeout"
    injector_type = "http_delay_proxy"
    mode = MODE_DELAY


class LostResponseInjector(HttpProxyInjector):
    scenario_id = "successful_operation_lost_response"
    injector_type = "http_lost_response_proxy"
    mode = MODE_LOST_RESPONSE


class DatabaseInterruptionInjector(BaseInjector):
    scenario_id = "database_connection_interruption"
    injector_type = "tcp_database_proxy"

    def __init__(self) -> None:
        self._proxy: TcpFaultProxy | None = None
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()
        self._activated_at: float | None = None

    def validate(self, context: FaultContext) -> list[str]:
        problems = super().validate(context)
        if context.database_upstream is None:
            problems.append(
                "database connection interruption needs the isolated test database's "
                "host and port"
            )
        duration = context.config.get("interruption_seconds", 3)
        if isinstance(duration, bool) or not isinstance(duration, int) or not 1 <= duration <= 300:
            problems.append("interruption_seconds must be an integer between 1 and 300")
        return problems

    def prepare(self, context: FaultContext) -> dict[str, Any]:
        if context.database_upstream is None:
            raise InjectorError("no test database upstream configured")
        host, port = context.database_upstream
        proxy = TcpFaultProxy(host, port)
        proxy.start()
        self._proxy = proxy
        context.emit(
            "injector_prepared",
            {"injector": self.injector_type, "database_proxy_port": proxy.port},
        )
        return {"database_proxy_port": proxy.port, "upstream": f"{host}:{port}"}

    def activate(self, context: FaultContext) -> dict[str, Any]:
        if self._proxy is None:
            raise InjectorError("injector was not prepared")
        duration = context.integer("interruption_seconds", 3, minimum=1, maximum=300)
        self._proxy.interrupt()
        self._activated_at = _now()
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            timer = threading.Timer(duration, self._auto_release, args=(context,))
            timer.daemon = True
            self._timer = timer
            timer.start()
        detail = {"duration_seconds": duration, "database_proxy_port": self._proxy.port}
        context.emit("fault_activated", detail)
        return detail

    def _auto_release(self, context: FaultContext) -> None:
        # Bounded by its own duration: the interruption never outlives the test.
        if self._proxy is not None and self._proxy.interrupted:
            self._proxy.restore()
            context.emit("fault_auto_released", {"reason": "duration elapsed"})

    def deactivate(self, context: FaultContext) -> dict[str, Any]:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        if self._proxy is None:
            return {"deactivated": False, "reason": "not prepared"}
        self._proxy.restore()
        context.emit("fault_released", {"injector": self.injector_type})
        return {"deactivated": True}

    def status(self) -> dict[str, Any]:
        return {
            "injector": self.injector_type,
            "proxy": self._proxy.stats() if self._proxy is not None else None,
        }

    def close(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        if self._proxy is not None:
            self._proxy.stop()
            self._proxy = None


class DuplicateDeliveryInjector(BaseInjector):
    """Mode A: the same logical job is submitted more than once.

    These are independent Celery messages carrying the same logical job id. It is
    *not* evidence of broker redelivery, and the evidence says so.
    """

    scenario_id = "duplicate_message_delivery"
    injector_type = "broker_duplicate_submission"

    def __init__(self) -> None:
        self._detail: dict[str, Any] = {}

    def validate(self, context: FaultContext) -> list[str]:
        problems = super().validate(context)
        if context.submit_duplicate is None:
            problems.append("no message submission callback is available for duplicate delivery")
        count = context.config.get("delivery_count", 2)
        if isinstance(count, bool) or not isinstance(count, int) or not 2 <= count <= 10:
            problems.append("delivery_count must be an integer between 2 and 10")
        return problems

    def activate(self, context: FaultContext) -> dict[str, Any]:
        if context.submit_duplicate is None:
            raise InjectorError("duplicate delivery requires a submission callback")
        count = context.integer("delivery_count", 2, minimum=2, maximum=10)
        task_ids = list(context.submit_duplicate(count - 1))
        self._detail = {
            "mechanism": "duplicate_logical_job_submission",
            "logical_job_id": context.operation_id,
            "additional_messages": count - 1,
            "additional_task_ids": task_ids,
            "redelivery_proven": False,
            "note": (
                "Independent submissions of one logical job; this does not prove broker "
                "redelivery."
            ),
        }
        context.emit("duplicate_messages_submitted", self._detail)
        context.emit("fault_activated", self._detail)
        return self._detail

    def wait_for_trigger(self, context: FaultContext, timeout_seconds: float) -> bool:
        if context.trigger_type == TRIGGER_CHECKPOINT:
            return super().wait_for_trigger(context, timeout_seconds)
        return True

    def status(self) -> dict[str, Any]:
        return {"injector": self.injector_type, **self._detail}


class WorkerTerminationInjector(BaseInjector):
    """Terminates the exact isolated worker through the runner supervisor."""

    scenario_id = "worker_termination"
    injector_type = "worker_termination"

    def __init__(self) -> None:
        self._detail: dict[str, Any] = {}

    def validate(self, context: FaultContext) -> list[str]:
        problems = super().validate(context)
        if context.terminate_worker is None:
            problems.append("no runner supervisor is available to terminate a worker")
        return problems

    def wait_for_trigger(self, context: FaultContext, timeout_seconds: float) -> bool:
        if context.trigger_type == TRIGGER_CHECKPOINT:
            return super().wait_for_trigger(context, timeout_seconds)
        if context.wait_for_task_running is None:
            return True
        return bool(context.wait_for_task_running(timeout_seconds))

    def activate(self, context: FaultContext) -> dict[str, Any]:
        if context.terminate_worker is None:
            raise InjectorError("worker termination requires the runner supervisor")
        grace = context.integer("termination_grace_seconds", 0, minimum=0, maximum=300)
        try:
            outcome = context.terminate_worker(f"scenario:{self.scenario_id}")
        except RuntimeBackendError as exc:
            raise InjectorError(str(exc)) from exc
        self._detail = {
            "grace_seconds": grace,
            "termination": outcome,
            "expect_redelivery": context.config.get("expect_redelivery"),
            "note": (
                "Worker loss alone does not guarantee redelivery; acknowledgement and "
                "broker configuration decide it."
            ),
        }
        context.emit("worker_termination_performed", self._detail)
        context.emit("fault_activated", self._detail)
        return self._detail

    def deactivate(self, context: FaultContext) -> dict[str, Any]:
        return {"deactivated": True, "reason": "worker termination is not reversible"}

    def status(self) -> dict[str, Any]:
        return {"injector": self.injector_type, **self._detail}


def _now() -> float:
    import time

    return time.time()


INJECTORS: dict[str, type[BaseInjector]] = {
    DependencyTimeoutInjector.scenario_id: DependencyTimeoutInjector,
    LostResponseInjector.scenario_id: LostResponseInjector,
    DatabaseInterruptionInjector.scenario_id: DatabaseInterruptionInjector,
    DuplicateDeliveryInjector.scenario_id: DuplicateDeliveryInjector,
    WorkerTerminationInjector.scenario_id: WorkerTerminationInjector,
}

INJECTOR_TYPES = {
    scenario_id: injector_class.injector_type for scenario_id, injector_class in INJECTORS.items()
}


def build_injector(scenario_id: str) -> BaseInjector:
    injector_class = INJECTORS.get(scenario_id)
    if injector_class is None:
        raise InjectorError(f"no injector is implemented for scenario '{scenario_id}'")
    return injector_class()


def supported_scenarios() -> tuple[str, ...]:
    return tuple(sorted(INJECTORS))


__all__ = [
    "DatabaseInterruptionInjector",
    "DependencyTimeoutInjector",
    "DuplicateDeliveryInjector",
    "INJECTORS",
    "INJECTOR_TYPES",
    "LostResponseInjector",
    "WorkerTerminationInjector",
    "build_injector",
    "supported_scenarios",
]
