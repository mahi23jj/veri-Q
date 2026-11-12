import uuid

from fastapi.testclient import TestClient


def test_health_reports_database_connected(client: TestClient):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "database": "connected"}


def test_create_and_get_application(client: TestClient):
    resp = client.post("/api/v1/applications", json={"name": "billing-api", "description": "Billing service"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "billing-api"
    assert body["environment"] == "development"
    uuid.UUID(body["id"])  # valid UUID

    got = client.get(f"/api/v1/applications/{body['id']}")
    assert got.status_code == 200
    assert got.json()["name"] == "billing-api"


def test_duplicate_application_name_rejected(client: TestClient):
    assert client.post("/api/v1/applications", json={"name": "dup-app"}).status_code == 201
    resp = client.post("/api/v1/applications", json={"name": "dup-app"})
    assert resp.status_code == 409


def test_empty_application_name_rejected(client: TestClient):
    resp = client.post("/api/v1/applications", json={"name": "   "})
    assert resp.status_code == 422


def test_get_missing_application_returns_404(client: TestClient):
    resp = client.get(f"/api/v1/applications/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_delete_application_without_experiments(client: TestClient):
    created = client.post("/api/v1/applications", json={"name": "to-delete"}).json()
    assert client.delete(f"/api/v1/applications/{created['id']}").status_code == 204
    assert client.get(f"/api/v1/applications/{created['id']}").status_code == 404


def test_delete_application_with_experiments_blocked(client: TestClient):
    app = client.post("/api/v1/applications", json={"name": "protected-app"}).json()
    client.post(
        "/api/v1/experiments",
        json={
            "target_app_id": app["id"],
            "name": "exp",
            "task_name": "tasks.charge",
            "scenario": "crash_after_commit",
        },
    )
    resp = client.delete(f"/api/v1/applications/{app['id']}")
    assert resp.status_code == 409
