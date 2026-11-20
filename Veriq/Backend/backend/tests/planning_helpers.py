"""Shared helpers for the reliability-planning test suite."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient


def auth(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key}


def register_app(client: TestClient, name: str) -> tuple[str, str]:
    resp = client.post("/api/v1/applications", json={"name": name, "environment": "test"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"], resp.json()["api_key"]


def discover_task(client: TestClient, api_key: str, task_name: str) -> dict:
    resp = client.post(
        "/api/v1/tasks/discovery", json={"task_names": [task_name]}, headers=auth(api_key)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()[0]


def execution_body(
    *,
    task_name: str,
    event_type: str = "TASK_STARTED",
    execution_id: uuid.UUID | None = None,
    payload: dict | None = None,
) -> dict:
    body = {
        "execution_id": str(execution_id or uuid.uuid4()),
        "celery_task_id": str(uuid.uuid4()),
        "task_name": task_name,
        "worker_instance_id": "planning-worker",
        "worker_hostname": "celery@planning",
        "pid": 1234,
        "queue_name": "veriq.test",
        "event_type": event_type,
        "event_id": str(uuid.uuid4()),
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    }
    if payload is not None:
        body["payload"] = payload
    return body


def report_checkpoint(
    client: TestClient,
    api_key: str,
    *,
    task_name: str,
    checkpoint: str | None,
    execution_id: uuid.UUID | None = None,
    payload: dict | None = None,
) -> dict:
    details: dict = {}
    if checkpoint is not None:
        details["checkpoint"] = checkpoint
    if payload:
        details.update(payload)
    return client.post(
        "/api/v1/task-executions/events",
        json=execution_body(
            task_name=task_name,
            event_type="TASK_CHECKPOINT",
            execution_id=execution_id,
            payload=details,
        ),
        headers=auth(api_key),
    )


def configure_adapter(
    client: TestClient,
    app_id: str,
    *,
    name: str,
    adapter_type: str,
    triggers: tuple[str, ...] = (),
    capabilities: list[str] | None = None,
    validate: bool = True,
    configuration_ref: str | None = None,
) -> dict:
    body: dict = {
        "name": name,
        "adapter_type": adapter_type,
        "enabled_triggers": list(triggers),
        "configuration_ref": (
            configuration_ref if configuration_ref is not None else f"cfg://test/{name}"
        ),
    }
    if capabilities is not None:
        body["capabilities"] = capabilities
    resp = client.post(f"/api/v1/applications/{app_id}/adapters", json=body)
    assert resp.status_code == 201, resp.text
    adapter = resp.json()
    if validate:
        validated = client.post(
            f"/api/v1/applications/{app_id}/adapters/{adapter['id']}/validate"
        )
        assert validated.status_code == 200, validated.text
        adapter = validated.json()
        assert adapter["status"] == "VALIDATED", adapter
    return adapter


def contract_body(
    *,
    measurement_adapter_id: str | None = None,
    authoritative: bool = True,
    include_measurement: bool = True,
    safe_input: dict | None = None,
    cleanup: dict | None = None,
) -> dict:
    body: dict = {
        "safe_input": (
            {"document_id": "test-document-001"} if safe_input is None else safe_input
        ),
        "effect_measurements": [],
        "assertions": [
            {
                "id": "execution_outcome",
                "description": "Execution reaches the expected terminal state",
                "type": "execution_status",
                "expected": "FAILED",
            }
        ],
        "cleanup": cleanup or {"mode": "fixture_managed", "description": "test fixture"},
    }
    if include_measurement:
        adapter_id = measurement_adapter_id
        assert adapter_id is not None
        body["effect_measurements"] = [
            {
                "id": "document_effect",
                "adapter_id": adapter_id,
                "measurement_type": "row_count",
                "config": {"table": "documents"},
                "authoritative": authoritative,
            }
        ]
        body["assertions"].append(
            {
                "id": "single_document",
                "description": "Exactly one document effect exists",
                "type": "effect_count",
                "measurement_id": "document_effect",
                "expected": 1,
            }
        )
    return body


def create_contract(
    client: TestClient, app_id: str, task_id: str, body: dict
) -> dict:
    resp = client.post(
        f"/api/v1/applications/{app_id}/registered-tasks/{task_id}/contract", json=body
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def select_task_scenario(
    client: TestClient, app_id: str, task_id: str, scenario_id: str, enabled: bool
) -> dict:
    resp = client.put(
        f"/api/v1/applications/{app_id}/registered-tasks/{task_id}/scenarios/{scenario_id}",
        json={"enabled": enabled},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def create_plan(
    client: TestClient, app_id: str, name: str, task_ids: list[str]
) -> dict:
    resp = client.post(
        f"/api/v1/applications/{app_id}/test-plans",
        json={"name": name, "task_ids": task_ids},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def generate_plan(client: TestClient, app_id: str, plan_id: str) -> dict:
    resp = client.post(f"/api/v1/applications/{app_id}/test-plans/{plan_id}/generate")
    assert resp.status_code == 200, resp.text
    return resp.json()


def plan_cases(client: TestClient, app_id: str, plan_id: str, revision: int) -> list[dict]:
    resp = client.get(
        f"/api/v1/applications/{app_id}/test-plans/{plan_id}/revisions/{revision}/test-cases"
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def enable_checkpoint(
    client: TestClient, app_id: str, checkpoint_id: str, enabled: bool = True
) -> dict:
    resp = client.patch(
        f"/api/v1/applications/{app_id}/checkpoints/{checkpoint_id}",
        json={"reliability_enabled": enabled},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def select_checkpoint_scenario(
    client: TestClient,
    app_id: str,
    checkpoint_id: str,
    scenario_id: str,
    *,
    enabled: bool = True,
    assertion_overrides: list[dict] | None = None,
    config: dict | None = None,
) -> dict:
    body: dict = {"enabled": enabled}
    if config is not None:
        body["config"] = config
    if assertion_overrides is not None:
        body["assertion_overrides"] = assertion_overrides
    resp = client.put(
        f"/api/v1/applications/{app_id}/checkpoints/{checkpoint_id}/scenarios/{scenario_id}",
        json=body,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()
