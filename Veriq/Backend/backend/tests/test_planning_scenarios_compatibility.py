"""Scenario catalogue, checkpoint selection and the compatibility engine."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.domain.compatibility.engine import (
    AdapterView,
    CheckpointView,
    ContractView,
    TaskView,
    evaluate,
)
from app.domain.scenarios.catalog import get_scenario
from tests.planning_helpers import (
    configure_adapter,
    contract_body,
    create_contract,
    discover_task,
    enable_checkpoint,
    register_app,
    report_checkpoint,
    select_checkpoint_scenario,
    select_task_scenario,
)


def _compat(client: TestClient, app_id: str, **selection) -> dict:
    resp = client.post(
        f"/api/v1/applications/{app_id}/compatibility/evaluate",
        json={"selections": [selection]},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["results"][0]


def _setup(client: TestClient, name: str):
    app_id, key = register_app(client, name)
    task = discover_task(client, key, "app.tasks.process_document")
    http_adapter = configure_adapter(
        client,
        app_id,
        name="http-sandbox",
        adapter_type="http",
        triggers=("timeout_simulation", "lost_response_simulation"),
    )
    return app_id, key, task, http_adapter


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------


def test_initial_scenario_catalog_contains_required_patterns(client: TestClient):
    payload = client.get("/api/v1/scenarios").json()
    assert payload["implementation_status"] == "RUNNER"
    by_id = {item["id"]: item for item in payload["items"]}
    assert {
        "dependency_timeout",
        "successful_operation_lost_response",
        "duplicate_message_delivery",
        "database_connection_interruption",
        "worker_termination",
    } == set(by_id)

    for item in payload["items"]:
        assert item["version"] >= 1
        assert item["supported_status"] == "SUPPORTED"
        assert item["implementation_status"] == "RUNNER"
        assert item["adapter_requirements"]
        assert "configuration_schema" in item
        assert "expected_recovery" in item

    worker = by_id["worker_termination"]
    assert set(worker["supported_trigger_modes"]) == {"automatic", "checkpoint"}
    assert "redelivery" in " ".join(worker["warnings"]).lower()

    lost = by_id["successful_operation_lost_response"]
    assert lost["requires"]["authoritative_measurement"] is True
    assert lost["adapter_requirements"][0]["trigger"] == "lost_response_simulation"


def test_scenario_catalog_is_not_business_specific(client: TestClient):
    raw = client.get("/api/v1/scenarios").text
    assert "app.tasks." not in raw
    assert "charge_order" not in raw


def test_scenario_filters_and_detail(client: TestClient):
    runtime = client.get("/api/v1/scenarios", params={"category": "runtime"}).json()["items"]
    assert [item["id"] for item in runtime] == ["worker_termination"]

    checkpointable = client.get(
        "/api/v1/scenarios", params={"trigger_type": "checkpoint"}
    ).json()["items"]
    assert {"worker_termination", "duplicate_message_delivery"} <= {
        item["id"] for item in checkpointable
    }

    detail = client.get("/api/v1/scenarios/dependency_timeout")
    assert detail.status_code == 200
    assert detail.json()["category"] == "dependency"
    assert client.get("/api/v1/scenarios/does_not_exist").status_code == 404


# ---------------------------------------------------------------------------
# Automatic selection configuration
# ---------------------------------------------------------------------------


def test_automatic_scenario_selection_and_opt_out(client: TestClient):
    app_id, _key, task, adapter = _setup(client, "selection-auto")
    create_contract(client, app_id, task["id"], contract_body(measurement_adapter_id=adapter["id"]))

    scenarios = {
        item["scenario_id"]: item
        for item in client.get(
            f"/api/v1/applications/{app_id}/registered-tasks/{task['id']}/scenarios"
        ).json()
    }
    assert scenarios["dependency_timeout"]["enabled"] is True
    assert scenarios["dependency_timeout"]["selected_by_default"] is True
    assert scenarios["dependency_timeout"]["compatibility"]["status"] == "COMPATIBLE"

    # Individually opt out; no other selection is affected.
    updated = select_task_scenario(
        client, app_id, task["id"], "dependency_timeout", False
    )
    assert updated["enabled"] is False

    scenarios = {
        item["scenario_id"]: item
        for item in client.get(
            f"/api/v1/applications/{app_id}/registered-tasks/{task['id']}/scenarios"
        ).json()
    }
    assert scenarios["dependency_timeout"]["enabled"] is False
    assert scenarios["duplicate_message_delivery"]["compatibility"]["status"] != "COMPATIBLE"

    # A scenario that cannot work automatically is rejected.
    bad = client.put(
        f"/api/v1/applications/{app_id}/registered-tasks/{task['id']}/scenarios/dependency_timeout",
        json={"enabled": True, "config": {"unsupported_key": 1}},
    )
    assert bad.status_code == 422


def test_checkpoint_scenarios_are_independent_of_task_scenarios(client: TestClient):
    app_id, key, task, adapter = _setup(client, "selection-checkpoint")
    configure_adapter(
        client, app_id, name="broker-main", adapter_type="broker", triggers=("duplicate_delivery",)
    )
    create_contract(client, app_id, task["id"], contract_body(measurement_adapter_id=adapter["id"]))
    report_checkpoint(
        client, key, task_name="app.tasks.process_document", checkpoint="after_database_save"
    )
    checkpoint = client.get(f"/api/v1/applications/{app_id}/checkpoints").json()[0]
    enable_checkpoint(client, app_id, checkpoint["id"])

    before = {
        item["scenario_id"]: item
        for item in client.get(
            f"/api/v1/applications/{app_id}/registered-tasks/{task['id']}/scenarios"
        ).json()
    }
    selected = select_checkpoint_scenario(
        client, app_id, checkpoint["id"], "worker_termination"
    )
    assert selected["enabled"] is True
    assert selected["compatibility"]["status"] == "COMPATIBLE"

    after = {
        item["scenario_id"]: item
        for item in client.get(
            f"/api/v1/applications/{app_id}/registered-tasks/{task['id']}/scenarios"
        ).json()
    }
    # Task-level automatic choices are untouched by a checkpoint selection.
    assert {k: v["enabled"] for k, v in before.items()} == {
        k: v["enabled"] for k, v in after.items()
    }

    # A scenario without checkpoint support is refused at a checkpoint.
    rejected = client.put(
        f"/api/v1/applications/{app_id}/checkpoints/{checkpoint['id']}/scenarios/dependency_timeout",
        json={"enabled": True},
    )
    assert rejected.status_code == 422


# ---------------------------------------------------------------------------
# Compatibility API
# ---------------------------------------------------------------------------


def test_missing_contract_needs_configuration(client: TestClient):
    app_id, _key, task, _adapter = _setup(client, "compat-no-contract")
    result = _compat(
        client,
        app_id,
        task_id=task["id"],
        scenario_id="dependency_timeout",
        trigger_type="automatic",
    )
    assert result["status"] == "NEEDS_CONFIGURATION"
    codes = {reason["code"] for reason in result["reasons"]}
    assert "CONTRACT_MISSING" in codes
    assert result["execution_available"] is False


def test_compatible_when_all_capabilities_present(client: TestClient):
    app_id, _key, task, adapter = _setup(client, "compat-complete")
    create_contract(client, app_id, task["id"], contract_body(measurement_adapter_id=adapter["id"]))

    result = _compat(
        client,
        app_id,
        task_id=task["id"],
        scenario_id="dependency_timeout",
        trigger_type="automatic",
    )
    assert result["status"] == "COMPATIBLE", result
    assert result["selected_adapters"][0]["adapter_id"] == adapter["id"]
    assert result["execution_available"] is True


def test_lost_response_requires_authoritative_measurement(client: TestClient):
    app_id, key = register_app(client, "compat-lost-response")
    task = discover_task(client, key, "app.tasks.process_document")
    # Only timeout injection is enabled at first.
    adapter = configure_adapter(
        client,
        app_id,
        name="http-sandbox",
        adapter_type="http",
        triggers=("timeout_simulation",),
    )
    contract = create_contract(
        client,
        app_id,
        task["id"],
        contract_body(measurement_adapter_id=adapter["id"], authoritative=False),
    )

    result = _compat(
        client,
        app_id,
        task_id=task["id"],
        scenario_id="successful_operation_lost_response",
        trigger_type="automatic",
    )
    assert result["status"] == "NEEDS_CONFIGURATION"
    codes = {reason["code"] for reason in result["reasons"] if reason["severity"] == "configuration"}
    assert "NON_AUTHORITATIVE_MEASUREMENT" in codes
    # The missing injection capability is explained separately.
    assert "TRIGGER_CAPABILITY_NOT_ENABLED" in codes

    # Enable the lost-response trigger and make the measurement authoritative.
    patched_adapter = client.patch(
        f"/api/v1/applications/{app_id}/adapters/{adapter['id']}",
        json={"enabled_triggers": ["timeout_simulation", "lost_response_simulation"]},
    )
    assert patched_adapter.status_code == 200
    client.post(f"/api/v1/applications/{app_id}/adapters/{adapter['id']}/validate")
    updated = client.patch(
        f"/api/v1/applications/{app_id}/contracts/{contract['id']}",
        json=contract_body(measurement_adapter_id=adapter["id"], authoritative=True),
    )
    assert updated.status_code == 200, updated.text
    result = _compat(
        client,
        app_id,
        task_id=task["id"],
        scenario_id="successful_operation_lost_response",
        trigger_type="automatic",
    )
    assert result["status"] == "COMPATIBLE", result


def test_unsupported_trigger_mode_reports_unsupported(client: TestClient):
    app_id, _key, task, _adapter = _setup(client, "compat-trigger")
    result = _compat(
        client,
        app_id,
        task_id=task["id"],
        scenario_id="dependency_timeout",
        trigger_type="checkpoint",
    )
    assert result["status"] == "UNSUPPORTED"
    assert any(
        reason["code"] == "TRIGGER_MODE_UNSUPPORTED" for reason in result["reasons"]
    )


def test_checkpoint_requirements_are_validated(client: TestClient):
    app_id, key, task, adapter = _setup(client, "compat-checkpoint")
    report_checkpoint(
        client, key, task_name="app.tasks.process_document", checkpoint="after_database_save"
    )
    checkpoint = client.get(f"/api/v1/applications/{app_id}/checkpoints").json()[0]
    create_contract(
        client,
        app_id,
        task["id"],
        contract_body(
            measurement_adapter_id=adapter["id"],
            cleanup={"mode": "fixture_managed"},
        ),
    )

    # No broker adapter yet, and the checkpoint is not enabled.
    result = _compat(
        client,
        app_id,
        task_id=task["id"],
        scenario_id="worker_termination",
        trigger_type="checkpoint",
        checkpoint_id=checkpoint["id"],
    )
    assert result["status"] == "NEEDS_CONFIGURATION"
    codes = {reason["code"] for reason in result["reasons"]}
    assert "CHECKPOINT_NOT_ENABLED" in codes
    assert "ADAPTER_NOT_CONFIGURED" in codes

    enable_checkpoint(client, app_id, checkpoint["id"])
    configure_adapter(client, app_id, name="broker-main", adapter_type="broker")
    result = _compat(
        client,
        app_id,
        task_id=task["id"],
        scenario_id="worker_termination",
        trigger_type="checkpoint",
        checkpoint_id=checkpoint["id"],
    )
    assert result["status"] == "COMPATIBLE", result


def test_unvalidated_adapter_needs_configuration(client: TestClient):
    app_id, key = register_app(client, "compat-unvalidated")
    task = discover_task(client, key, "app.tasks.process_document")
    unvalidated = client.post(
        f"/api/v1/applications/{app_id}/adapters",
        json={
            "name": "http-draft",
            "adapter_type": "http",
            "enabled_triggers": ["timeout_simulation"],
        },
    ).json()
    create_contract(
        client, app_id, task["id"], contract_body(measurement_adapter_id=unvalidated["id"])
    )
    result = _compat(
        client,
        app_id,
        task_id=task["id"],
        scenario_id="dependency_timeout",
        trigger_type="automatic",
    )
    assert result["status"] == "NEEDS_CONFIGURATION"
    assert any(reason["code"] == "ADAPTER_NOT_VALIDATED" for reason in result["reasons"])


def test_capability_not_present_is_never_reported_available(client: TestClient):
    app_id, key = register_app(client, "compat-capability")
    task = discover_task(client, key, "app.tasks.process_document")
    # HTTP adapter that only observes dependencies: no failure_trigger.
    observer = client.post(
        f"/api/v1/applications/{app_id}/adapters",
        json={
            "name": "http-observer",
            "adapter_type": "http",
            "capabilities": ["dependency_observation"],
            "configuration_ref": "cfg://observer",
        },
    ).json()
    client.post(f"/api/v1/applications/{app_id}/adapters/{observer['id']}/validate")
    result = _compat(
        client,
        app_id,
        task_id=task["id"],
        scenario_id="dependency_timeout",
        trigger_type="automatic",
    )
    assert result["status"] == "NEEDS_CONFIGURATION"
    codes = {reason["code"] for reason in result["reasons"]}
    assert "ADAPTER_NOT_CONFIGURED" in codes
    assert "failure_trigger" in next(
        reason["message"] for reason in result["reasons"] if reason["code"] == "ADAPTER_NOT_CONFIGURED"
    )


def test_evaluation_is_deterministic(client: TestClient):
    app_id, _key, task, adapter = _setup(client, "compat-deterministic")
    create_contract(client, app_id, task["id"], contract_body(measurement_adapter_id=adapter["id"]))
    selection = {
        "task_id": task["id"],
        "scenario_id": "dependency_timeout",
        "trigger_type": "automatic",
    }
    first = _compat(client, app_id, **selection)
    second = _compat(client, app_id, **selection)
    assert first == second


def test_cross_application_compatibility_is_rejected(client: TestClient):
    app_a, _key_a, task, _adapter = _setup(client, "compat-owner-a")
    app_b, _key_b = register_app(client, "compat-owner-b")
    resp = client.post(
        f"/api/v1/applications/{app_b}/compatibility/evaluate",
        json={
            "selections": [
                {
                    "task_id": task["id"],
                    "scenario_id": "dependency_timeout",
                    "trigger_type": "automatic",
                }
            ]
        },
    )
    assert resp.status_code == 404
    assert app_a


# ---------------------------------------------------------------------------
# Engine unit tests (pure)
# ---------------------------------------------------------------------------


def _contract(mapping: dict) -> ContractView:
    return ContractView(id="c1", version=1, payload=mapping, valid=True)


def test_engine_prioritises_unsupported_over_configuration():
    scenario = get_scenario("dependency_timeout")
    assert scenario is not None
    result = evaluate(
        task=TaskView(id="t1", task_name="app.tasks.anything"),
        scenario=scenario,
        trigger_type="checkpoint",  # not supported for this scenario
        checkpoint=CheckpointView(id="cp1", name="after_save", reliability_enabled=False),
        contract=None,
        adapters=[],
    )
    assert result.status == "UNSUPPORTED"
    codes = [reason.code for reason in result.reasons]
    assert codes[0] == "TRIGGER_MODE_UNSUPPORTED"


def test_engine_selects_a_validated_adapter_that_enables_the_required_trigger():
    scenario = get_scenario("dependency_timeout")
    assert scenario is not None
    adapters = [
        AdapterView(
            id="a-adapter",
            name="http-no-trigger",
            adapter_type="http",
            category="http",
            capabilities=frozenset({"failure_trigger"}),
            enabled_triggers=frozenset(),
            status="VALIDATED",
        ),
        AdapterView(
            id="b-adapter",
            name="http-with-trigger",
            adapter_type="http",
            category="http",
            capabilities=frozenset({"failure_trigger"}),
            enabled_triggers=frozenset({"timeout_simulation"}),
            status="VALIDATED",
        ),
    ]
    contract = _contract(
        {
            "safe_input": {"document_id": "test-document-001"},
            "assertions": [{"id": "ok", "type": "execution_status", "expected": "FAILED"}],
            "effect_measurements": [],
            "cleanup": {"mode": "none"},
        }
    )

    result = evaluate(
        task=TaskView(id="t1", task_name="app.tasks.anything"),
        scenario=scenario,
        trigger_type="automatic",
        checkpoint=None,
        contract=contract,
        adapters=adapters,
    )

    assert result.status == "COMPATIBLE"
    assert result.selected_adapters[0]["adapter_id"] == "b-adapter"


def test_engine_is_order_stable_for_adapters():
    scenario = get_scenario("dependency_timeout")
    assert scenario is not None
    adapters = [
        AdapterView(
            id="b-adapter",
            name="b",
            adapter_type="http",
            category="http",
            capabilities=frozenset({"failure_trigger"}),
            enabled_triggers=frozenset({"timeout_simulation"}),
            status="VALIDATED",
        ),
        AdapterView(
            id="a-adapter",
            name="a",
            adapter_type="http",
            category="http",
            capabilities=frozenset({"failure_trigger"}),
            enabled_triggers=frozenset({"timeout_simulation"}),
            status="VALIDATED",
        ),
    ]
    contract = _contract(
        {
            "safe_input": {"document_id": "test-document-001"},
            "assertions": [{"id": "ok", "type": "execution_status", "expected": "FAILED"}],
            "effect_measurements": [],
            "cleanup": {"mode": "none"},
        }
    )
    first = evaluate(
        task=TaskView(id="t1", task_name="app.tasks.anything"),
        scenario=scenario,
        trigger_type="automatic",
        checkpoint=None,
        contract=contract,
        adapters=adapters,
    )
    second = evaluate(
        task=TaskView(id="t1", task_name="app.tasks.anything"),
        scenario=scenario,
        trigger_type="automatic",
        checkpoint=None,
        contract=contract,
        adapters=list(reversed(adapters)),
    )
    assert first.status == second.status == "COMPATIBLE"
    assert first.selected_adapters == second.selected_adapters
    assert first.selected_adapters[0]["adapter_id"] == "a-adapter"


def test_engine_marks_execution_available_only_for_compatible_implemented_cases():
    scenario = get_scenario("worker_termination")
    assert scenario is not None
    result = evaluate(
        task=TaskView(id="t1", task_name="app.tasks.anything"),
        scenario=scenario,
        trigger_type="automatic",
        checkpoint=None,
        contract=_contract(
            {
                "safe_input": {"document_id": "test-document-001"},
                "assertions": [],
                "effect_measurements": [],
                "cleanup": {"mode": "none"},
            }
        ),
        adapters=[
            AdapterView(
                id="broker-1",
                name="broker",
                adapter_type="broker",
                category="broker",
                capabilities=frozenset({"dependency_observation"}),
                enabled_triggers=frozenset(),
                status="VALIDATED",
            )
        ],
    )
    assert result.compatible is True
    assert result.execution_available is True
    assert any("redelivery" in warning.message.lower() for warning in result.warnings)

    # A configuration problem still makes the case non-executable.
    incomplete = evaluate(
        task=TaskView(id="t1", task_name="app.tasks.anything"),
        scenario=scenario,
        trigger_type="automatic",
        checkpoint=None,
        contract=None,
        adapters=[],
    )
    assert incomplete.compatible is False
    assert incomplete.execution_available is False
