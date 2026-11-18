"""Discovery + ordinary execution telemetry (no experiment required)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Worker


def register_app(client: TestClient, name: str) -> tuple[str, str]:
    resp = client.post("/api/v1/applications", json={"name": name, "environment": "test"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"], resp.json()["api_key"]


def auth(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key}


def execution_body(
    *,
    execution_id: uuid.UUID | None = None,
    event_type: str = "TASK_STARTED",
    task_name: str = "app.tasks.charge_order",
    celery_task_id: str | None = None,
    **overrides,
) -> dict:
    body = {
        "execution_id": str(execution_id or uuid.uuid4()),
        "celery_task_id": celery_task_id or str(uuid.uuid4()),
        "task_name": task_name,
        "worker_instance_id": "worker-instance-1",
        "worker_hostname": "celery@host",
        "pid": 4242,
        "process_start_identity": "4242:2026-11-12T00:00:00+00:00",
        "queue_name": "normal",
        "event_type": event_type,
        "event_id": str(uuid.uuid4()),
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    }
    body.update(overrides)
    return body


def worker_body(event_type: str = "WORKER_STARTED", **overrides) -> dict:
    body = {
        "worker_instance_id": "worker-instance-1",
        "event_type": event_type,
        "hostname": "celery@host",
        "worker_hostname": "celery@host",
        "pid": 4242,
        "process_start_identity": "4242:2026-11-12T00:00:00+00:00",
        "registered_tasks": ["app.tasks.charge_order", "app.tasks.fail_order"],
        "queues": [
            {
                "name": "normal",
                "exchange": "normal",
                "routing_key": "normal",
                "is_configured": True,
                "is_consumed": True,
            },
            {
                "name": "veriq.test",
                "exchange": "veriq.test",
                "routing_key": "veriq.test",
                "is_configured": True,
                "is_consumed": True,
            },
        ],
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    }
    body.update(overrides)
    return body


def test_worker_discovery_heartbeat_and_shutdown_are_idempotent(client: TestClient):
    app_id, key = register_app(client, "discovery-app")

    started = client.post("/api/v1/workers/events", json=worker_body(), headers=auth(key))
    assert started.status_code == 201, started.text
    worker = started.json()
    assert worker["status"] == "ONLINE"
    assert worker["pid"] == 4242
    assert worker["process_start_identity"].startswith("4242:")
    assert {q["queue_name"] for q in worker["queues"]} == {"normal", "veriq.test"}

    # Registered task discovery is independent of execution.
    tasks = client.get("/api/v1/registered-tasks", params={"target_app_id": app_id}).json()
    assert tasks["total"] == 2
    assert all(t["status"] == "DISCOVERED" for t in tasks["items"])

    first_seen = worker["last_seen_at"]
    heartbeat = client.post(
        "/api/v1/workers/events", json=worker_body("WORKER_HEARTBEAT"), headers=auth(key)
    )
    assert heartbeat.status_code == 201
    assert heartbeat.json()["id"] == worker["id"]
    assert heartbeat.json()["last_seen_at"] >= first_seen

    # No duplicate worker or task rows after a repeated report.
    workers = client.get("/api/v1/workers", params={"target_app_id": app_id}).json()
    assert workers["total"] == 1
    assert len(workers["items"][0]["queues"]) == 2
    assert client.get("/api/v1/registered-tasks", params={"target_app_id": app_id}).json()["total"] == 2

    shutdown = client.post(
        "/api/v1/workers/events", json=worker_body("WORKER_SHUTTING_DOWN"), headers=auth(key)
    )
    assert shutdown.status_code == 201
    assert shutdown.json()["status"] == "OFFLINE"
    # Historical worker records are retained.
    assert client.get("/api/v1/workers", params={"target_app_id": app_id}).json()["total"] == 1


def test_stale_worker_is_reported_offline(client: TestClient, db_session: Session):
    app_id, key = register_app(client, "stale-app")
    worker = client.post("/api/v1/workers/events", json=worker_body(), headers=auth(key)).json()

    stored = db_session.get(Worker, uuid.UUID(worker["id"]))
    stored.last_seen_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db_session.commit()

    fetched = client.get(f"/api/v1/workers/{worker['id']}").json()
    assert fetched["status"] == "OFFLINE"
    assert app_id


def test_execution_telemetry_without_experiment(client: TestClient):
    app_id, key = register_app(client, "telemetry-app")
    execution_id = uuid.uuid4()

    started = client.post(
        "/api/v1/task-executions/events",
        json=execution_body(execution_id=execution_id),
        headers=auth(key),
    )
    assert started.status_code == 201, started.text
    assert started.json()["stored"] is True
    assert started.json()["status"] == "RUNNING"

    finished = client.post(
        "/api/v1/task-executions/events",
        json=execution_body(execution_id=execution_id, event_type="TASK_SUCCEEDED"),
        headers=auth(key),
    )
    assert finished.status_code == 201
    assert finished.json()["status"] == "SUCCEEDED"

    listing = client.get("/api/v1/task-executions", params={"target_app_id": app_id}).json()
    assert listing["total"] == 1
    execution = listing["items"][0]
    assert execution["execution_id"] == str(execution_id)
    assert execution["experiment_run_id"] is None
    assert execution["worker_instance_id"] == "worker-instance-1"
    assert execution["queue_name"] == "normal"
    assert execution["duration_ms"] is not None and execution["duration_ms"] >= 0

    detail = client.get(f"/api/v1/task-executions/{execution['id']}").json()
    assert [e["event_type"] for e in detail["events"]] == ["TASK_STARTED", "TASK_SUCCEEDED"]

    catalog = client.get(
        "/api/v1/registered-tasks", params={"target_app_id": app_id}
    ).json()["items"]
    assert len(catalog) == 1
    assert catalog[0]["execution_count"] == 1
    assert catalog[0]["last_outcome"] == "SUCCEEDED"
    assert catalog[0]["queue_names"] == ["normal"]


def test_same_celery_task_id_can_have_multiple_executions(client: TestClient):
    app_id, key = register_app(client, "attempts-app")
    celery_task_id = "celery-task-123"
    execution_ids = [uuid.uuid4(), uuid.uuid4()]

    for execution_id in execution_ids:
        client.post(
            "/api/v1/task-executions/events",
            json=execution_body(execution_id=execution_id, celery_task_id=celery_task_id),
            headers=auth(key),
        )
        client.post(
            "/api/v1/task-executions/events",
            json=execution_body(
                execution_id=execution_id,
                celery_task_id=celery_task_id,
                event_type="TASK_SUCCEEDED",
            ),
            headers=auth(key),
        )

    listing = client.get(
        "/api/v1/task-executions",
        params={"target_app_id": app_id, "celery_task_id": celery_task_id},
    ).json()
    assert listing["total"] == 2
    assert {item["execution_id"] for item in listing["items"]} == {str(e) for e in execution_ids}
    assert len({item["celery_task_id"] for item in listing["items"]}) == 1


def test_duplicate_client_event_id_is_idempotent(client: TestClient):
    app_id, key = register_app(client, "dedupe-app")
    body = execution_body()

    first = client.post("/api/v1/task-executions/events", json=body, headers=auth(key))
    second = client.post("/api/v1/task-executions/events", json=body, headers=auth(key))
    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["duplicate"] is True

    listing = client.get("/api/v1/task-executions", params={"target_app_id": app_id}).json()
    assert listing["total"] == 1
    detail = client.get(f"/api/v1/task-executions/{listing['items'][0]['id']}").json()
    assert len(detail["events"]) == 1


def test_disabled_observation_drops_telemetry_but_keeps_discovery(client: TestClient):
    app_id, key = register_app(client, "selection-app")
    client.post(
        "/api/v1/tasks/discovery",
        json={"task_names": ["app.tasks.charge_order"]},
        headers=auth(key),
    )
    task = client.get("/api/v1/registered-tasks", params={"target_app_id": app_id}).json()[
        "items"
    ][0]

    disabled = client.patch(
        f"/api/v1/registered-tasks/{task['id']}/observation", json={"status": "DISABLED"}
    )
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "DISABLED"

    dropped = client.post(
        "/api/v1/task-executions/events", json=execution_body(), headers=auth(key)
    )
    assert dropped.status_code == 201
    assert dropped.json()["stored"] is False
    assert "disabled" in dropped.json()["reason"]
    assert (
        client.get("/api/v1/task-executions", params={"target_app_id": app_id}).json()["total"]
        == 0
    )

    # Discovery continues while telemetry is disabled.
    tasks = client.get("/api/v1/registered-tasks", params={"target_app_id": app_id}).json()
    assert tasks["total"] == 1
    assert tasks["items"][0]["status"] == "DISABLED"

    enabled = client.patch(
        f"/api/v1/registered-tasks/{task['id']}/observation", json={"status": "OBSERVING"}
    )
    assert enabled.json()["status"] == "OBSERVING"
    stored = client.post(
        "/api/v1/task-executions/events", json=execution_body(), headers=auth(key)
    )
    assert stored.json()["stored"] is True


def test_observation_selection_is_scoped_to_the_application(client: TestClient):
    app_a, key_a = register_app(client, "scope-a")
    app_b, _ = register_app(client, "scope-b")
    client.post(
        "/api/v1/tasks/discovery", json={"task_names": ["app.tasks.a_only"]}, headers=auth(key_a)
    )

    assert client.get("/api/v1/registered-tasks", params={"target_app_id": app_a}).json()[
        "total"
    ] == 1
    assert client.get("/api/v1/registered-tasks", params={"target_app_id": app_b}).json()[
        "total"
    ] == 0


def test_execution_links_to_owned_experiment_run_only(client: TestClient):
    app_id, key = register_app(client, "linked-app")
    experiment = client.post(
        "/api/v1/experiments",
        json={
            "target_app_id": app_id,
            "name": "linked",
            "task_name": "app.tasks.charge_order",
            "scenario": "crash_after_commit",
        },
    ).json()
    run = client.post(
        f"/api/v1/experiments/{experiment['id']}/runs", headers=auth(key)
    ).json()

    linked = client.post(
        "/api/v1/task-executions/events",
        json=execution_body(veriq_run_id=run["id"]),
        headers=auth(key),
    )
    assert linked.json()["stored"] is True
    execution = client.get(
        "/api/v1/task-executions", params={"target_app_id": app_id}
    ).json()["items"][0]
    assert execution["experiment_run_id"] == run["id"]

    # Another application's execution reports the same run id: it must not be
    # linked, but ordinary telemetry is still stored for its own app.
    other_id, other_key = register_app(client, "linked-other")
    foreign = client.post(
        "/api/v1/task-executions/events",
        json=execution_body(veriq_run_id=run["id"]),
        headers=auth(other_key),
    )
    assert foreign.json()["stored"] is True
    other_execution = client.get(
        "/api/v1/task-executions", params={"target_app_id": other_id}
    ).json()["items"][0]
    assert other_execution["experiment_run_id"] is None


def test_execution_creates_worker_record_when_none_reported(
    client: TestClient, db_session: Session
):
    app_id, key = register_app(client, "worker-implicit")
    client.post(
        "/api/v1/task-executions/events",
        json=execution_body(worker_instance_id="late-worker"),
        headers=auth(key),
    )
    workers = client.get("/api/v1/workers", params={"target_app_id": app_id}).json()
    assert workers["total"] == 1
    assert workers["items"][0]["worker_instance_id"] == "late-worker"
    stored = db_session.scalar(select(Worker).where(Worker.worker_instance_id == "late-worker"))
    assert stored is not None and stored.status == "ONLINE"


def test_execution_pagination(client: TestClient):
    app_id, key = register_app(client, "pagination-app")
    for _ in range(3):
        client.post(
            "/api/v1/task-executions/events",
            json=execution_body(event_type="TASK_SUCCEEDED"),
            headers=auth(key),
        )

    page = client.get(
        "/api/v1/task-executions", params={"target_app_id": app_id, "skip": 0, "limit": 2}
    ).json()
    assert page["total"] == 3
    assert len(page["items"]) == 2
    second = client.get(
        "/api/v1/task-executions", params={"target_app_id": app_id, "skip": 2, "limit": 2}
    ).json()
    assert len(second["items"]) == 1


def test_ingestion_requires_api_key(client: TestClient):
    assert client.post("/api/v1/task-executions/events", json=execution_body()).status_code == 401
    assert client.post("/api/v1/workers/events", json=worker_body()).status_code == 401
    assert (
        client.post("/api/v1/tasks/discovery", json={"task_names": ["t"]}).status_code == 401
    )
