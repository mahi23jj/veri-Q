"""Celery signal integration unit tests (real Celery app, mocked transport)."""

from __future__ import annotations

import os
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from celery import Celery
from celery.signals import (
    heartbeat_sent,
    task_failure,
    task_postrun,
    task_prerun,
    task_retry,
    worker_ready,
    worker_shutdown,
)
from kombu import Queue

from veriq import VeriQ
from veriq.celery import integrate, process_start_identity
from veriq.context import (
    ExecutionContext,
    clear_execution,
    current_execution,
    set_execution,
)

from .conftest import MockBackend, make_transport

_app_counter = 0


def make_app(label: str) -> Celery:
    global _app_counter
    _app_counter += 1
    app = Celery(f"veriq-unit-{label}-{_app_counter}", broker="memory://")
    app.conf.update(
        task_always_eager=False,
        task_default_queue="normal",
        task_queues=(Queue("normal"), Queue("veriq.test")),
    )

    @app.task(name=f"{label}.demo")
    def demo(value: int = 1) -> int:
        return value

    return app


def task_of(app: Celery, name: str):
    return app.tasks[name]


@contextmanager
def pushed_request(task, *, task_id: str, headers=None, delivery_info=None, is_eager=False):
    task.push_request(
        task_id=task_id,
        headers=headers or {},
        delivery_info=delivery_info or {"routing_key": "normal"},
        hostname="celery@testworker",
        is_eager=is_eager,
    )
    try:
        yield
    finally:
        task.pop_request()


class WorkerSender:
    """Hashable stand-in for Celery's WorkController (signals index by sender)."""

    def __init__(self, app, hostname="celery@worker-1", consumed=("normal",)):
        self.app = app
        self.hostname = hostname
        self.consumer = SimpleNamespace(queues={name: object() for name in consumed})


class IntegrationHarness:
    def __init__(self) -> None:
        self.created = []

    def make(self, app, backend, **kwargs):
        client = VeriQ(transport=make_transport(backend))
        integration = integrate(
            app,
            client,
            discover_on_integrate=kwargs.pop("discover_on_integrate", False),
            **kwargs,
        )
        self.created.append(integration)
        return client, integration

    def close(self) -> None:
        for integration in self.created:
            integration.disconnect()


@pytest.fixture()
def integrations():
    harness = IntegrationHarness()
    yield harness
    harness.close()


def send_prerun(task, task_id: str) -> None:
    task_prerun.send(sender=task, task_id=task_id, task=task, args=(), kwargs={})


def send_postrun(task, task_id: str, state: str = "SUCCESS") -> None:
    task_postrun.send(
        sender=task,
        task_id=task_id,
        task=task,
        args=(),
        kwargs={},
        retval=None,
        state=state,
    )


def reported_event_types(backend: MockBackend) -> list[str]:
    return [body["event_type"] for body in backend.json_bodies]


def test_successful_task_reports_lifecycle_and_checkpoint(backend: MockBackend, integrations):
    app = make_app("success")
    task = task_of(app, "success.demo")
    client, _integration = integrations.make(app, backend)
    for _ in range(3):
        backend.reply(201, {"stored": True})

    with pushed_request(task, task_id="celery-task-1"):
        send_prerun(task, "celery-task-1")
        assert current_execution() is not None
        checkpoint = client.checkpoint("payment_charged")
        assert checkpoint == {"stored": True}
        send_postrun(task, "celery-task-1")

    assert current_execution() is None
    bodies = backend.json_bodies
    assert [b["event_type"] for b in bodies] == [
        "TASK_STARTED",
        "TASK_CHECKPOINT",
        "TASK_SUCCEEDED",
    ]
    execution_ids = {b["execution_id"] for b in bodies}
    assert len(execution_ids) == 1
    started = bodies[0]
    assert started["celery_task_id"] == "celery-task-1"
    assert started["task_name"] == "success.demo"
    assert started["pid"] == os.getpid()
    assert started["process_start_identity"].startswith(f"{os.getpid()}:")
    assert started["queue_name"] == "normal"
    assert started["worker_instance_id"]
    assert started["veriq_run_id"] is None
    assert started["veriq_operation_id"] is None
    assert bodies[1]["payload"] == {"checkpoint": "payment_charged"}


def test_failed_task_reports_one_terminal_event(backend: MockBackend, integrations):
    app = make_app("failure")
    task = task_of(app, "failure.demo")
    integrations.make(app, backend)
    backend.reply(201, {"stored": True}).reply(201, {"stored": True})

    with pushed_request(task, task_id="celery-task-fail"):
        send_prerun(task, "celery-task-fail")
        task_failure.send(
            sender=task,
            task_id="celery-task-fail",
            exception=ValueError("boom"),
            traceback=None,
            einfo=None,
            args=(),
            kwargs={},
        )
        # Celery also fires task_postrun with state FAILURE; it must not add a
        # duplicate success event.
        send_postrun(task, "celery-task-fail", state="FAILURE")

    assert reported_event_types(backend) == ["TASK_STARTED", "TASK_FAILED"]
    failed = backend.json_bodies[1]
    assert failed["payload"]["exception_type"] == "ValueError"
    assert failed["payload"]["exception_message"] == "boom"


def test_retry_request_is_terminal_and_preserves_identity(backend: MockBackend, integrations):
    app = make_app("retry")
    task = task_of(app, "retry.demo")
    integrations.make(app, backend)
    backend.reply(201, {"stored": True}).reply(201, {"stored": True})

    with pushed_request(task, task_id="celery-task-retry"):
        send_prerun(task, "celery-task-retry")
        task_retry.send(
            sender=None,
            request=SimpleNamespace(id="celery-task-retry"),
            reason=RuntimeError("temporary"),
            einfo=None,
        )
        send_postrun(task, "celery-task-retry", state="RETRY")

    assert reported_event_types(backend) == ["TASK_STARTED", "TASK_RETRY_REQUESTED"]
    assert backend.json_bodies[0]["execution_id"] == backend.json_bodies[1]["execution_id"]
    assert backend.json_bodies[1]["payload"]["reason"] == "temporary"


def test_every_attempt_gets_a_fresh_execution_id(backend: MockBackend, integrations):
    app = make_app("attempts")
    task = task_of(app, "attempts.demo")
    integrations.make(app, backend)
    for _ in range(4):
        backend.reply(201, {"stored": True})

    for _attempt in range(2):
        with pushed_request(task, task_id="same-celery-task-id"):
            send_prerun(task, "same-celery-task-id")
            send_postrun(task, "same-celery-task-id")

    bodies = backend.json_bodies
    assert [b["event_type"] for b in bodies] == [
        "TASK_STARTED",
        "TASK_SUCCEEDED",
        "TASK_STARTED",
        "TASK_SUCCEEDED",
    ]
    assert bodies[0]["execution_id"] != bodies[2]["execution_id"]
    assert {b["celery_task_id"] for b in bodies} == {"same-celery-task-id"}


def test_missing_and_present_experiment_context(backend: MockBackend, integrations):
    app = make_app("experiment")
    task = task_of(app, "experiment.demo")
    integrations.make(app, backend)
    backend.reply(201, {"stored": True}).reply(201, {"stored": True}).reply(201, {"stored": True})

    with pushed_request(task, task_id="plain"):
        send_prerun(task, "plain")
        send_postrun(task, "plain")

    run_id = uuid.uuid4()
    operation_id = uuid.uuid4()
    with pushed_request(
        task,
        task_id="linked",
        headers={
            "veriq_run_id": str(run_id),
            "veriq_operation_id": str(operation_id),
        },
    ):
        send_prerun(task, "linked")
        assert current_execution().veriq_run_id == run_id
        send_postrun(task, "linked")

    assert backend.json_bodies[0]["veriq_run_id"] is None
    assert backend.json_bodies[2]["veriq_run_id"] == str(run_id)
    assert backend.json_bodies[2]["veriq_operation_id"] == str(operation_id)


def test_integrate_registers_handlers_once_per_application(backend: MockBackend, integrations):
    app = make_app("once")
    first_client, first = integrations.make(app, backend)
    second = integrate(app, first_client, discover_on_integrate=False)
    assert second is first

    task = task_of(app, "once.demo")
    backend.reply(201, {"stored": True}).reply(201, {"stored": True})
    with pushed_request(task, task_id="once-task"):
        send_prerun(task, "once-task")
        send_postrun(task, "once-task")

    # Exactly one start and one success -> no duplicate handler fired.
    assert reported_event_types(backend) == ["TASK_STARTED", "TASK_SUCCEEDED"]


def test_multiple_celery_applications_do_not_interfere(integrations):
    backend_a = MockBackend()
    backend_b = MockBackend()
    app_a = make_app("app-a")
    app_b = make_app("app-b")
    task_a = task_of(app_a, "app-a.demo")
    task_b = task_of(app_b, "app-b.demo")
    integrations.make(app_a, backend_a)
    integrations.make(app_b, backend_b)
    backend_a.reply(201, {"stored": True}).reply(201, {"stored": True})
    backend_b.reply(201, {"stored": True}).reply(201, {"stored": True})

    with pushed_request(task_a, task_id="a-task"):
        send_prerun(task_a, "a-task")
        send_postrun(task_a, "a-task")

    assert reported_event_types(backend_a) == ["TASK_STARTED", "TASK_SUCCEEDED"]
    assert backend_b.requests == []
    assert backend_a.json_bodies[0]["task_name"] == "app-a.demo"

    with pushed_request(task_b, task_id="b-task"):
        send_prerun(task_b, "b-task")
        send_postrun(task_b, "b-task")

    assert reported_event_types(backend_b) == ["TASK_STARTED", "TASK_SUCCEEDED"]
    assert len(backend_a.requests) == 2


def test_eager_execution_is_not_treated_as_a_worker_execution(backend: MockBackend, integrations):
    app = make_app("eager")
    task = task_of(app, "eager.demo")
    integrations.make(app, backend)

    with pushed_request(task, task_id="eager-task", is_eager=True):
        send_prerun(task, "eager-task")
        assert current_execution() is None

    assert backend.requests == []


def test_transport_failures_do_not_break_task_execution(backend: MockBackend, integrations):
    app = make_app("resilient")
    task = task_of(app, "resilient.demo")
    integrations.make(app, backend)
    backend.raise_error(httpx.ConnectError("backend down")).raise_error(
        httpx.ConnectError("backend down")
    )

    with pushed_request(task, task_id="resilient-task"):
        send_prerun(task, "resilient-task")
        assert current_execution() is not None
        send_postrun(task, "resilient-task")

    assert current_execution() is None


def test_task_discovery_excludes_celery_builtins(backend: MockBackend, integrations):
    app = make_app("discovery")
    backend.reply(201, [])
    integrations.make(app, backend, discover_on_integrate=True)

    assert len(backend.requests) == 1
    body = backend.json_bodies[0]
    assert "discovery.demo" in body["task_names"]
    assert all(not name.startswith("celery.") for name in body["task_names"])


def test_worker_startup_heartbeat_shutdown_and_queues(backend: MockBackend, integrations):
    app = make_app("worker")
    _client, integration = integrations.make(app, backend)
    integration.heartbeat_interval = 0
    backend.reply(201, {}).reply(201, {}).reply(201, {})

    sender = WorkerSender(app)
    worker_ready.send(sender=sender)
    heartbeat_sent.send(sender=sender)
    integration.heartbeat_interval = 3600
    heartbeat_sent.send(sender=sender)  # throttled, no request
    worker_shutdown.send(sender=sender)

    bodies = backend.json_bodies
    assert [b["event_type"] for b in bodies] == [
        "WORKER_STARTED",
        "WORKER_HEARTBEAT",
        "WORKER_SHUTTING_DOWN",
    ]
    started = bodies[0]
    assert started["hostname"] == "celery@worker-1"
    assert started["pid"] == os.getpid()
    assert started["process_start_identity"] == process_start_identity()
    assert started["worker_instance_id"] == integration.worker_instance_id
    queue_names = {q["name"] for q in started["queues"]}
    assert {"normal", "veriq.test"} <= queue_names
    normal = next(q for q in started["queues"] if q["name"] == "normal")
    assert normal["is_consumed"] is True
    assert "worker.demo" in started["registered_tasks"]


def test_worker_instance_ids_are_per_application(integrations):
    backend_a = MockBackend()
    backend_b = MockBackend()
    _ca, integration_a = integrations.make(make_app("instance-a"), backend_a)
    _cb, integration_b = integrations.make(make_app("instance-b"), backend_b)
    assert integration_a.worker_instance_id != integration_b.worker_instance_id


def test_real_celery_worker_reports_success_and_failure(backend: MockBackend, integrations):
    """End-to-end signal test with a real in-process Celery worker."""
    from celery.contrib.testing.worker import start_worker

    app = Celery("veriq-real-worker", broker="memory://", backend="cache+memory://")
    app.conf.update(
        task_always_eager=False,
        task_default_queue="normal",
        worker_hijack_root_logger=False,
    )

    @app.task(name="real.success")
    def succeeds(value: int) -> int:
        return value + 1

    @app.task(name="real.failure")
    def fails() -> None:
        raise ValueError("real worker failure")

    integrations.make(app, backend)
    for _ in range(8):
        backend.reply(201, {"stored": True})

    with start_worker(app, perform_ping_check=False):
        assert succeeds.apply_async((1,)).get(timeout=15) == 2
        result = fails.apply_async()
        assert isinstance(result.get(timeout=15, propagate=False), ValueError)

    execution_events = [
        body
        for body in backend.json_bodies
        if body.get("event_type", "").startswith("TASK_")
    ]
    assert [body["event_type"] for body in execution_events] == [
        "TASK_STARTED",
        "TASK_SUCCEEDED",
        "TASK_STARTED",
        "TASK_FAILED",
    ]
    assert len({body["execution_id"] for body in execution_events}) == 2
    assert all(body["celery_task_id"] for body in execution_events)


def test_concurrent_execution_contexts_are_isolated():
    barrier = threading.Barrier(2)
    seen: dict[str, uuid.UUID] = {}

    def run(label: str) -> None:
        context = ExecutionContext(
            execution_id=uuid.uuid4(),
            task_id=f"task-{label}",
            task_name="concurrent.demo",
            started_at=datetime.now(timezone.utc),
            worker_instance_id="worker-1",
            worker_hostname="celery@host",
            pid=os.getpid(),
            process_start_identity=process_start_identity(),
        )
        set_execution(context)
        try:
            barrier.wait(timeout=5)
            time.sleep(0.01)
            seen[label] = current_execution().execution_id
        finally:
            clear_execution(context)

    threads = [threading.Thread(target=run, args=(label,)) for label in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert set(seen) == {"a", "b"}
    assert seen["a"] != seen["b"]
    assert current_execution() is None
