"""Runtime API: profile, start, reads, ownership and cancellation."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.api.routes.runtime as runtime_routes
from app.domain.runtime.dependencies import dependency_issue
from app.models.runtime import RunnerCredential
from app.services import runtime_service
from tests import planning_helpers as ph
from tests.runtime_helpers import (
    SIMULATED_PROFILE,
    app_for,
    build_plan,
    case_for,
    start_run,
)


def _run_url(app_id: str, run_id) -> str:
    return f"/api/v1/applications/{app_id}/test-runs/{run_id}"


def test_http_dependency_url_is_resolved_from_contract_when_profile_field_is_missing():
    configuration = {
        "test_input": {
            "request": {"endpoint": "https://example.com/api/quote"},
        },
        "scenario_config": {},
    }

    upstream = runtime_service.dependency_upstream(
        configuration,
        {"http": {"advertised_host": "127.0.0.1"}},
    )
    rewritten = runtime_service.input_with_proxy(
        configuration,
        {"http": {"advertised_host": "127.0.0.1"}},
        "http://127.0.0.1:43127",
    )

    assert upstream == "https://example.com/api/quote"
    assert rewritten["request"]["endpoint"] == "http://127.0.0.1:43127/api/quote"


def test_dependency_issue_reports_missing_and_invalid_upstreams():
    missing = dependency_issue(
        {"test_input": {"order_id": "1"}, "scenario_config": {}}, {}
    )
    assert missing is not None and missing["code"] == "HTTP_DEPENDENCY_URL_MISSING"

    invalid = dependency_issue(
        {"scenario_config": {"dependency_url": "sandbox.example/quote"}}, {}
    )
    assert invalid is not None and invalid["code"] == "HTTP_DEPENDENCY_URL_INVALID"

    assert (
        dependency_issue(
            {"test_input": {"url": "https://sandbox.example/quote"}}, {}
        )
        is None
    )
    assert (
        dependency_issue(
            {"scenario_config": {"dependency_url": "https://sandbox.example/quote"}}, {}
        )
        is None
    )


def test_http_dependency_url_prefers_explicit_scenario_configuration():
    upstream = runtime_service.dependency_upstream(
        {
            "test_input": {"url": "https://contract.example/quote"},
            "scenario_config": {"dependency_url": "https://sandbox.example/quote"},
        },
        {},
    )

    assert upstream == "https://sandbox.example/quote"


def test_runtime_profile_round_trip_and_validation(client: TestClient):
    app_id, _key = ph.register_app(client, "runtime-profile")

    initial = client.get(f"/api/v1/applications/{app_id}/runtime-profile")
    assert initial.status_code == 200
    assert initial.json()["runtime_config"] is None

    saved = client.put(
        f"/api/v1/applications/{app_id}/runtime-profile", json=SIMULATED_PROFILE
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["runtime_config"]["queue"] == "veriq.test"

    secret = dict(SIMULATED_PROFILE)
    secret["env"] = {"DATABASE_PASSWORD": "hunter2"}
    rejected = client.put(
        f"/api/v1/applications/{app_id}/runtime-profile", json=secret
    )
    assert rejected.status_code == 422
    assert "credential" in rejected.text

    concurrency = dict(SIMULATED_PROFILE)
    concurrency["concurrency"] = 4
    rejected_concurrency = client.put(
        f"/api/v1/applications/{app_id}/runtime-profile", json=concurrency
    )
    assert rejected_concurrency.status_code == 422


def test_runtime_capabilities_are_reported(client: TestClient):
    app_id, _key = ph.register_app(client, "runtime-capabilities")
    response = client.get(f"/api/v1/applications/{app_id}/runner/capabilities")
    assert response.status_code == 200
    payload = response.json()
    assert payload["runner_enabled"] is True
    assert {item["scenario_id"] for item in payload["supported_scenarios"]} == {
        "dependency_timeout",
        "successful_operation_lost_response",
        "duplicate_message_delivery",
        "database_connection_interruption",
        "worker_termination",
    }
    assert payload["limits"]["total_seconds"] > 0
    assert "dedicated docker network" in payload["isolation"].lower()
    assert "not a security boundary" in payload["isolation"].lower()


def test_starting_requires_an_approved_revision(client: TestClient, db_session: Session):
    app_id, key = ph.register_app(client, "runtime-unapproved")
    task = ph.discover_task(client, key, "app.tasks.fetch_reference_data")
    ph.configure_adapter(
        client, app_id, name="http", adapter_type="http", triggers=("timeout_simulation",)
    )
    ph.create_contract(
        client,
        app_id,
        task["id"],
        {
            "safe_input": {"url": "http://127.0.0.1:9/x"},
            "assertions": [
                {
                    "id": "outcome",
                    "description": "terminal state",
                    "type": "execution_status",
                    "expected": "SUCCEEDED",
                }
            ],
            "cleanup": {"mode": "fixture_managed"},
        },
    )
    plan = ph.create_plan(client, app_id, "unapproved plan", [task["id"]])
    generated = ph.generate_plan(client, app_id, plan["id"])
    case = ph.plan_cases(client, app_id, plan["id"], generated["revision"]["revision"])[0]

    response = client.post(
        f"/api/v1/applications/{app_id}/test-plans/{plan['id']}/runs",
        json={"case_id": case["id"]},
    )
    assert response.status_code == 422, response.text
    codes = {issue["code"] for issue in response.json()["detail"]["issues"]}
    assert "PLAN_NOT_APPROVED" in codes
    assert client.get(f"/api/v1/applications/{app_id}/test-runs").json() == []


def test_start_read_cancel_and_ownership(
    client: TestClient, db_session: Session, monkeypatch
):
    monkeypatch.setattr(runtime_routes, "schedule_run", lambda run_id: True)
    fixture = build_plan(client, "runtime-api")
    case = case_for(fixture, "dependency_timeout")
    app_id = fixture["app_id"]

    started = client.post(
        f"/api/v1/applications/{app_id}/test-plans/{fixture['plan']['id']}/runs",
        json={"case_id": case["id"]},
    )
    assert started.status_code == 202, started.text
    payload = started.json()
    assert payload["scheduled"] is True
    assert payload["run"]["lifecycle_state"] == "PENDING"
    run_id = payload["run"]["id"]

    listed = client.get(f"/api/v1/applications/{app_id}/test-runs")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [run_id]

    detail = client.get(_run_url(app_id, run_id))
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["run"]["scenario_id"] == "dependency_timeout"
    assert body["configuration"]["test_input"]["url"].startswith("http")
    assert body["environment"] is None
    assert body["recovery"] is None

    verdict = client.get(f"{_run_url(app_id, run_id)}/verdict")
    assert verdict.status_code == 200
    assert verdict.json()["verdict"] is None
    assert verdict.json()["scope"] == "execution_recovery_only"

    assert client.get(f"{_run_url(app_id, run_id)}/environment").status_code == 404
    assert client.get(f"{_run_url(app_id, run_id)}/recovery").status_code == 404
    assert client.get(f"{_run_url(app_id, run_id)}/faults").json() == []
    assert client.get(f"{_run_url(app_id, run_id)}/workers").json() == []
    assert isinstance(client.get(f"{_run_url(app_id, run_id)}/events").json(), list)

    cancelled = client.post(f"{_run_url(app_id, run_id)}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    first_requested = cancelled.json()["run"]["cancel_requested_at"]
    assert first_requested is not None
    # Cancelling an already-cancelling run is idempotent, not destructive.
    again = client.post(f"{_run_url(app_id, run_id)}/cancel")
    assert again.status_code == 200
    assert again.json()["run"]["cancel_requested_at"] == first_requested

    # A run is never visible through another application.
    other_app, _key = ph.register_app(client, "runtime-api-other")
    assert client.get(_run_url(other_app, run_id)).status_code == 404
    assert client.post(f"{_run_url(other_app, run_id)}/cancel").status_code == 404
    assert client.get(f"/api/v1/applications/{other_app}/test-runs").json() == []


def test_start_by_case_key_and_unknown_case(client: TestClient, monkeypatch):
    monkeypatch.setattr(runtime_routes, "schedule_run", lambda run_id: True)
    fixture = build_plan(client, "runtime-api-case-key")
    case = case_for(fixture, "dependency_timeout")
    app_id = fixture["app_id"]

    started = client.post(
        f"/api/v1/applications/{app_id}/test-plans/{fixture['plan']['id']}/runs",
        json={"case_key": case["case_key"]},
    )
    assert started.status_code == 202, started.text

    missing = client.post(
        f"/api/v1/applications/{app_id}/test-plans/{fixture['plan']['id']}/runs",
        json={"case_key": "0" * 32},
    )
    assert missing.status_code == 404


def test_approval_alone_executes_nothing(client: TestClient):
    fixture = build_plan(client, "runtime-approval-only")
    assert fixture["cases"]
    assert client.get(f"/api/v1/applications/{fixture['app_id']}/test-runs").json() == []


def test_recover_interrupted_runs_endpoint(client: TestClient, db_session: Session):
    fixture = build_plan(client, "runtime-recover")
    case = case_for(fixture, "dependency_timeout")
    run = start_run(db_session, fixture, case)

    response = client.post(
        f"/api/v1/applications/{fixture['app_id']}/test-runs/recover-interrupted"
    )
    assert response.status_code == 200, response.text
    recovered = response.json()["recovered"]
    assert [item["run_id"] for item in recovered] == [str(run.id)]
    assert recovered[0]["lifecycle_state"] == "CANCELLED"
    assert recovered[0]["verdict"] == "INCONCLUSIVE"

    detail = client.get(_run_url(fixture["app_id"], run.id)).json()
    assert detail["run"]["lifecycle_state"] == "CANCELLED"
    # Nothing was provisioned, so there is no environment to clean.
    assert detail["environment"] is None
    assert any(
        event["event_type"] == "finalized" for event in detail["runtime_events"]
    )


def test_run_credential_authenticates_until_revoked(
    client: TestClient, db_session: Session
):
    """The isolated worker reports telemetry with a run-scoped key, not the app key."""

    fixture = build_plan(client, "runtime-credential")
    case = case_for(fixture, "dependency_timeout")
    run = start_run(db_session, fixture, case)
    secret = runtime_service.create_runner_credential(db_session, run)

    ping = client.get("/api/v1/observation/ping", headers={"X-API-Key": secret})
    assert ping.status_code == 200, ping.text
    assert ping.json()["target_app_id"] == fixture["app_id"]

    credential = db_session.scalar(
        select(RunnerCredential).where(RunnerCredential.test_case_run_id == run.id)
    )
    credential.revoked_at = datetime.now(timezone.utc)
    db_session.commit()

    revoked = client.get("/api/v1/observation/ping", headers={"X-API-Key": secret})
    assert revoked.status_code == 401
    # The application's own key is unaffected.
    assert (
        client.get("/api/v1/observation/ping", headers={"X-API-Key": fixture["api_key"]}).status_code
        == 200
    )
    assert secret not in (credential.api_key_hash or "")


def test_run_correlation_id_is_stable(client: TestClient, db_session: Session):
    fixture = build_plan(client, "runtime-correlation")
    case = case_for(fixture, "dependency_timeout")
    run = start_run(db_session, fixture, case)
    assert run.logical_job_id != run.id
    assert app_for(db_session, fixture).id == run.target_app_id
    assert uuid.UUID(run.configuration["case_id"]) == uuid.UUID(case["id"])
