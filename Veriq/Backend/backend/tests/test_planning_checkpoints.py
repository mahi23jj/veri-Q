"""Checkpoint discovery from SDK telemetry (planning metadata, not control)."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from tests.planning_helpers import (
    auth,
    discover_task,
    register_app,
    report_checkpoint,
)


def test_checkpoint_reports_create_one_discovered_checkpoint(client: TestClient):
    app_id, key = register_app(client, "checkpoint-discovery")
    discover_task(client, key, "app.tasks.process_document")

    first = report_checkpoint(
        client, key, task_name="app.tasks.process_document", checkpoint="after_download"
    )
    assert first.status_code == 201, first.text
    assert first.json()["stored"] is True

    checkpoints = client.get(
        f"/api/v1/applications/{app_id}/checkpoints"
    ).json()
    assert len(checkpoints) == 1
    checkpoint = checkpoints[0]
    assert checkpoint["name"] == "after_download"
    assert checkpoint["report_count"] == 1
    assert checkpoint["reliability_enabled"] is False

    # Repeated reports are the same checkpoint, not a new definition.
    second = report_checkpoint(
        client, key, task_name="app.tasks.process_document", checkpoint="after_download"
    )
    assert second.json()["stored"] is True
    checkpoints = client.get(f"/api/v1/applications/{app_id}/checkpoints").json()
    assert len(checkpoints) == 1
    assert checkpoints[0]["id"] == checkpoint["id"]
    assert checkpoints[0]["report_count"] == 2
    assert checkpoints[0]["last_seen_at"] >= checkpoint["last_seen_at"]


def test_checkpoint_identity_is_scoped_to_task(client: TestClient):
    app_id, key = register_app(client, "checkpoint-scope")
    discover_task(client, key, "app.tasks.process_document")
    discover_task(client, key, "app.tasks.sync_inventory")

    report_checkpoint(
        client, key, task_name="app.tasks.process_document", checkpoint="after_save"
    )
    report_checkpoint(
        client, key, task_name="app.tasks.sync_inventory", checkpoint="after_save"
    )

    checkpoints = client.get(f"/api/v1/applications/{app_id}/checkpoints").json()
    assert len(checkpoints) == 2
    assert {c["name"] for c in checkpoints} == {"after_save"}
    assert len({c["registered_task_id"] for c in checkpoints}) == 2


def test_checkpoint_metadata_is_bounded_and_optional(client: TestClient):
    app_id, key = register_app(client, "checkpoint-metadata")
    discover_task(client, key, "app.tasks.process_document")

    resp = report_checkpoint(
        client,
        key,
        task_name="app.tasks.process_document",
        checkpoint="after_download",
        payload={"document_id": "test-document-001", "nested": {"a": 1}},
    )
    assert resp.status_code == 201
    checkpoint = client.get(f"/api/v1/applications/{app_id}/checkpoints").json()[0]
    # Safe metadata is kept; the checkpoint name is not duplicated into it.
    assert checkpoint["checkpoint_metadata"] == {
        "document_id": "test-document-001",
        "nested": {"a": 1},
    }

    # A checkpoint event without a name is still ordinary telemetry.
    unlabelled = report_checkpoint(
        client, key, task_name="app.tasks.process_document", checkpoint=None
    )
    assert unlabelled.status_code == 201
    assert unlabelled.json()["stored"] is True
    assert len(client.get(f"/api/v1/applications/{app_id}/checkpoints").json()) == 1


def test_checkpoint_reporting_does_not_block_execution(client: TestClient):
    app_id, key = register_app(client, "checkpoint-nonblocking")
    discover_task(client, key, "app.tasks.process_document")
    execution_id = uuid.uuid4()

    started = client.post(
        "/api/v1/task-executions/events",
        json={
            "execution_id": str(execution_id),
            "task_name": "app.tasks.process_document",
            "event_type": "TASK_STARTED",
            "event_id": str(uuid.uuid4()),
        },
        headers=auth(key),
    )
    assert started.status_code == 201

    for name in ("after_download", "after_database_save"):
        resp = report_checkpoint(
            client,
            key,
            task_name="app.tasks.process_document",
            checkpoint=name,
            execution_id=execution_id,
        )
        assert resp.status_code == 201
        assert resp.json()["stored"] is True

    finished = client.post(
        "/api/v1/task-executions/events",
        json={
            "execution_id": str(execution_id),
            "task_name": "app.tasks.process_document",
            "event_type": "TASK_SUCCEEDED",
            "event_id": str(uuid.uuid4()),
        },
        headers=auth(key),
    )
    assert finished.json()["status"] == "SUCCEEDED"

    executions = client.get(
        "/api/v1/task-executions", params={"target_app_id": app_id}
    ).json()
    assert executions["total"] == 1
    detail = client.get(f"/api/v1/task-executions/{executions['items'][0]['id']}").json()
    assert [e["event_type"] for e in detail["events"]] == [
        "TASK_STARTED",
        "TASK_CHECKPOINT",
        "TASK_CHECKPOINT",
        "TASK_SUCCEEDED",
    ]
    # Enabling reliability testing for a checkpoint does not alter telemetry.
    checkpoint = client.get(f"/api/v1/applications/{app_id}/checkpoints").json()[0]
    client.patch(
        f"/api/v1/applications/{app_id}/checkpoints/{checkpoint['id']}",
        json={"reliability_enabled": True},
    )
    again = report_checkpoint(
        client, key, task_name="app.tasks.process_document", checkpoint="after_download"
    )
    assert again.json()["stored"] is True


def test_checkpoints_are_scoped_to_the_application(client: TestClient):
    app_a, key_a = register_app(client, "checkpoint-app-a")
    app_b, _key_b = register_app(client, "checkpoint-app-b")
    discover_task(client, key_a, "app.tasks.process_document")
    report_checkpoint(
        client, key_a, task_name="app.tasks.process_document", checkpoint="after_save"
    )

    assert len(client.get(f"/api/v1/applications/{app_a}/checkpoints").json()) == 1
    assert client.get(f"/api/v1/applications/{app_b}/checkpoints").json() == []

    checkpoint = client.get(f"/api/v1/applications/{app_a}/checkpoints").json()[0]
    # Cross-application access is a 404, never a leak.
    assert (
        client.get(f"/api/v1/applications/{app_b}/checkpoints/{checkpoint['id']}").status_code
        == 404
    )
