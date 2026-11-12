import uuid

from fastapi.testclient import TestClient


def _make_app(client: TestClient, name: str = "app-1") -> str:
    return client.post("/api/v1/applications", json={"name": name}).json()["id"]


def _experiment_payload(app_id: str, **overrides):
    payload = {
        "target_app_id": app_id,
        "name": "crash after commit",
        "task_name": "tasks.charge",
        "scenario": "crash_after_commit",
        "timeout_seconds": 60,
    }
    payload.update(overrides)
    return payload


def test_create_experiment_with_valid_application(client: TestClient):
    app_id = _make_app(client)
    resp = client.post("/api/v1/experiments", json=_experiment_payload(app_id))
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "DRAFT"
    assert body["target_app_id"] == app_id


def test_create_experiment_with_invalid_application_id(client: TestClient):
    resp = client.post("/api/v1/experiments", json=_experiment_payload(str(uuid.uuid4())))
    assert resp.status_code == 422


def test_invalid_timeout_values_rejected(client: TestClient):
    app_id = _make_app(client)
    for bad in (0, -1, 3601):
        resp = client.post("/api/v1/experiments", json=_experiment_payload(app_id, timeout_seconds=bad))
        assert resp.status_code == 422, bad


def test_empty_experiment_name_and_task_rejected(client: TestClient):
    app_id = _make_app(client)
    assert client.post("/api/v1/experiments", json=_experiment_payload(app_id, name="")).status_code == 422
    assert client.post("/api/v1/experiments", json=_experiment_payload(app_id, task_name=" ")).status_code == 422


def test_edit_draft_experiment(client: TestClient):
    app_id = _make_app(client)
    exp = client.post("/api/v1/experiments", json=_experiment_payload(app_id)).json()
    resp = client.patch(f"/api/v1/experiments/{exp['id']}", json={"name": "renamed", "timeout_seconds": 120})
    assert resp.status_code == 200
    assert resp.json()["name"] == "renamed"
    assert resp.json()["timeout_seconds"] == 120


def test_edit_non_draft_experiment_rejected(client: TestClient, db_session):
    app_id = _make_app(client)
    exp = client.post("/api/v1/experiments", json=_experiment_payload(app_id)).json()
    # No API transitions experiments out of DRAFT yet; simulate a future
    # status change directly in the DB to prove the guard works.
    from app.models import Experiment

    obj = db_session.get(Experiment, uuid.UUID(exp["id"]))
    obj.status = "ACTIVE"
    db_session.commit()

    resp = client.patch(f"/api/v1/experiments/{exp['id']}", json={"name": "nope"})
    assert resp.status_code == 409
    assert client.delete(f"/api/v1/experiments/{exp['id']}").status_code == 409


def test_delete_draft_experiment(client: TestClient):
    app_id = _make_app(client)
    exp = client.post("/api/v1/experiments", json=_experiment_payload(app_id)).json()
    assert client.delete(f"/api/v1/experiments/{exp['id']}").status_code == 204
    assert client.get(f"/api/v1/experiments/{exp['id']}").status_code == 404


def test_list_pagination(client: TestClient):
    app_id = _make_app(client)
    for i in range(3):
        client.post("/api/v1/experiments", json=_experiment_payload(app_id, name=f"exp-{i}"))
    body = client.get("/api/v1/experiments", params={"limit": 2, "skip": 0}).json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
