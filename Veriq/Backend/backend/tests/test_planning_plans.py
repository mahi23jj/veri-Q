"""Scenario matrix generation and test plan review/approval."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.domain.compatibility.engine import CompatibilityResult
from app.domain.planning.matrix import EvaluatedCombination, generate_matrix
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


def _full_setup(client: TestClient, name: str, *, contract: bool = True):
    app_id, key = register_app(client, name)
    task = discover_task(client, key, "app.tasks.process_document")
    http_adapter = configure_adapter(
        client,
        app_id,
        name="http-sandbox",
        adapter_type="http",
        triggers=("timeout_simulation", "lost_response_simulation"),
    )
    db_adapter = configure_adapter(
        client,
        app_id,
        name="db-test",
        adapter_type="database",
        triggers=("connection_interruption",),
    )
    broker_adapter = configure_adapter(
        client, app_id, name="broker-test", adapter_type="broker", triggers=("duplicate_delivery",)
    )
    if contract:
        create_contract(
            client,
            app_id,
            task["id"],
            contract_body(
                measurement_adapter_id=db_adapter["id"],
                # HTTP failure scenarios need a dependency the fault proxy can
                # forward to; the safe input carries the sandbox endpoint.
                safe_input={
                    "document_id": "test-document-001",
                    "url": "https://sandbox.example/quote",
                },
            ),
        )
    for checkpoint in (
        "after_download",
        "after_extraction",
        "after_database_save",
        "after_event_published",
    ):
        report_checkpoint(
            client, key, task_name="app.tasks.process_document", checkpoint=checkpoint
        )
    return {
        "app_id": app_id,
        "key": key,
        "task": task,
        "http": http_adapter,
        "db": db_adapter,
        "broker": broker_adapter,
    }


def _checkpoints(client: TestClient, app_id: str) -> dict[str, dict]:
    return {
        checkpoint["name"]: checkpoint
        for checkpoint in client.get(f"/api/v1/applications/{app_id}/checkpoints").json()
    }


def test_matrix_contains_one_case_per_selected_combination(client: TestClient):
    setup = _full_setup(client, "matrix-basic")
    app_id, task = setup["app_id"], setup["task"]

    plan = create_plan(client, app_id, "baseline plan", [task["id"]])
    generated = generate_plan(client, app_id, plan["id"])
    assert generated["plan"]["status"] == "VALIDATING"
    assert generated["plan"]["current_revision"] == 1

    cases = plan_cases(client, app_id, plan["id"], 1)
    automatic = [case for case in cases if case["trigger_type"] == "automatic"]
    assert len(automatic) == 5
    assert {case["scenario_id"] for case in automatic} == {
        "dependency_timeout",
        "successful_operation_lost_response",
        "duplicate_message_delivery",
        "database_connection_interruption",
        "worker_termination",
    }
    assert all(case["status"] == "READY" for case in cases)
    assert all(case["checkpoint_name"] is None for case in automatic)

    case = next(c for c in automatic if c["scenario_id"] == "dependency_timeout")
    assert case["contract_version"] == 1
    assert case["test_input"] == {
        "document_id": "test-document-001",
        "url": "https://sandbox.example/quote",
    }
    assert case["adapter_refs"]
    assert case["configuration_fingerprint"]
    assert case["compatibility"]["status"] == "COMPATIBLE"
    # Executable by the runner once the revision is approved; generation alone
    # still executes nothing.
    assert case["compatibility"]["execution_available"] is True
    assert generated["summary"]["total_cases"] == len(cases)


def test_checkpoint_selection_generates_separate_cases(client: TestClient):
    setup = _full_setup(client, "matrix-checkpoints")
    app_id, task = setup["app_id"], setup["task"]
    checkpoints = _checkpoints(client, app_id)

    for name in checkpoints:
        enable_checkpoint(client, app_id, checkpoints[name]["id"])
    select_checkpoint_scenario(
        client,
        app_id,
        checkpoints["after_database_save"]["id"],
        "worker_termination",
        config={"termination_grace_seconds": 5},
    )
    select_checkpoint_scenario(
        client,
        app_id,
        checkpoints["after_event_published"]["id"],
        "worker_termination",
        assertion_overrides=[
            {
                "id": "execution_outcome",
                "description": "Event published exactly once",
                "type": "execution_status",
                "expected": "SUCCEEDED",
            }
        ],
    )
    select_checkpoint_scenario(
        client,
        app_id,
        checkpoints["after_database_save"]["id"],
        "duplicate_message_delivery",
        enabled=False,
    )

    plan = create_plan(client, app_id, "checkpoint plan", [task["id"]])
    generate_plan(client, app_id, plan["id"])
    cases = plan_cases(client, app_id, plan["id"], 1)

    checkpoint_cases = [case for case in cases if case["trigger_type"] == "checkpoint"]
    assert {(case["scenario_id"], case["checkpoint_name"]) for case in checkpoint_cases} == {
        ("worker_termination", "after_database_save"),
        ("worker_termination", "after_event_published"),
    }
    # Automatic selections are untouched and still generated once.
    automatic_worker = [
        case
        for case in cases
        if case["scenario_id"] == "worker_termination" and case["trigger_type"] == "automatic"
    ]
    assert len(automatic_worker) == 1
    assert len({case["case_key"] for case in cases}) == len(cases)

    # Checkpoint assertion overrides extend the task-level defaults.
    published = next(
        case for case in checkpoint_cases if case["checkpoint_name"] == "after_event_published"
    )
    outcome = next(a for a in published["assertions"] if a["id"] == "execution_outcome")
    assert outcome["expected"] == "SUCCEEDED"
    saved = next(
        case for case in checkpoint_cases if case["checkpoint_name"] == "after_database_save"
    )
    saved_outcome = next(a for a in saved["assertions"] if a["id"] == "execution_outcome")
    assert saved_outcome["expected"] == "FAILED"
    # Scenario configuration is part of the reproducible case, and differs per
    # injection point.
    assert saved["scenario_config"] == {"termination_grace_seconds": 5}
    assert not published["scenario_config"]


def test_blocked_checkpoint_selection_marks_plan_needs_changes(client: TestClient):
    setup = _full_setup(client, "matrix-blocked")
    app_id, task = setup["app_id"], setup["task"]
    checkpoints = _checkpoints(client, app_id)
    # Select at a checkpoint but never enable reliability testing for it.
    select_checkpoint_scenario(
        client, app_id, checkpoints["after_download"]["id"], "worker_termination"
    )

    plan = create_plan(client, app_id, "blocked plan", [task["id"]])
    generated = generate_plan(client, app_id, plan["id"])
    assert generated["plan"]["status"] == "NEEDS_CHANGES"

    blocked = [case for case in plan_cases(client, app_id, plan["id"], 1) if case["status"] == "BLOCKED"]
    assert len(blocked) == 1
    assert blocked[0]["trigger_type"] == "checkpoint"
    assert any(
        reason["code"] == "CHECKPOINT_NOT_ENABLED"
        for reason in blocked[0]["compatibility"]["reasons"]
    )

    assert (
        client.post(f"/api/v1/applications/{app_id}/test-plans/{plan['id']}/submit").status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/applications/{app_id}/test-plans/{plan['id']}/approve",
            json={"revision": 1},
        ).status_code
        == 409
    )


def test_approval_lifecycle_authorises_without_executing(client: TestClient):
    setup = _full_setup(client, "plan-lifecycle")
    app_id, task = setup["app_id"], setup["task"]
    plan = create_plan(client, app_id, "lifecycle", [task["id"]])

    # Approval before generation is refused.
    assert (
        client.post(f"/api/v1/applications/{app_id}/test-plans/{plan['id']}/approve", json={"revision": 1}).status_code
        == 409
    )

    executions_before = client.get(
        "/api/v1/task-executions", params={"target_app_id": app_id}
    ).json()
    workers_before = client.get("/api/v1/workers", params={"target_app_id": app_id}).json()

    generate_plan(client, app_id, plan["id"])
    validation = client.post(
        f"/api/v1/applications/{app_id}/test-plans/{plan['id']}/validate"
    ).json()
    assert validation["ok"] is True, validation
    assert validation["total_cases"] == 5
    assert validation["blocked_cases"] == 0

    submitted = client.post(
        f"/api/v1/applications/{app_id}/test-plans/{plan['id']}/submit"
    ).json()
    assert submitted["status"] == "READY_FOR_REVIEW"

    wrong_revision = client.post(
        f"/api/v1/applications/{app_id}/test-plans/{plan['id']}/approve",
        json={"revision": 2},
    )
    assert wrong_revision.status_code == 409

    approved = client.post(
        f"/api/v1/applications/{app_id}/test-plans/{plan['id']}/approve",
        json={"revision": 1},
    ).json()
    assert approved["status"] == "APPROVED"
    assert approved["approved_revision"] == 1
    assert approved["ready_for_execution"] is True
    assert approved["execution_available"] is False

    # Approval executes nothing: telemetry totals are exactly those produced by
    # the checkpoint discovery reports made before planning.
    executions_after = client.get(
        "/api/v1/task-executions", params={"target_app_id": app_id}
    ).json()
    assert executions_after["total"] == executions_before["total"]
    assert (
        client.get("/api/v1/workers", params={"target_app_id": app_id}).json()["total"]
        == workers_before["total"]
    )

    # A second approval of an already-approved plan is a state error.
    assert (
        client.post(
            f"/api/v1/applications/{app_id}/test-plans/{plan['id']}/approve",
            json={"revision": 1},
        ).status_code
        == 409
    )

    revoked = client.post(
        f"/api/v1/applications/{app_id}/test-plans/{plan['id']}/revoke"
    ).json()
    assert revoked["status"] == "READY_FOR_REVIEW"
    assert revoked["approved_revision"] is None
    assert revoked["ready_for_execution"] is False


def test_contract_change_invalidates_approval_and_keeps_history(client: TestClient):
    setup = _full_setup(client, "plan-drift")
    app_id, task = setup["app_id"], setup["task"]
    contract = client.get(
        f"/api/v1/applications/{app_id}/registered-tasks/{task['id']}/contract"
    ).json()

    plan = create_plan(client, app_id, "drift", [task["id"]])
    generate_plan(client, app_id, plan["id"])
    client.post(f"/api/v1/applications/{app_id}/test-plans/{plan['id']}/submit")
    client.post(
        f"/api/v1/applications/{app_id}/test-plans/{plan['id']}/approve",
        json={"revision": 1},
    )

    updated = client.patch(
        f"/api/v1/applications/{app_id}/contracts/{contract['id']}",
        json=contract_body(
            measurement_adapter_id=setup["db"]["id"],
            safe_input={"document_id": "test-document-002"},
        ),
    )
    assert updated.json()["version"] == 2

    validation = client.post(
        f"/api/v1/applications/{app_id}/test-plans/{plan['id']}/validate"
    ).json()
    assert validation["ok"] is False
    assert validation["drift"]
    plan_after = validation["plan"]
    assert plan_after["status"] == "NEEDS_CHANGES"
    assert plan_after["approved_revision"] is None

    # Historical revision keeps the original contract version snapshot.
    old_cases = plan_cases(client, app_id, plan["id"], 1)
    assert {case["contract_version"] for case in old_cases} == {1}
    assert {case["test_input"]["document_id"] for case in old_cases} == {"test-document-001"}

    generated = generate_plan(client, app_id, plan["id"])
    assert generated["revision"]["revision"] == 2
    new_cases = plan_cases(client, app_id, plan["id"], 2)
    assert {case["contract_version"] for case in new_cases} == {2}
    # Revision 1 is retained unchanged and marked as superseded.
    revision_one = client.get(
        f"/api/v1/applications/{app_id}/test-plans/{plan['id']}/revisions/1"
    ).json()
    assert revision_one["invalidated_at"] is not None


def test_plan_edit_requires_new_review(client: TestClient):
    setup = _full_setup(client, "plan-edit")
    app_id, task = setup["app_id"], setup["task"]
    plan = create_plan(client, app_id, "edit", [task["id"]])
    generate_plan(client, app_id, plan["id"])
    client.post(f"/api/v1/applications/{app_id}/test-plans/{plan['id']}/submit")
    client.post(
        f"/api/v1/applications/{app_id}/test-plans/{plan['id']}/approve", json={"revision": 1}
    )

    updated = client.patch(
        f"/api/v1/applications/{app_id}/test-plans/{plan['id']}", json={"name": "renamed"}
    ).json()
    assert updated["status"] == "DRAFT"
    assert updated["approved_revision"] is None
    assert updated["ready_for_execution"] is False


def test_empty_plan_cannot_be_submitted(client: TestClient):
    setup = _full_setup(client, "plan-empty", contract=False)
    app_id, task = setup["app_id"], setup["task"]
    plan = create_plan(client, app_id, "no contract", [task["id"]])

    generated = generate_plan(client, app_id, plan["id"])
    assert generated["summary"]["total_cases"] == 0
    assert generated["plan"]["status"] == "NEEDS_CHANGES"
    assert (
        client.post(f"/api/v1/applications/{app_id}/test-plans/{plan['id']}/submit").status_code
        == 409
    )
    validation = client.post(
        f"/api/v1/applications/{app_id}/test-plans/{plan['id']}/validate"
    ).json()
    assert validation["ok"] is False


def test_dependency_scenario_without_an_upstream_is_blocked(client: TestClient):
    """No upstream URL means the fault proxy could never activate the fault."""
    setup = _full_setup(client, "dep-blocked")
    app_id, task = setup["app_id"], setup["task"]
    contract = client.get(
        f"/api/v1/applications/{app_id}/registered-tasks/{task['id']}/contract"
    ).json()
    client.patch(
        f"/api/v1/applications/{app_id}/contracts/{contract['id']}",
        json=contract_body(
            measurement_adapter_id=setup["db"]["id"],
            safe_input={"document_id": "test-document-001"},
        ),
    )

    plan = create_plan(client, app_id, "dependency blocked", [task["id"]])
    generated = generate_plan(client, app_id, plan["id"])
    assert generated["plan"]["status"] == "NEEDS_CHANGES"

    cases = plan_cases(client, app_id, plan["id"], 1)
    dependency_cases = [
        case
        for case in cases
        if case["scenario_id"]
        in ("dependency_timeout", "successful_operation_lost_response")
    ]
    assert dependency_cases
    for case in dependency_cases:
        assert case["status"] == "BLOCKED"
        assert "HTTP_DEPENDENCY_URL_MISSING" in {
            reason["code"] for reason in case["compatibility"]["reasons"]
        }
    # Scenarios that need no upstream are unaffected.
    assert any(case["status"] == "READY" for case in cases)

    blocked = client.post(
        f"/api/v1/applications/{app_id}/test-plans/{plan['id']}/submit"
    )
    assert blocked.status_code == 409


def test_dependency_scenario_warns_when_nothing_points_the_task_at_the_proxy(
    client: TestClient,
):
    """A configured upstream is not enough: the task's request must be routed."""
    setup = _full_setup(client, "dep-not-routed")
    app_id, task = setup["app_id"], setup["task"]
    contract = client.get(
        f"/api/v1/applications/{app_id}/registered-tasks/{task['id']}/contract"
    ).json()
    client.patch(
        f"/api/v1/applications/{app_id}/contracts/{contract['id']}",
        json=contract_body(
            measurement_adapter_id=setup["db"]["id"],
            safe_input={"document_id": "test-document-001"},
        ),
    )
    client.put(
        f"/api/v1/applications/{app_id}/registered-tasks/{task['id']}/scenarios/dependency_timeout",
        json={
            "enabled": True,
            "config": {"dependency_url": "https://sandbox.example/quote"},
        },
    )

    plan = create_plan(client, app_id, "dependency not routed", [task["id"]])
    generate_plan(client, app_id, plan["id"])
    case = next(
        c
        for c in plan_cases(client, app_id, plan["id"], 1)
        if c["scenario_id"] == "dependency_timeout"
    )
    assert case["status"] == "READY"
    assert "HTTP_PROXY_NOT_ROUTED" in {
        warning["code"] for warning in case["compatibility"]["warnings"]
    }


def test_scenario_configuration_rejects_a_relative_dependency_url(client: TestClient):
    setup = _full_setup(client, "dep-invalid-url")
    app_id, task = setup["app_id"], setup["task"]

    rejected = client.put(
        f"/api/v1/applications/{app_id}/registered-tasks/{task['id']}/scenarios/dependency_timeout",
        json={"enabled": True, "config": {"dependency_url": "sandbox.example/quote"}},
    )
    assert rejected.status_code == 422, rejected.text
    assert "absolute http(s) URL" in rejected.text


def test_disabled_automatic_scenario_is_not_generated(client: TestClient):
    setup = _full_setup(client, "plan-optout")
    app_id, task = setup["app_id"], setup["task"]
    select_task_scenario(client, app_id, task["id"], "duplicate_message_delivery", False)

    plan = create_plan(client, app_id, "opt out", [task["id"]])
    generate_plan(client, app_id, plan["id"])
    scenarios = {case["scenario_id"] for case in plan_cases(client, app_id, plan["id"], 1)}
    assert "duplicate_message_delivery" not in scenarios
    assert "dependency_timeout" in scenarios


def test_plans_are_scoped_to_the_application(client: TestClient):
    setup = _full_setup(client, "plan-scope-a")
    app_id, task = setup["app_id"], setup["task"]
    other_app, _key = register_app(client, "plan-scope-b")
    plan = create_plan(client, app_id, "scoped", [task["id"]])

    assert client.get(f"/api/v1/applications/{other_app}/test-plans").json() == []
    assert (
        client.get(f"/api/v1/applications/{other_app}/test-plans/{plan['id']}").status_code == 404
    )
    assert (
        client.post(
            f"/api/v1/applications/{other_app}/test-plans/{plan['id']}/generate"
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/applications/{other_app}/test-plans",
            json={"name": "foreign", "task_ids": [task["id"]]},
        ).status_code
        == 404
    )


# ---------------------------------------------------------------------------
# Pure matrix generation
# ---------------------------------------------------------------------------


def _combination(**overrides) -> EvaluatedCombination:
    base = dict(
        target_app_id="app-1",
        task_id="task-1",
        task_name="app.tasks.process_document",
        scenario_id="worker_termination",
        scenario_version=1,
        scenario_name="Worker termination during execution",
        scenario_category="runtime",
        trigger_type="automatic",
        checkpoint_id=None,
        checkpoint_name=None,
        contract_id="contract-1",
        contract_version=1,
        safe_input={"document_id": "test-document-001"},
        input_fixture_ref=None,
        assertions=(),
        cleanup={"mode": "fixture_managed"},
        adapter_refs=(),
        compatibility=CompatibilityResult(
            status="COMPATIBLE",
            reasons=(),
            selected_adapters=(),
            scenario_id="worker_termination",
            scenario_version=1,
            trigger_type="automatic",
        ),
    )
    base.update(overrides)
    return EvaluatedCombination(**base)  # type: ignore[arg-type]


def test_matrix_deduplicates_identical_configurations():
    first = _combination()
    second = _combination()
    matrix = generate_matrix([first, second])
    assert len(matrix.rows) == 1
    assert len(matrix.duplicates) == 1
    assert matrix.duplicates[0]["same_as_case_key"] == matrix.rows[0].case_key
    assert "identical" in matrix.duplicates[0]["reason"]


def test_matrix_keeps_distinct_scenario_configuration_apart():
    base = _combination()
    configured = _combination(scenario_config={"termination_grace_seconds": 5})
    matrix = generate_matrix([base, configured])
    assert len(matrix.rows) == 2
    assert {tuple(sorted(row.combination.scenario_config)) for row in matrix.rows} == {
        (),
        ("termination_grace_seconds",),
    }


def test_matrix_keeps_distinct_injection_points_apart():
    automatic = _combination()
    at_checkpoint = _combination(
        trigger_type="checkpoint",
        checkpoint_id="cp-1",
        checkpoint_name="after_database_save",
    )
    matrix = generate_matrix([automatic, at_checkpoint])
    assert len(matrix.rows) == 2
    assert {row.combination.checkpoint_name for row in matrix.rows} == {
        None,
        "after_database_save",
    }
    assert matrix.duplicates == ()


def test_matrix_rows_are_reproducible_and_ordered():
    combinations = [
        _combination(task_name="b.task"),
        _combination(task_name="a.task"),
        _combination(scenario_id="dependency_timeout", scenario_name="Dependency timeout"),
    ]
    first = generate_matrix(combinations)
    second = generate_matrix(list(reversed(combinations)))
    assert [row.case_key for row in first.rows] == [row.case_key for row in second.rows]
    assert [row.combination.task_name for row in first.rows] == [
        "a.task",
        "app.tasks.process_document",
        "b.task",
    ]
