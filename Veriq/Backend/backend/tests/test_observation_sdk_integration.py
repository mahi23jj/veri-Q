"""The real SDK reporting discovery/telemetry into the real FastAPI app."""

from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

veriq = pytest.importorskip("veriq")

from veriq import VeriQ, VeriQConfig  # noqa: E402
from veriq.transport.http import HTTPTransport  # noqa: E402

BACKEND_URL = "http://testserver"


def sdk_for(client: TestClient, api_key: str) -> VeriQ:
    config = VeriQConfig(BACKEND_URL, api_key, timeout=5.0)
    http_client = httpx.Client(transport=client._transport, base_url=BACKEND_URL)
    return VeriQ(transport=HTTPTransport(config, client=http_client))


def register_app(client: TestClient, name: str) -> tuple[str, str]:
    resp = client.post("/api/v1/applications", json={"name": name, "environment": "test"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"], resp.json()["api_key"]


def test_sdk_discovery_and_execution_round_trip(client: TestClient):
    app_id, api_key = register_app(client, "sdk-observation")

    with sdk_for(client, api_key) as sdk:
        discovered = sdk.discover_tasks(["app.tasks.charge_order", "app.tasks.fail_order"])
        assert len(discovered) == 2

        worker = sdk.report_worker(
            {
                "worker_instance_id": "sdk-worker-1",
                "event_type": "WORKER_STARTED",
                "hostname": "celery@host",
                "pid": 1234,
                "process_start_identity": "1234:2026-11-12T00:00:00+00:00",
                "registered_tasks": ["app.tasks.charge_order"],
                "queues": [{"name": "normal", "is_configured": True, "is_consumed": True}],
            }
        )
        assert worker["status"] == "ONLINE"

        execution_id = str(uuid.uuid4())
        identity = {
            "execution_id": execution_id,
            "celery_task_id": "celery-1",
            "task_name": "app.tasks.charge_order",
            "worker_instance_id": "sdk-worker-1",
            "worker_hostname": "celery@host",
            "pid": 1234,
            "queue_name": "normal",
        }
        assert sdk.report_execution({**identity, "event_type": "TASK_STARTED"})["status"] == "RUNNING"
        assert sdk.report_execution(
            {**identity, "event_type": "TASK_CHECKPOINT", "payload": {"checkpoint": "charged"}}
        )["stored"] is True
        assert sdk.report_execution(
            {**identity, "event_type": "TASK_SUCCEEDED"}
        )["status"] == "SUCCEEDED"

    execution = client.get(
        "/api/v1/task-executions", params={"target_app_id": app_id}
    ).json()["items"][0]
    assert execution["execution_id"] == execution_id
    assert execution["worker_instance_id"] == "sdk-worker-1"
    assert execution["experiment_run_id"] is None
    detail = client.get(f"/api/v1/task-executions/{execution['id']}").json()
    assert [event["event_type"] for event in detail["events"]] == [
        "TASK_STARTED",
        "TASK_CHECKPOINT",
        "TASK_SUCCEEDED",
    ]

    tasks = client.get("/api/v1/registered-tasks", params={"target_app_id": app_id}).json()
    assert tasks["total"] == 2
    catalog = next(t for t in tasks["items"] if t["task_name"] == "app.tasks.charge_order")
    assert catalog["execution_count"] == 1
    assert catalog["queue_names"] == ["normal"]
    assert catalog["last_outcome"] == "SUCCEEDED"

    # Disabling observation stops storage but discovery/selection remains.
    disabled = client.patch(
        f"/api/v1/registered-tasks/{catalog['id']}/observation",
        json={"status": "DISABLED"},
    )
    assert disabled.status_code == 200
    with sdk_for(client, api_key) as sdk:
        dropped = sdk.report_execution(
            {
                "execution_id": str(uuid.uuid4()),
                "task_name": "app.tasks.charge_order",
                "event_type": "TASK_STARTED",
            }
        )
    assert dropped["stored"] is False
    assert client.get("/api/v1/task-executions", params={"target_app_id": app_id}).json()[
        "total"
    ] == 1
    assert client.get("/api/v1/registered-tasks", params={"target_app_id": app_id}).json()[
        "total"
    ] == 2
