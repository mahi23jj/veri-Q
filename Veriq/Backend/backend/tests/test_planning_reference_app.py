"""Planning workflow against the real `celery-target-app` tasks and checkpoints.

Task names and checkpoint names below are copied from
`examples/celery-target-app/app/tasks.py`. They reach the backend only through
SDK-shaped discovery/telemetry payloads — the backend never hardcodes them, and
this test does not run Celery, Redis or Docker.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.planning_helpers import (
    configure_adapter,
    contract_body,
    create_contract,
    create_plan,
    discover_task,
    enable_checkpoint,
    generate_plan,
    plan_cases,
    register_app,
    report_checkpoint,
    select_checkpoint_scenario,
    select_task_scenario,
)

HTTP_TASK = "app.tasks.fetch_reference_data"
DB_TASK = "app.tasks.record_document"


def _compat(client: TestClient, app_id: str, **selection) -> dict:
    resp = client.post(
        f"/api/v1/applications/{app_id}/compatibility/evaluate",
        json={"selections": [selection]},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["results"][0]


def test_reference_app_planning_workflow(client: TestClient):
    app_id, key = register_app(client, "celery-target-app-planning")
    http_task = discover_task(client, key, HTTP_TASK)
    db_task = discover_task(client, key, DB_TASK)

    # The SDK reports the checkpoints that actually exist in the example app.
    for checkpoint in ("before_http_request", "after_http_response"):
        report_checkpoint(client, key, task_name=HTTP_TASK, checkpoint=checkpoint)
    for checkpoint in ("before_database_save", "after_database_save"):
        report_checkpoint(client, key, task_name=DB_TASK, checkpoint=checkpoint)

    checkpoints = {
        checkpoint["name"]: checkpoint
        for checkpoint in client.get(f"/api/v1/applications/{app_id}/checkpoints").json()
    }
    assert {"before_http_request", "after_http_response", "after_database_save"} <= set(
        checkpoints
    )

    # 1. HTTP adapter only: the HTTP task can be planned for timeouts.
    http_adapter = configure_adapter(
        client,
        app_id,
        name="target-http",
        adapter_type="http",
        triggers=("timeout_simulation", "lost_response_simulation"),
    )
    fetch_contract = create_contract(
        client,
        app_id,
        http_task["id"],
        contract_body(
            measurement_adapter_id=None,
            include_measurement=False,
            safe_input={"url": "https://example.com/sandbox"},
        ),
    )
    assert fetch_contract["validation"]["valid"] is True

    timeout = _compat(
        client,
        app_id,
        task_id=http_task["id"],
        scenario_id="dependency_timeout",
        trigger_type="automatic",
    )
    assert timeout["status"] == "COMPATIBLE", timeout

    lost_response = _compat(
        client,
        app_id,
        task_id=http_task["id"],
        scenario_id="successful_operation_lost_response",
        trigger_type="automatic",
    )
    assert lost_response["status"] == "NEEDS_CONFIGURATION"
    assert any(
        reason["code"] == "MISSING_EFFECT_MEASUREMENT"
        for reason in lost_response["reasons"]
    )

    # 2. The database task has no contract yet: different outcome, same catalog.
    db_adapter = configure_adapter(
        client,
        app_id,
        name="target-db",
        adapter_type="database",
        triggers=("connection_interruption",),
    )
    missing_contract = _compat(
        client,
        app_id,
        task_id=db_task["id"],
        scenario_id="database_connection_interruption",
        trigger_type="automatic",
    )
    assert missing_contract["status"] == "NEEDS_CONFIGURATION"
    assert any(
        reason["code"] == "CONTRACT_MISSING" for reason in missing_contract["reasons"]
    )

    record_contract = create_contract(
        client,
        app_id,
        db_task["id"],
        contract_body(
            measurement_adapter_id=db_adapter["id"],
            safe_input={"document_id": "test-document-001"},
            cleanup={"mode": "fixture_managed", "description": "delete test-owned row"},
        ),
    )
    assert record_contract["validation"]["valid"] is True

    # 3. Duplicate delivery needs a broker adapter and its trigger.
    duplicate_without_broker = _compat(
        client,
        app_id,
        task_id=db_task["id"],
        scenario_id="duplicate_message_delivery",
        trigger_type="automatic",
    )
    assert duplicate_without_broker["status"] == "NEEDS_CONFIGURATION"
    assert any(
        reason["code"] == "ADAPTER_NOT_CONFIGURED"
        for reason in duplicate_without_broker["reasons"]
    )

    configure_adapter(
        client,
        app_id,
        name="target-broker",
        adapter_type="broker",
        triggers=("duplicate_delivery",),
    )
    duplicate = _compat(
        client,
        app_id,
        task_id=db_task["id"],
        scenario_id="duplicate_message_delivery",
        trigger_type="automatic",
    )
    assert duplicate["status"] == "COMPATIBLE", duplicate

    # 4. Checkpoint-based worker termination at the real checkpoint name.
    enable_checkpoint(client, app_id, checkpoints["after_database_save"]["id"])
    select_checkpoint_scenario(
        client,
        app_id,
        checkpoints["after_database_save"]["id"],
        "worker_termination",
    )
    termination = _compat(
        client,
        app_id,
        task_id=db_task["id"],
        scenario_id="worker_termination",
        trigger_type="checkpoint",
        checkpoint_id=checkpoints["after_database_save"]["id"],
    )
    assert termination["status"] == "COMPATIBLE", termination

    # 5. Keep the matrix focused: opt out of scenarios these tasks do not exercise.
    for task in (http_task, db_task):
        for scenario_id in (
            "dependency_timeout",
            "successful_operation_lost_response",
            "duplicate_message_delivery",
            "database_connection_interruption",
            "worker_termination",
        ):
            select_task_scenario(client, app_id, task["id"], scenario_id, False)
    select_task_scenario(client, app_id, http_task["id"], "dependency_timeout", True)
    select_task_scenario(client, app_id, db_task["id"], "duplicate_message_delivery", True)
    select_task_scenario(
        client, app_id, db_task["id"], "database_connection_interruption", True
    )

    # 6. Generate, validate, review and approve.
    plan = create_plan(client, app_id, "reference app plan", [http_task["id"], db_task["id"]])
    generated = generate_plan(client, app_id, plan["id"])
    assert generated["plan"]["status"] == "VALIDATING"
    summary = generated["summary"]
    assert summary["total_cases"] == 4
    assert summary["blocked_cases"] == 0

    cases = plan_cases(client, app_id, plan["id"], 1)
    assert {(case["task_name"], case["scenario_id"], case["trigger_type"]) for case in cases} == {
        (HTTP_TASK, "dependency_timeout", "automatic"),
        (DB_TASK, "duplicate_message_delivery", "automatic"),
        (DB_TASK, "database_connection_interruption", "automatic"),
        (DB_TASK, "worker_termination", "checkpoint"),
    }
    checkpoint_case = next(case for case in cases if case["trigger_type"] == "checkpoint")
    assert checkpoint_case["checkpoint_name"] == "after_database_save"

    validation = client.post(
        f"/api/v1/applications/{app_id}/test-plans/{plan['id']}/validate"
    ).json()
    assert validation["ok"] is True, validation

    assert (
        client.post(f"/api/v1/applications/{app_id}/test-plans/{plan['id']}/submit").json()[
            "status"
        ]
        == "READY_FOR_REVIEW"
    )
    approved = client.post(
        f"/api/v1/applications/{app_id}/test-plans/{plan['id']}/approve",
        json={"revision": 1},
    ).json()
    assert approved["status"] == "APPROVED"
    assert approved["ready_for_execution"] is True
    assert approved["execution_available"] is False

    # Planning produced no new task executions beyond the checkpoint telemetry.
    executions = client.get(
        "/api/v1/task-executions", params={"target_app_id": app_id}
    ).json()
    assert executions["total"] == 4
    assert all(
        execution["status"] == "RUNNING" for execution in executions["items"]
    )
