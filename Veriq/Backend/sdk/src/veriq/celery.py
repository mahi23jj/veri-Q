"""Celery integration for VeriQ.

Usage::

    from veriq import VeriQ
    from veriq.celery import integrate

    veriq = VeriQ(api_url="http://localhost:8000", api_key="vq_...")
    integrate(celery_app, veriq)

The integration connects Celery signal handlers and reports ordinary task
lifecycle telemetry to the VeriQ backend. It never changes task return values,
exceptions, retries or worker behaviour, and reporting failures are logged and
swallowed so monitoring cannot break the application.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
import uuid
import weakref
from datetime import datetime, timezone
from typing import Any

from veriq.client import VeriQ
from veriq.context import (
    ExecutionContext,
    clear_execution,
    current_execution,
    set_execution,
)

__all__ = ["integrate", "CeleryIntegration", "process_start_identity"]

logger = logging.getLogger("veriq.celery")

# Captured once per Python process. Used to build a process-start identity that
# distinguishes two processes that happen to reuse the same PID.
_PROCESS_STARTED_AT = datetime.now(timezone.utc)
_PROCESS_PID = os.getpid()

# One integration per Celery application. ``WeakKeyDictionary`` avoids keeping
# an application (and its signal handlers) alive forever.
_INTEGRATIONS: "weakref.WeakKeyDictionary[Any, CeleryIntegration]" = weakref.WeakKeyDictionary()
_REGISTRY_LOCK = threading.Lock()

# Celery's own built-in task names (celery.chord, celery.backend_cleanup, ...)
# are not application tasks and are not useful in the catalog.
_BUILTIN_TASK_PREFIX = "celery."
_DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 30.0


def process_start_identity(pid: int | None = None) -> str:
    """Return an identifier for this process lifetime (PID is not enough)."""
    return f"{pid if pid is not None else _PROCESS_PID}:{_PROCESS_STARTED_AT.isoformat()}"


def _parse_uuid(value: Any) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (AttributeError, TypeError, ValueError):
        return None


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string(value: Any, limit: int = 500) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] if text else None


class CeleryIntegration:
    """Holds the signal handlers and identity for one Celery application."""

    def __init__(
        self,
        celery_app: Any,
        veriq: VeriQ,
        *,
        worker_hostname: str | None = None,
        heartbeat_interval: float = _DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
        discover_on_integrate: bool = True,
    ) -> None:
        if veriq is None:
            raise ValueError("a VeriQ client is required")
        self._app = celery_app
        self._veriq = veriq
        # One uuid per (application, process lifetime). Not a hostname and not
        # a PID: both can be reused while a worker instance is still distinct.
        self.worker_instance_id = str(uuid.uuid4())
        self._worker_hostname = worker_hostname
        self.heartbeat_interval = heartbeat_interval
        self._last_heartbeat_at = 0.0
        self._uid = f"veriq:{id(celery_app)}:{self.worker_instance_id}"
        self._discover_on_integrate = discover_on_integrate
        self._connected = False
        self._handlers: tuple[Any, ...] = ()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    def connect(self) -> "CeleryIntegration":
        from celery.signals import (
            heartbeat_sent,
            task_failure,
            task_postrun,
            task_prerun,
            task_retry,
            worker_ready,
            worker_shutdown,
        )

        if self._connected:
            return self
        self._handlers = (
            (task_prerun, self._on_task_prerun),
            (task_postrun, self._on_task_postrun),
            (task_failure, self._on_task_failure),
            (task_retry, self._on_task_retry),
            (worker_ready, self._on_worker_ready),
            (heartbeat_sent, self._on_heartbeat),
            (worker_shutdown, self._on_worker_shutdown),
        )
        for signal, handler in self._handlers:
            signal.connect(
                handler,
                weak=False,
                dispatch_uid=f"{self._uid}:{signal.name}",
            )
        self._connected = True
        return self

    def disconnect(self) -> None:
        """Detach every signal handler (useful for tests and app teardown)."""
        if not self._connected:
            return
        for signal, handler in getattr(self, "_handlers", ()):
            signal.disconnect(dispatch_uid=f"{self._uid}:{signal.name}")
        self._connected = False
        with _REGISTRY_LOCK:
            if _INTEGRATIONS.get(self._app) is self:
                del _INTEGRATIONS[self._app]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _is_our_task(self, sender: Any) -> bool:
        return getattr(sender, "app", None) is self._app

    def _is_our_worker(self, sender: Any) -> bool:
        app = getattr(sender, "app", None)
        # Some Celery versions omit ``app`` on the WorkController; the
        # application-level integration still owns the signal in that case.
        return app is None or app is self._app

    def _task_names(self) -> list[str]:
        try:
            names = [
                name
                for name in self._app.tasks.keys()
                if isinstance(name, str) and not name.startswith(_BUILTIN_TASK_PREFIX)
            ]
        except Exception:  # pragma: no cover - defensive
            return []
        return sorted(names)

    def _worker_hostname_for(self, sender: Any = None, request: Any = None) -> str:
        for candidate in (
            getattr(sender, "hostname", None),
            getattr(request, "hostname", None),
            self._worker_hostname,
            socket.gethostname(),
        ):
            if candidate:
                return str(candidate)
        return "unknown"

    def _queue_name(self, task: Any) -> str | None:
        request = getattr(task, "request", None)
        delivery_info = _as_dict(getattr(request, "delivery_info", None))
        queue = delivery_info.get("routing_key") or delivery_info.get("queue")
        if queue:
            return str(queue)
        return getattr(self._app.conf, "task_default_queue", None)

    def _experiment_context(self, task: Any) -> tuple[uuid.UUID | None, uuid.UUID | None]:
        request = getattr(task, "request", None)
        candidates: list[dict[str, Any]] = []
        headers = getattr(request, "headers", None)
        if isinstance(headers, dict):
            candidates.append(headers)
        try:
            request_headers = request.get("headers")
        except Exception:
            request_headers = None
        if isinstance(request_headers, dict):
            candidates.append(request_headers)
        if isinstance(request, dict):
            candidates.append(request)

        run_id = operation_id = None
        for mapping in candidates:
            run_id = run_id or _parse_uuid(mapping.get("veriq_run_id"))
            operation_id = operation_id or _parse_uuid(mapping.get("veriq_operation_id"))
        return run_id, operation_id

    def _queues(self, sender: Any = None) -> list[dict[str, Any]]:
        """Describe configured queues and, when discoverable, consumed queues."""
        configured: dict[str, Any] = {}
        try:
            for queue in self._app.amqp.queues.values():
                name = getattr(queue, "name", None)
                if name:
                    configured[str(name)] = queue
        except Exception:  # pragma: no cover - amqp may not be initialised
            configured = {}

        consumed: set[str] = set()
        consumer = getattr(sender, "consumer", None)
        consumer_queues = getattr(consumer, "queues", None)
        if isinstance(consumer_queues, dict):
            consumed = {str(name) for name in consumer_queues}
        elif isinstance(consumer_queues, (list, tuple, set)):
            consumed = {str(name) for name in consumer_queues}

        reports: list[dict[str, Any]] = []
        for name, queue in configured.items():
            exchange = getattr(queue, "exchange", None)
            reports.append(
                {
                    "name": name,
                    "exchange": getattr(exchange, "name", None),
                    "routing_key": getattr(queue, "routing_key", None),
                    "is_configured": True,
                    "is_consumed": name in consumed,
                }
            )
        for name in sorted(consumed - set(configured)):
            reports.append(
                {
                    "name": name,
                    "exchange": None,
                    "routing_key": None,
                    "is_configured": False,
                    "is_consumed": True,
                }
            )
        return reports

    # ------------------------------------------------------------------
    # Reporting (failure must never break a task)
    # ------------------------------------------------------------------
    def _safe(self, action: str, fn, *args, **kwargs) -> Any:
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # transport/config errors included
            logger.warning("VeriQ %s report failed (ignored): %s", action, exc)
            return None

    def _report_task_event(
        self,
        context: ExecutionContext,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        started_at: datetime | None = None,
    ) -> None:
        body = context.identity_fields()
        body["event_type"] = event_type
        body["occurred_at"] = datetime.now(timezone.utc).isoformat()
        body["event_id"] = str(uuid.uuid4())
        if started_at is not None:
            body["started_at"] = started_at.isoformat()
        if payload is not None:
            body["payload"] = payload
        self._safe("execution", self._veriq.report_execution, body)

    def _report_worker(self, event_type: str, sender: Any = None) -> None:
        hostname = self._worker_hostname_for(sender)
        payload = {
            "worker_instance_id": self.worker_instance_id,
            "event_type": event_type,
            "hostname": hostname,
            "worker_hostname": hostname,
            "pid": os.getpid(),
            "process_start_identity": process_start_identity(),
            "registered_tasks": self._task_names(),
            "queues": self._queues(sender),
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        }
        self._safe("worker", self._veriq.report_worker, payload)

    def discover_tasks(self) -> None:
        names = self._task_names()
        if names:
            self._safe("discovery", self._veriq.discover_tasks, names)

    # ------------------------------------------------------------------
    # Task signals
    # ------------------------------------------------------------------
    def _on_task_prerun(self, sender=None, task_id=None, task=None, **kwargs) -> None:
        # ``task`` is the Task instance; ``sender`` is the same object in
        # Celery 5.x but accept either.
        task = task if task is not None else sender
        if task is None or not self._is_our_task(task):
            return
        request = getattr(task, "request", None)
        if bool(getattr(request, "is_eager", False)) or bool(
            getattr(self._app.conf, "task_always_eager", False)
        ):
            # Eager calls are in-process test invocations, not worker
            # executions; do not invent a worker identity for them.
            return

        now = datetime.now(timezone.utc)
        run_id, operation_id = self._experiment_context(task)
        context = ExecutionContext(
            execution_id=uuid.uuid4(),
            task_id=str(task_id) if task_id is not None else None,
            task_name=getattr(task, "name", None) or "unknown",
            started_at=now,
            worker_instance_id=self.worker_instance_id,
            worker_hostname=self._worker_hostname_for(request=request),
            pid=os.getpid(),
            process_start_identity=process_start_identity(),
            queue_name=self._queue_name(task),
            veriq_run_id=run_id,
            veriq_operation_id=operation_id,
        )
        set_execution(context)
        self._report_task_event(context, "TASK_STARTED", started_at=now)

    def _on_task_postrun(self, sender=None, task_id=None, task=None, **kwargs) -> None:
        task = task if task is not None else sender
        context = current_execution()
        if context is None:
            return
        if task_id is not None and context.task_id != str(task_id):
            return
        if task is not None and not self._is_our_task(task):
            return

        try:
            state = kwargs.get("state")
            if not context.terminal_sent and state not in ("FAILURE", "RETRY"):
                self._report_task_event(
                    context, "TASK_SUCCEEDED", {"state": str(state) if state else "SUCCESS"}
                )
        finally:
            clear_execution(context)

    def _on_task_failure(
        self,
        sender=None,
        task_id=None,
        exception=None,
        einfo=None,
        **kwargs,
    ) -> None:
        task = sender
        context = current_execution()
        if context is None:
            return
        if task_id is not None and context.task_id != str(task_id):
            return
        if task is not None and not self._is_our_task(task):
            return
        self._report_task_event(
            context,
            "TASK_FAILED",
            {
                "exception_type": type(exception).__name__ if exception is not None else None,
                "exception_message": _string(exception),
            },
        )
        context.terminal_sent = True

    def _on_task_retry(self, request=None, reason=None, **kwargs) -> None:
        context = current_execution()
        if context is None:
            return
        request_id = getattr(request, "id", None)
        if request_id is not None and context.task_id != str(request_id):
            # A retry from another task in the same process must not consume
            # this execution's context.
            return
        self._report_task_event(
            context, "TASK_RETRY_REQUESTED", {"reason": _string(reason)}
        )
        context.terminal_sent = True

    # ------------------------------------------------------------------
    # Worker signals
    # ------------------------------------------------------------------
    def _on_worker_ready(self, sender=None, **kwargs) -> None:
        if not self._is_our_worker(sender):
            return
        hostname = getattr(sender, "hostname", None)
        if hostname:
            self._worker_hostname = str(hostname)
        self._report_worker("WORKER_STARTED", sender)
        self._last_heartbeat_at = time.monotonic()

    def _on_heartbeat(self, sender=None, **kwargs) -> None:
        if not self._is_our_worker(sender):
            return
        now = time.monotonic()
        if self.heartbeat_interval > 0 and now - self._last_heartbeat_at < self.heartbeat_interval:
            return
        self._last_heartbeat_at = now
        self._report_worker("WORKER_HEARTBEAT", sender)

    def _on_worker_shutdown(self, sender=None, **kwargs) -> None:
        if not self._is_our_worker(sender):
            return
        self._report_worker("WORKER_SHUTTING_DOWN", sender)


def integrate(
    celery_app: Any,
    veriq: VeriQ,
    *,
    worker_hostname: str | None = None,
    heartbeat_interval: float = _DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    discover_on_integrate: bool = True,
) -> CeleryIntegration:
    """Wire a VeriQ client into a Celery application exactly once.

    Calling ``integrate`` again for the same application returns the existing
    integration instead of registering duplicate signal handlers.
    """
    with _REGISTRY_LOCK:
        existing = _INTEGRATIONS.get(celery_app)
        if existing is not None:
            return existing
        integration = CeleryIntegration(
            celery_app,
            veriq,
            worker_hostname=worker_hostname,
            heartbeat_interval=heartbeat_interval,
            discover_on_integrate=discover_on_integrate,
        ).connect()
        _INTEGRATIONS[celery_app] = integration

    if discover_on_integrate:
        # Best effort: an unreachable backend or a not-yet-configured client
        # must not prevent the application from starting.
        integration.discover_tasks()
    return integration
