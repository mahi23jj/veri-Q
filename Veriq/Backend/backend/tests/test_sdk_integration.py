"""End-to-end: the real SDK package driving the real FastAPI app in-process.

Traffic is routed through the TestClient's own transport, so the SDK exercises
its HTTP layer and the backend exercises auth, ownership and persistence. No
live server or Docker is involved; it is skipped if the SDK is not installed.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

veriq = pytest.importorskip("veriq")

from veriq import VeriQ, VeriQConfig  # noqa: E402
from veriq.exceptions import VeriQAuthenticationError, VeriQValidationError  # noqa: E402
from veriq.transport.http import HTTPTransport  # noqa: E402

BACKEND_URL = "http://testserver"


def sdk_for(client: TestClient, api_key: str) -> VeriQ:
    """Build an SDK client whose HTTP traffic goes straight into the app."""
    config = VeriQConfig(BACKEND_URL, api_key, timeout=5.0)
    http_client = httpx.Client(transport=client._transport, base_url=BACKEND_URL)
    return VeriQ(transport=HTTPTransport(config, client=http_client))


def register_app(client: TestClient, name: str) -> tuple[str, str]:
    resp = client.post(
        "/api/v1/applications", json={"name": name, "environment": "test"}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"], resp.json()["api_key"]


def create_run(client: TestClient, api_key: str, experiment_id: str) -> dict:
    resp = client.post(
        f"/api/v1/experiments/{experiment_id}/runs", headers={"X-API-Key": api_key}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_sdk_event_round_trip_is_persisted_and_idempotent(client: TestClient):
    app_id, api_key = register_app(client, "sdk-round-trip")
    experiment = client.post(
        "/api/v1/experiments",
        json={
            "target_app_id": app_id,
            "name": "sdk round trip",
            "task_name": "app.tasks.charge",
            "scenario": "crash_after_commit",
        },
    ).json()
    run = create_run(client, api_key, experiment["id"])

    event_id = uuid.uuid4()
    occurred_at = datetime.now(timezone.utc).replace(microsecond=0)

    with sdk_for(client, api_key) as sdk:
        receipt = sdk.send_event(
            experiment_run_id=run["id"],
            event_type="sdk.test_event",
            payload={"message": "SDK communication successful"},
            event_id=event_id,
            occurred_at=occurred_at,
        )
        assert receipt.status_code == 201
        assert receipt.duplicate is False
        assert client.get(
            f"/api/v1/experiment-runs/{run['id']}/events", headers={"X-API-Key": api_key}
        ).json()[0]["id"] == str(receipt.server_event_id)

        # Re-sending the same event ID is deduplicated by the backend.
        retry = sdk.send_event(
            experiment_run_id=run["id"],
            event_type="sdk.test_event",
            payload={"message": "SDK communication successful"},
            event_id=event_id,
            occurred_at=occurred_at,
        )
        assert retry.duplicate is True
        assert retry.server_event_id == receipt.server_event_id

    events = client.get(
        f"/api/v1/experiment-runs/{run['id']}/events", headers={"X-API-Key": api_key}
    ).json()
    assert len(events) == 1
    stored = events[0]
    assert stored["source"] == "SDK"
    assert stored["event_type"] == "sdk.test_event"
    assert stored["payload"] == {"message": "SDK communication successful"}
    assert datetime.fromisoformat(stored["occurred_at"]) == occurred_at
    assert stored["experiment_run_id"] == run["id"]


def test_sdk_rejects_wrong_api_key_and_foreign_runs(client: TestClient):
    owner_id, owner_key = register_app(client, "sdk-owner")
    _, other_key = register_app(client, "sdk-other")
    experiment = client.post(
        "/api/v1/experiments",
        json={
            "target_app_id": owner_id,
            "name": "owned",
            "task_name": "app.tasks.charge",
            "scenario": "crash_after_commit",
        },
    ).json()
    run = create_run(client, owner_key, experiment["id"])

    # A valid key that does not own the run is rejected without leaking it.
    with sdk_for(client, other_key) as sdk:
        with pytest.raises(VeriQValidationError) as foreign:
            sdk.send_event(run["id"], "sdk.test_event", event_id=uuid.uuid4())
        assert foreign.value.status_code == 404

    with sdk_for(client, "vq_invalid_key") as sdk:
        with pytest.raises(VeriQAuthenticationError) as unauthorized:
            sdk.send_event(run["id"], "sdk.test_event")
        assert unauthorized.value.status_code == 401
        assert "vq_invalid_key" not in str(unauthorized.value)

    with sdk_for(client, owner_key) as sdk:
        with pytest.raises(VeriQValidationError):
            sdk.send_event(uuid.uuid4(), "sdk.test_event")

    assert client.get(
        f"/api/v1/experiment-runs/{run['id']}/events", headers={"X-API-Key": owner_key}
    ).json() == []
