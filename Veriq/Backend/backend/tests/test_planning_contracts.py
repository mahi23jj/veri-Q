"""Task Test Contract lifecycle, validation and ownership."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.planning_helpers import (
    configure_adapter,
    contract_body,
    create_contract,
    discover_task,
    register_app,
)


def _setup(client: TestClient, name: str):
    app_id, key = register_app(client, name)
    task = discover_task(client, key, "app.tasks.process_document")
    http_adapter = configure_adapter(
        client, app_id, name="http-sandbox", adapter_type="http", triggers=("timeout_simulation",)
    )
    return app_id, key, task, http_adapter


def test_contract_create_retrieve_and_list(client: TestClient):
    app_id, _key, task, adapter = _setup(client, "contract-crud")

    contract = create_contract(
        client, app_id, task["id"], contract_body(measurement_adapter_id=adapter["id"])
    )
    assert contract["version"] == 1
    assert contract["validation"]["valid"] is True
    assert contract["payload"]["safe_input"] == {"document_id": "test-document-001"}

    fetched = client.get(
        f"/api/v1/applications/{app_id}/registered-tasks/{task['id']}/contract"
    )
    assert fetched.status_code == 200
    assert fetched.json()["id"] == contract["id"]

    listed = client.get(f"/api/v1/applications/{app_id}/contracts").json()
    assert [item["id"] for item in listed] == [contract["id"]]

    # One active contract per task.
    duplicate = client.post(
        f"/api/v1/applications/{app_id}/registered-tasks/{task['id']}/contract",
        json=contract_body(measurement_adapter_id=adapter["id"]),
    )
    assert duplicate.status_code == 409


def test_contract_update_appends_version(client: TestClient):
    app_id, _key, task, adapter = _setup(client, "contract-versions")
    contract = create_contract(
        client, app_id, task["id"], contract_body(measurement_adapter_id=adapter["id"])
    )

    updated_payload = contract_body(
        measurement_adapter_id=adapter["id"],
        safe_input={"document_id": "test-document-002"},
    )
    updated = client.patch(
        f"/api/v1/applications/{app_id}/contracts/{contract['id']}", json=updated_payload
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"] == 2
    assert updated.json()["payload"]["safe_input"] == {"document_id": "test-document-002"}

    versions = client.get(
        f"/api/v1/applications/{app_id}/contracts/{contract['id']}/versions"
    ).json()
    assert [version["version"] for version in versions] == [1, 2]
    assert versions[0]["payload"]["safe_input"] == {"document_id": "test-document-001"}
    assert versions[1]["payload"]["safe_input"] == {"document_id": "test-document-002"}


def test_contract_rejects_malformed_and_unsafe_input(client: TestClient):
    app_id, _key, task, adapter = _setup(client, "contract-invalid")
    url = f"/api/v1/applications/{app_id}/registered-tasks/{task['id']}/contract"

    # Unknown adapter reference.
    unknown = contract_body(
        measurement_adapter_id="00000000-0000-0000-0000-000000000000"
    )
    assert client.post(url, json=unknown).status_code == 422

    # Secret-looking keys are refused outright.
    secret = contract_body(measurement_adapter_id=adapter["id"])
    secret["safe_input"] = {"api_key": "sk-live-should-never-be-stored"}
    assert client.post(url, json=secret).status_code == 422

    # Assertions must reference a declared measurement.
    dangling = contract_body(measurement_adapter_id=adapter["id"])
    dangling["assertions"].append(
        {
            "id": "dangling",
            "description": "refers to nothing",
            "type": "effect_exists",
            "measurement_id": "missing_measurement",
        }
    )
    assert client.post(url, json=dangling).status_code == 422

    # effect_count needs an integer expectation.
    bad_count = contract_body(measurement_adapter_id=adapter["id"])
    bad_count["assertions"][-1]["expected"] = "one"
    assert client.post(url, json=bad_count).status_code == 422

    # adapter-managed cleanup needs an adapter.
    bad_cleanup = contract_body(measurement_adapter_id=adapter["id"])
    bad_cleanup["cleanup"] = {"mode": "adapter_managed"}
    assert client.post(url, json=bad_cleanup).status_code == 422

    # Nothing was stored by the rejected requests.
    assert client.get(f"/api/v1/applications/{app_id}/contracts").json() == []


def test_contract_validation_endpoint_reports_warnings(client: TestClient):
    app_id, _key, task, adapter = _setup(client, "contract-validate")
    contract = create_contract(
        client,
        app_id,
        task["id"],
        {
            "safe_input": {"document_id": "test-document-001"},
            "effect_measurements": [],
            "assertions": [],
            "cleanup": {"mode": "none"},
        },
    )
    assert contract["validation"]["valid"] is True
    codes = {issue["code"] for issue in contract["validation"]["issues"]}
    assert {"ASSERTIONS_MISSING", "EFFECT_MEASUREMENTS_MISSING", "CLEANUP_NOT_CONFIGURED"} <= codes

    report = client.post(
        f"/api/v1/applications/{app_id}/contracts/{contract['id']}/validate"
    ).json()
    assert report["valid"] is True
    assert all(issue["severity"] == "warning" for issue in report["issues"])


def test_contract_measurement_requires_capable_adapter(client: TestClient):
    app_id, key = register_app(client, "contract-capability")
    task = discover_task(client, key, "app.tasks.process_document")
    broker = configure_adapter(
        client, app_id, name="broker-main", adapter_type="broker", triggers=("duplicate_delivery",)
    )
    # The broker adapter does not declare effect_measurement.
    resp = client.post(
        f"/api/v1/applications/{app_id}/registered-tasks/{task['id']}/contract",
        json=contract_body(measurement_adapter_id=broker["id"]),
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["issues"][0]["code"] == "MEASUREMENT_CAPABILITY_MISSING"


def test_contract_is_scoped_to_its_application(client: TestClient):
    app_a, key_a, task, adapter = _setup(client, "contract-owner-a")
    app_b, key_b = register_app(client, "contract-owner-b")
    contract = create_contract(
        client, app_a, task["id"], contract_body(measurement_adapter_id=adapter["id"])
    )

    assert (
        client.get(f"/api/v1/applications/{app_b}/contracts/{contract['id']}").status_code
        == 404
    )
    assert client.get(f"/api/v1/applications/{app_b}/contracts").json() == []
    # Another application cannot attach a contract to a task it does not own.
    assert (
        client.post(
            f"/api/v1/applications/{app_b}/registered-tasks/{task['id']}/contract",
            json=contract_body(measurement_adapter_id=adapter["id"]),
        ).status_code
        == 404
    )
    # Nor can it update the owner's contract.
    assert (
        client.patch(
            f"/api/v1/applications/{app_b}/contracts/{contract['id']}",
            json=contract_body(measurement_adapter_id=adapter["id"]),
        ).status_code
        == 404
    )
    assert key_b


def test_saving_a_contract_does_not_execute_the_task(client: TestClient):
    app_id, _key, task, adapter = _setup(client, "contract-no-execution")
    create_contract(
        client, app_id, task["id"], contract_body(measurement_adapter_id=adapter["id"])
    )
    assert (
        client.get("/api/v1/task-executions", params={"target_app_id": app_id}).json()["total"]
        == 0
    )
    assert client.get("/api/v1/workers", params={"target_app_id": app_id}).json()["total"] == 0
