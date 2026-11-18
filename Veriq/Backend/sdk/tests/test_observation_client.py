import uuid

import pytest

from veriq import VeriQ
from veriq.exceptions import VeriQClientClosedError

from .conftest import API_KEY, MockBackend, make_transport


def test_report_execution_posts_identity_and_defaults(backend: MockBackend):
    backend.reply(201, {"stored": True, "status": "RUNNING"})
    client = VeriQ(transport=make_transport(backend))
    execution_id = uuid.uuid4()

    response = client.report_execution(
        {
            "execution_id": str(execution_id),
            "task_name": "app.tasks.demo",
            "event_type": "TASK_STARTED",
        }
    )

    assert response["stored"] is True
    request = backend.requests[0]
    assert str(request.url).endswith("/api/v1/task-executions/events")
    assert request.headers["X-API-Key"] == API_KEY
    body = backend.json_bodies[0]
    assert body["execution_id"] == str(execution_id)
    assert uuid.UUID(body["event_id"])
    assert body["occurred_at"].endswith("+00:00")


def test_report_worker_and_task_discovery_paths(backend: MockBackend):
    backend.reply(201, {"worker_instance_id": "w1"}).reply(201, [])
    client = VeriQ(transport=make_transport(backend))

    worker = client.report_worker({"worker_instance_id": "w1", "event_type": "WORKER_STARTED"})
    discovered = client.discover_tasks(["app.tasks.demo"])

    assert worker["worker_instance_id"] == "w1"
    assert discovered == []
    assert str(backend.requests[0].url).endswith("/api/v1/workers/events")
    assert str(backend.requests[1].url).endswith("/api/v1/tasks/discovery")
    assert backend.json_bodies[1]["task_names"] == ["app.tasks.demo"]
    assert backend.json_bodies[1]["source"] == "SDK"


def test_checkpoint_outside_a_task_is_a_noop(backend: MockBackend):
    client = VeriQ(transport=make_transport(backend))
    assert client.checkpoint("payment_charged") is None
    assert backend.requests == []


def test_observation_calls_after_close_raise(backend: MockBackend):
    client = VeriQ(transport=make_transport(backend))
    client.close()
    with pytest.raises(VeriQClientClosedError):
        client.report_execution(
            {"execution_id": str(uuid.uuid4()), "task_name": "t", "event_type": "TASK_STARTED"}
        )
