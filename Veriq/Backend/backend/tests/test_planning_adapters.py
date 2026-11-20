"""Adapter registry: types, capabilities, application configuration, validation."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.planning_helpers import configure_adapter, register_app


def test_builtin_adapter_types_expose_capabilities(client: TestClient):
    types = client.get("/api/v1/adapter-types").json()
    by_slug = {adapter["slug"]: adapter for adapter in types}
    assert {"http", "database", "broker", "object_storage"} <= set(by_slug)
    assert all(adapter["builtin"] is True for adapter in types)

    http = by_slug["http"]
    assert "failure_trigger" in http["capabilities"]
    assert "effect_measurement" in http["capabilities"]
    assert {"timeout_simulation", "lost_response_simulation"} <= set(
        http["supported_triggers"]
    )
    # The HTTP adapter cannot claim storage cleanup.
    assert "resource_cleanup" not in http["capabilities"]

    broker = by_slug["broker"]
    assert "duplicate_delivery" in broker["supported_triggers"]
    assert "effect_measurement" not in broker["capabilities"]


def test_configured_adapter_derives_type_capabilities(client: TestClient):
    app_id, _key = register_app(client, "adapter-config")
    adapter = client.post(
        f"/api/v1/applications/{app_id}/adapters",
        json={
            "name": "http-sandbox",
            "adapter_type": "http",
            "enabled_triggers": ["timeout_simulation"],
            "configuration_ref": "cfg://sandbox/http",
        },
    ).json()
    assert adapter["status"] == "CONFIGURED"
    assert adapter["category"] == "http"
    assert "effect_measurement" in adapter["capabilities"]
    # Configuration alone is not availability.
    assert adapter["validation"] is None


def test_adapter_validation_is_metadata_only(client: TestClient):
    app_id, _key = register_app(client, "adapter-validate")
    adapter = configure_adapter(
        client, app_id, name="db-test", adapter_type="database", triggers=("connection_interruption",)
    )
    assert adapter["status"] == "VALIDATED"
    assert adapter["validated_at"] is not None
    validation = adapter["validation"]
    assert validation["valid"] is True
    assert validation["operational"] is False
    checks = {check["check"]: check for check in validation["checks"]}
    assert checks["adapter_type_supported"]["ok"] is True
    # Connectivity is explicitly deferred, never claimed.
    assert checks["connectivity_verification"]["ok"] is False
    assert "deferred_to_runner" in checks["connectivity_verification"]["detail"]


def test_missing_configuration_is_detected(client: TestClient):
    app_id, _key = register_app(client, "adapter-missing-config")
    created = client.post(
        f"/api/v1/applications/{app_id}/adapters",
        json={"name": "bare", "adapter_type": "object_storage"},
    ).json()
    validated = client.post(
        f"/api/v1/applications/{app_id}/adapters/{created['id']}/validate"
    ).json()
    checks = {check["check"]: check for check in validated["validation"]["checks"]}
    assert checks["configuration_reference_present"]["ok"] is False


def test_unsupported_capability_or_trigger_is_rejected(client: TestClient):
    app_id, _key = register_app(client, "adapter-reject")
    base = f"/api/v1/applications/{app_id}/adapters"

    bad_capability = client.post(
        base,
        json={
            "name": "broker-cleanup",
            "adapter_type": "broker",
            "capabilities": ["resource_cleanup"],
        },
    )
    assert bad_capability.status_code == 422

    bad_trigger = client.post(
        base,
        json={
            "name": "storage-timeout",
            "adapter_type": "object_storage",
            "enabled_triggers": ["timeout_simulation"],
        },
    )
    assert bad_trigger.status_code == 422

    unknown_type = client.post(base, json={"name": "nope", "adapter_type": "graphql"})
    assert unknown_type.status_code == 422


def test_custom_adapter_type_can_be_registered_and_configured(client: TestClient):
    app_id, _key = register_app(client, "adapter-custom")
    definition = client.post(
        f"/api/v1/applications/{app_id}/adapter-definitions",
        json={
            "slug": "redis_streams",
            "name": "Redis Streams observer",
            "category": "broker",
            "description": "Application-specific broker observation",
            "capabilities": ["dependency_observation", "environment_validation"],
            "supported_triggers": ["duplicate_delivery"],
        },
    )
    assert definition.status_code == 201, definition.text
    assert definition.json()["builtin"] is False

    types = {
        adapter["slug"]: adapter
        for adapter in client.get(f"/api/v1/applications/{app_id}/adapter-types").json()
    }
    assert "redis_streams" in types

    adapter = configure_adapter(
        client,
        app_id,
        name="streams",
        adapter_type="redis_streams",
        triggers=("duplicate_delivery",),
    )
    assert adapter["adapter_type"] == "redis_streams"
    assert "dependency_observation" in adapter["capabilities"]

    # Custom types do not leak to other applications.
    other_id, _other_key = register_app(client, "adapter-custom-other")
    other_types = {
        adapter["slug"]
        for adapter in client.get(f"/api/v1/applications/{other_id}/adapter-types").json()
    }
    assert "redis_streams" not in other_types


def test_adapter_update_resets_validation(client: TestClient):
    app_id, _key = register_app(client, "adapter-reset")
    adapter = configure_adapter(
        client, app_id, name="http-sandbox", adapter_type="http", triggers=("timeout_simulation",)
    )
    updated = client.patch(
        f"/api/v1/applications/{app_id}/adapters/{adapter['id']}",
        json={"enabled_triggers": ["timeout_simulation", "lost_response_simulation"]},
    ).json()
    assert updated["status"] == "CONFIGURED"
    assert updated["validation"] is None
    assert set(updated["enabled_triggers"]) == {
        "timeout_simulation",
        "lost_response_simulation",
    }


def test_adapters_are_scoped_to_the_application(client: TestClient):
    app_a, _key_a = register_app(client, "adapter-scope-a")
    app_b, _key_b = register_app(client, "adapter-scope-b")
    adapter = configure_adapter(client, app_a, name="http-a", adapter_type="http")

    assert client.get(f"/api/v1/applications/{app_b}/adapters").json() == []
    assert (
        client.post(
            f"/api/v1/applications/{app_b}/adapters/{adapter['id']}/validate"
        ).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/v1/applications/{app_b}/adapters/{adapter['id']}",
            json={"enabled_triggers": []},
        ).status_code
        == 404
    )


def test_duplicate_adapter_name_rejected(client: TestClient):
    app_id, _key = register_app(client, "adapter-duplicate")
    configure_adapter(client, app_id, name="http-sandbox", adapter_type="http")
    resp = client.post(
        f"/api/v1/applications/{app_id}/adapters",
        json={"name": "http-sandbox", "adapter_type": "http"},
    )
    assert resp.status_code == 409
