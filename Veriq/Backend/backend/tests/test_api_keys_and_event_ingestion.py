"""API-key auth, run creation and SDK event ingestion (backend side).

The SDK-facing contract lives here: X-API-Key auth scoped to one target app,
run ownership checks, and idempotent event submission. No execution engine is
involved — runs are created in PENDING and never started.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient


def _register(client: TestClient, name: str) -> tuple[str, str]:
    resp = client.post("/api/v1/applications", json={"name": name, "environment": "test"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body["id"], body["api_key"]


def _experiment(client: TestClient, app_id: str, **overrides) -> dict:
    payload = {
        "target_app_id": app_id,
        "name": "crash after commit",
        "task_name": "tasks.charge",
        "scenario": "crash_after_commit",
        "timeout_seconds": 60,
    }
    payload.update(overrides)
    resp = client.post("/api/v1/experiments", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _run(client: TestClient, api_key: str, experiment_id: str) -> dict:
    resp = client.post(
        f"/api/v1/experiments/{experiment_id}/runs", headers={"X-API-Key": api_key}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _event(run_id: str, event_id: uuid.UUID, occurred_at: datetime, **kwargs) -> dict:
    body = {
        "event_id": str(event_id),
        "event_type": "sdk.test_event",
        "occurred_at": occurred_at.isoformat(),
        "payload": {"message": "SDK communication successful"},
    }
    body.update(kwargs)
    return body


def test_application_creation_returns_api_key_once_and_never_again(client: TestClient):
    app_id, api_key = _register(client, "key-app")
    assert api_key.startswith("vq_")

    assert "api_key" not in client.get(f"/api/v1/applications/{app_id}").json()
    listed = client.get("/api/v1/applications").json()["items"]
    assert all("api_key" not in item for item in listed)


def test_rotating_api_key_invalidates_the_previous_one(client: TestClient):
    app_id, old_key = _register(client, "rotate-app")
    exp = _experiment(client, app_id)

    rotated = client.post(f"/api/v1/applications/{app_id}/api-key")
    assert rotated.status_code == 200
    new_key = rotated.json()["api_key"]
    assert new_key != old_key

    old_attempt = client.post(
        f"/api/v1/experiments/{exp['id']}/runs", headers={"X-API-Key": old_key}
    )
    assert old_attempt.status_code == 401
    _run(client, new_key, exp["id"])


def test_missing_and_invalid_api_keys_are_rejected_without_echoing_them(client: TestClient):
    app_id, _ = _register(client, "auth-app")
    exp = _experiment(client, app_id)

    assert client.post(f"/api/v1/experiments/{exp['id']}/runs").status_code == 401

    bogus = "vq_this-key-does-not-exist"
    resp = client.post(f"/api/v1/experiments/{exp['id']}/runs", headers={"X-API-Key": bogus})
    assert resp.status_code == 401
    assert bogus not in resp.text


def test_run_is_scoped_to_the_authenticated_application(client: TestClient):
    owner_id, owner_key = _register(client, "owner-app")
    other_id, other_key = _register(client, "other-app")
    exp = _experiment(client, owner_id)

    forbidden = client.post(
        f"/api/v1/experiments/{exp['id']}/runs", headers={"X-API-Key": other_key}
    )
    # Cross-tenant access looks like a missing resource on purpose.
    assert forbidden.status_code == 404

    run = _run(client, owner_key, exp["id"])
    assert client.get(
        f"/api/v1/experiment-runs/{run['id']}", headers={"X-API-Key": other_key}
    ).status_code == 404
    assert client.get(
        f"/api/v1/experiment-runs/{run['id']}", headers={"X-API-Key": owner_key}
    ).status_code == 200
    assert other_id != owner_id


def test_run_numbers_increment_and_config_snapshot_is_frozen(client: TestClient):
    app_id, api_key = _register(client, "snapshot-app")
    exp = _experiment(client, app_id, checkpoint_name="after_commit")

    first = _run(client, api_key, exp["id"])
    second = _run(client, api_key, exp["id"])
    assert (first["run_number"], second["run_number"]) == (1, 2)
    assert first["status"] == "PENDING"
    assert first["config_snapshot"]["task_name"] == "tasks.charge"
    assert first["config_snapshot"]["checkpoint_name"] == "after_commit"

    # A later experiment edit must not rewrite the run's snapshot.
    assert client.patch(
        f"/api/v1/experiments/{exp['id']}", json={"timeout_seconds": 120}
    ).status_code == 200
    reloaded = client.get(
        f"/api/v1/experiment-runs/{first['id']}", headers={"X-API-Key": api_key}
    ).json()
    assert reloaded["config_snapshot"]["timeout_seconds"] == 60


def test_event_is_persisted_with_sdk_source_and_occurrence_time(client: TestClient):
    app_id, api_key = _register(client, "event-app")
    exp = _experiment(client, app_id)
    run = _run(client, api_key, exp["id"])
    occurred_at = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(seconds=30)
    event_id = uuid.uuid4()

    created = client.post(
        f"/api/v1/experiment-runs/{run['id']}/events",
        json=_event(run["id"], event_id, occurred_at),
        headers={"X-API-Key": api_key},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["source"] == "SDK"
    assert body["event_type"] == "sdk.test_event"
    assert body["payload"] == {"message": "SDK communication successful"}
    assert datetime.fromisoformat(body["occurred_at"]) == occurred_at
    assert body["experiment_run_id"] == run["id"]

    events = client.get(
        f"/api/v1/experiment-runs/{run['id']}/events", headers={"X-API-Key": api_key}
    ).json()
    assert [e["id"] for e in events] == [body["id"]]


def test_duplicate_event_id_does_not_duplicate_evidence(client: TestClient):
    app_id, api_key = _register(client, "idempotent-app")
    exp = _experiment(client, app_id)
    run = _run(client, api_key, exp["id"])
    event_id = uuid.uuid4()
    occurred_at = datetime.now(timezone.utc)
    body = _event(run["id"], event_id, occurred_at)

    first = client.post(
        f"/api/v1/experiment-runs/{run['id']}/events", json=body, headers={"X-API-Key": api_key}
    )
    second = client.post(
        f"/api/v1/experiment-runs/{run['id']}/events", json=body, headers={"X-API-Key": api_key}
    )
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    events = client.get(
        f"/api/v1/experiment-runs/{run['id']}/events", headers={"X-API-Key": api_key}
    ).json()
    assert len(events) == 1


def test_event_cannot_be_posted_to_another_applications_run(client: TestClient):
    owner_id, owner_key = _register(client, "event-owner")
    _, other_key = _register(client, "event-other")
    exp = _experiment(client, owner_id)
    run = _run(client, owner_key, exp["id"])

    resp = client.post(
        f"/api/v1/experiment-runs/{run['id']}/events",
        json=_event(run["id"], uuid.uuid4(), datetime.now(timezone.utc)),
        headers={"X-API-Key": other_key},
    )
    assert resp.status_code == 404
    assert client.get(
        f"/api/v1/experiment-runs/{run['id']}/events", headers={"X-API-Key": owner_key}
    ).json() == []


def test_unknown_run_and_invalid_event_payload_are_rejected(client: TestClient):
    app_id, api_key = _register(client, "validation-app")
    exp = _experiment(client, app_id)
    run = _run(client, api_key, exp["id"])

    missing = client.post(
        f"/api/v1/experiment-runs/{uuid.uuid4()}/events",
        json=_event(str(uuid.uuid4()), uuid.uuid4(), datetime.now(timezone.utc)),
        headers={"X-API-Key": api_key},
    )
    assert missing.status_code == 404

    naive = client.post(
        f"/api/v1/experiment-runs/{run['id']}/events",
        json={
            "event_type": "sdk.test_event",
            "occurred_at": "2026-11-11T10:00:00",
        },
        headers={"X-API-Key": api_key},
    )
    assert naive.status_code == 422

    empty_type = client.post(
        f"/api/v1/experiment-runs/{run['id']}/events",
        json={"event_type": "   "},
        headers={"X-API-Key": api_key},
    )
    assert empty_type.status_code == 422
