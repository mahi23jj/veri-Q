"""End-to-end check of the reliability runner against real infrastructure.

This script is deliberately outside the test suite: it drives a *running* VeriQ
backend (with Docker available) and a real target-application image, so it
provisions real containers, kills a real worker and inspects the verdict.

Usage (from `backend/`, with the backend already running and migrated):

    python scripts/runtime_e2e.py --api-url http://127.0.0.1:8000 \
        --image veriq-celery-target-worker:latest

The backend must be able to reach the target worker's telemetry callback and
the worker must be able to reach the backend, so run the backend with
``RUNNER_CALLBACK_BASE_URL=http://host.docker.internal:8000`` (the default) on a
machine where ``host.docker.internal`` resolves from inside containers.

Everything it creates is namespaced by an app name containing a timestamp; the
script never touches an existing application.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}


def _request(
    method: str, url: str, body: dict[str, Any] | None = None, key: str | None = None
) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if key:
        request.add_header("X-API-Key", key)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise SystemExit(f"{method} {url} -> HTTP {exc.code}: {detail}") from exc
    return json.loads(payload) if payload else None


def _wait(label: str, predicate, timeout_seconds: float, interval: float = 2.0):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise SystemExit(f"timed out after {timeout_seconds:.0f}s waiting for {label}")


def _start_discovery_broker() -> str:
    """A throwaway Redis so a real worker can reach ``worker_ready``."""

    subprocess.run(
        ["docker", "rm", "-f", "veriq-e2e-discovery-redis"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            "veriq-e2e-discovery-redis",
            "-p",
            "63790:6379",
            "redis:7-alpine",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    for _ in range(30):
        ready = subprocess.run(
            ["docker", "exec", "veriq-e2e-discovery-redis", "redis-cli", "ping"],
            capture_output=True,
            text=True,
        )
        if "PONG" in ready.stdout:
            break
        time.sleep(1)
    return "redis://host.docker.internal:63790/0"


def _discover(
    args: argparse.Namespace, api_url: str, api_key: str, broker_url: str
) -> None:
    """Run the target image briefly so its worker reports discovery."""

    command = [
        "docker",
        "run",
        "--rm",
        "--name",
        f"veriq-e2e-discovery-{uuid.uuid4().hex[:8]}",
        "--add-host",
        "host.docker.internal:host-gateway",
        "-e",
        f"VERIQ_API_URL={args.discovery_api_url or api_url}",
        "-e",
        f"VERIQ_API_KEY={api_key}",
        "-e",
        f"VERIQ_QUEUE={args.queue}",
        "-e",
        f"CELERY_BROKER_URL={broker_url}",
        args.image,
        "celery",
        "-A",
        "app.worker",
        "worker",
        "-Q",
        args.queue,
        "--loglevel=INFO",
        "--concurrency=1",
    ]
    print(f"  discovery worker: docker run {args.image} ...")
    process = subprocess.Popen(
        command, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT
    )
    try:
        time.sleep(args.discovery_seconds)
    finally:
        process.terminate()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--discovery-api-url",
        default=None,
        help="Backend URL as seen from inside a container (defaults to --api-url)",
    )
    parser.add_argument("--image", default="veriq-celery-target-worker:latest")
    parser.add_argument("--queue", default="veriq.test")
    parser.add_argument("--task", default="app.tasks.slow_operation")
    parser.add_argument("--scenario", default="worker_termination")
    parser.add_argument("--slow-seconds", type=float, default=6.0)
    parser.add_argument("--discovery-seconds", type=float, default=15.0)
    parser.add_argument(
        "--discovery-broker",
        default=None,
        help="Broker URL for the discovery worker (defaults to a temporary Redis)",
    )
    parser.add_argument("--run-timeout", type=float, default=420.0)
    args = parser.parse_args()

    api = args.api_url.rstrip("/") + "/api/v1"
    app_name = f"runtime-e2e-{int(time.time())}"

    print(f"1. register application {app_name}")
    created = _request("POST", f"{api}/applications", {"name": app_name, "environment": "test"})
    app_id = created["id"]
    api_key = created["api_key"]

    print("2. configure the Docker runtime profile")
    profile = {
        "runtime_type": "docker",
        "image": args.image,
        "queue": args.queue,
        "concurrency": 1,
        "broker_image": "redis:7-alpine",
        "database_image": "postgres:16-alpine",
        "http": {
            "url_env": "TARGET_PAYMENT_URL",
            "upstream_url": "http://mock-payment-service",
            "advertised_host": "127.0.0.1",
        },
        "env": {
            "CELERY_TASK_ACKS_LATE": "true",
            "CELERY_TASK_REJECT_ON_WORKER_LOST": "true",
            "CELERY_VISIBILITY_TIMEOUT": "10",
            "TARGET_SQLITE_PATH": "/tmp/veriq-target.db",
        },
    }
    _request("PUT", f"{api}/applications/{app_id}/runtime-profile", profile)

    print("3. discover the task from a real worker of the same image")
    broker_url = args.discovery_broker or _start_discovery_broker()
    try:
        _discover(args, args.api_url, api_key, broker_url)
    finally:
        if not args.discovery_broker:
            subprocess.run(
                ["docker", "rm", "-f", "veriq-e2e-discovery-redis"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def _task_id() -> str | None:
        tasks = _request("GET", f"{api}/applications/{app_id}/registered-tasks")["items"]
        for task in tasks:
            if task["task_name"] == args.task:
                return task["id"]
        return None

    task_id = _wait("task discovery", _task_id, args.discovery_seconds + 60)
    print(f"   registered task {task_id}")

    print("4. register the adapters the scenarios declare")
    for name, adapter_type, triggers in (
        ("http-sandbox", "http", ["timeout_simulation", "lost_response_simulation"]),
        ("db-sandbox", "database", ["connection_interruption"]),
        ("broker-sandbox", "broker", ["duplicate_delivery"]),
    ):
        adapter = _request(
            "POST",
            f"{api}/applications/{app_id}/adapters",
            {
                "name": name,
                "adapter_type": adapter_type,
                "enabled_triggers": triggers,
                "configuration_ref": f"cfg://e2e/{name}",
            },
        )
        _request("POST", f"{api}/applications/{app_id}/adapters/{adapter['id']}/validate")

    print("5. create a task test contract with a recovery policy")
    _request(
        "POST",
        f"{api}/applications/{app_id}/registered-tasks/{task_id}/contract",
        {
            "safe_input": {"seconds": args.slow_seconds},
            "effect_measurements": [],
            "assertions": [
                {
                    "id": "execution_outcome",
                    "description": "Execution reaches the expected terminal state",
                    "type": "execution_status",
                    "expected": "SUCCEEDED",
                }
            ],
            "cleanup": {"mode": "fixture_managed", "description": "e2e fixture"},
            "recovery": {
                "max_attempts": 2,
                "per_attempt_timeout_seconds": 30,
                "recovery_deadline_seconds": 120,
                "expected_terminal_state": "SUCCEEDED",
                "expect_redelivery": True,
                "settle_seconds": 3,
            },
        },
    )

    print("6. select the scenario and build an approved plan")
    for scenario_id in (
        "dependency_timeout",
        "successful_operation_lost_response",
        "duplicate_message_delivery",
        "database_connection_interruption",
        "worker_termination",
    ):
        _request(
            "PUT",
            f"{api}/applications/{app_id}/registered-tasks/{task_id}/scenarios/{scenario_id}",
            {"enabled": scenario_id == args.scenario},
        )

    plan = _request(
        "POST",
        f"{api}/applications/{app_id}/test-plans",
        {"name": f"{app_name} plan", "task_ids": [task_id]},
    )
    generated = _request("POST", f"{api}/applications/{app_id}/test-plans/{plan['id']}/generate")
    revision = generated["revision"]["revision"]
    for action in ("validate", "submit"):
        _request("POST", f"{api}/applications/{app_id}/test-plans/{plan['id']}/{action}")
    _request(
        "POST",
        f"{api}/applications/{app_id}/test-plans/{plan['id']}/approve",
        {"revision": revision},
    )
    cases = _request(
        "GET",
        f"{api}/applications/{app_id}/test-plans/{plan['id']}/revisions/{revision}/test-cases",
    )
    case = next(item for item in cases if item["scenario_id"] == args.scenario)
    print(f"   approved case {case['id']} ({args.scenario})")

    print("7. start the run (explicit action, nothing was executed by approval)")
    started = _request(
        "POST",
        f"{api}/applications/{app_id}/test-plans/{plan['id']}/runs",
        {"case_id": case["id"]},
    )
    run_id = started["run"]["id"]
    print(f"   run {run_id} scheduled={started['scheduled']}")

    def _detail() -> dict[str, Any] | None:
        detail = _request("GET", f"{api}/applications/{app_id}/test-runs/{run_id}")
        state = detail["run"]["lifecycle_state"]
        print(f"   ... {state}")
        return detail if state in TERMINAL else None

    detail = _wait("the run to reach a terminal lifecycle state", _detail, args.run_timeout)

    run = detail["run"]
    print("\n=== result ===")
    print(json.dumps(
        {
            "run_id": run_id,
            "lifecycle_state": run["lifecycle_state"],
            "verdict": run["verdict"],
            "verdict_detail": run.get("verdict_detail")
            or [
                event["payload"]
                for event in detail["runtime_events"]
                if event["event_type"] == "verdict_recorded"
            ],
            "error_message": run.get("error_message"),
            "fault_events": [
                {"state": e["state"], "injector": e["injector_type"], "error": e.get("error")}
                for e in detail["fault_events"]
            ],
            "recovery": (
                {
                    "attempt_count": detail["recovery"]["attempt_count"],
                    "subsequent_attempt_count": detail["recovery"][
                        "subsequent_attempt_count"
                    ],
                    "retry_request_count": detail["recovery"]["retry_request_count"],
                    "fault_activated": detail["recovery"]["fault_activated"],
                    "final_execution_state": detail["recovery"]["final_execution_state"],
                    "evidence_complete": detail["recovery"]["evidence_complete"],
                    "missing_evidence": detail["recovery"]["missing_evidence"],
                    "observation": detail["recovery"]["observation"],
                }
                if detail.get("recovery")
                else None
            ),
            "workers": [
                {"key": w["worker_key"], "state": w["lifecycle_state"]}
                for w in detail["workers"]
            ],
            "environment": (
                {
                    "namespace": detail["environment"]["namespace"],
                    "provisioning_state": detail["environment"]["provisioning_state"],
                    "cleanup_state": detail["environment"]["cleanup_state"],
                    "cleanup_error": detail["environment"].get("cleanup_error"),
                }
                if detail.get("environment")
                else None
            ),
            "runtime_events": [e["event_type"] for e in detail["runtime_events"]],
        },
        indent=2,
        default=str,
    ))
    return 0 if run["verdict"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
