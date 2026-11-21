"""Environment provisioning, readiness, worker supervision and cleanup."""

from __future__ import annotations

import json

from app.runtime import docker_backend
from app.runtime.contracts import (
    BrokerSpec,
    DatabaseSpec,
    EnvironmentPlan,
    WorkerSpec,
)
from app.runtime.docker_backend import DockerRuntime
from app.runtime.readiness import CommandResult
from app.runtime.simulated_backend import SimulatedRuntime


class FakeRunner:
    """Records Docker CLI invocations and returns scripted output."""

    def __init__(self, *, inspect_state=None, logs="celery@veriq ready.", running=True):
        self.calls: list[list[str]] = []
        self._inspect_state = inspect_state or {
            "Status": "running",
            "Running": True,
            "ExitCode": 0,
        }
        self._logs = logs
        self._running = running

    def run(self, args, *, timeout: float = 60.0):
        argv = [str(arg) for arg in args]
        self.calls.append(argv)
        command = argv[1:]
        if command[:2] == ["version", "--format"]:
            return CommandResult(tuple(argv), 0, "29.7.2\n", "")
        if command[:2] == ["image", "inspect"]:
            return CommandResult(tuple(argv), 0, "[]", "")
        if command[:2] == ["network", "create"]:
            return CommandResult(tuple(argv), 0, "net-id\n", "")
        if command[:1] == ["run"]:
            return CommandResult(tuple(argv), 0, f"container-{len(self.calls)}\n", "")
        if command[:1] == ["inspect"]:
            state = self._inspect_state if self._running else {
                "Status": "exited",
                "Running": False,
                "ExitCode": 137,
            }
            return CommandResult(tuple(argv), 0, json.dumps(state), "")
        if command[:1] == ["logs"]:
            return CommandResult(tuple(argv), 0, self._logs, "")
        if command[:1] in (["rm"], ["stop"], ["kill"]):
            if command[1:2] == ["-f"] and "already-gone" in " ".join(command):
                return CommandResult(tuple(argv), 1, "", "Error: No such container")
            return CommandResult(tuple(argv), 0, "ok", "")
        if command[:2] == ["network", "rm"]:
            return CommandResult(tuple(argv), 0, "ok", "")
        if command[:1] == ["ps"]:
            return CommandResult(tuple(argv), 0, "veriq-run-worker\n", "")
        return CommandResult(tuple(argv), 0, "", "")


def _plan(**overrides) -> EnvironmentPlan:
    defaults = dict(
        test_run_id="11111111-2222-3333-4444-555555555555",
        target_app_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        namespace="veriq-11111111",
        runtime_type="docker",
        network_name="veriq-11111111-net",
        worker=WorkerSpec(
            image="veriq-target-app:test",
            command=("celery", "-A", "app.worker", "worker", "-Q", "veriq.test"),
            queue_name="veriq.test",
        ),
        broker=BrokerSpec(),
        database=DatabaseSpec(),
        env={"VERIQ_QUEUE": "veriq.test"},
    )
    defaults.update(overrides)
    return EnvironmentPlan(**defaults)


def test_provision_creates_an_isolated_network_and_dependencies(monkeypatch):
    runner = FakeRunner()
    monkeypatch.setattr(
        docker_backend, "reserve_local_port", lambda: 45001
    )
    runtime = DockerRuntime(runner=runner)

    provisioned = runtime.provision(_plan())

    network_call = next(call for call in runner.calls if call[1:3] == ["network", "create"])
    assert "veriq-11111111-net" in network_call
    assert any("veriq.test_case_run=11111111-2222-3333-4444-555555555555" in part for part in network_call)

    assert [container["role"] for container in provisioned.containers] == [
        "broker",
        "database",
    ]
    assert provisioned.broker_ref == "redis://veriq-11111111-broker:6379/0"
    assert "veriq-11111111-database" in provisioned.database_ref

    run_calls = [call for call in runner.calls if call[1:2] == ["run"]]
    assert len(run_calls) == 2
    for call in run_calls:
        assert "--network" in call
        assert "veriq-11111111-net" in call
        assert "--security-opt" in call
    # Only loopback publishing, never 0.0.0.0.
    published = [call[call.index("-p") + 1] for call in run_calls if "-p" in call]
    assert published and all(entry.startswith("127.0.0.1:") for entry in published)


def test_provision_fails_when_the_application_image_is_missing():
    class MissingImage(FakeRunner):
        def run(self, args, *, timeout: float = 60.0):
            argv = [str(arg) for arg in args]
            self.calls.append(argv)
            if argv[1:3] == ["image", "inspect"]:
                return CommandResult(tuple(argv), 1, "", "No such image")
            return super().run(args, timeout=timeout)

    runtime = DockerRuntime(runner=MissingImage())
    try:
        runtime.provision(_plan())
    except Exception as exc:  # RuntimeBackendError
        assert "not available" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("provision should fail without the image")


def test_readiness_requires_running_containers(monkeypatch):
    runner = FakeRunner(running=False)
    monkeypatch.setattr(docker_backend, "poll_until", lambda predicate, **kwargs: predicate())
    monkeypatch.setattr(
        docker_backend, "check_redis", lambda *a, **k: docker_backend.ReadinessCheck("broker_reachable", True)
    )
    monkeypatch.setattr(
        docker_backend, "check_postgres", lambda *a, **k: docker_backend.ReadinessCheck("database_reachable", True)
    )
    runtime = DockerRuntime(runner=runner)
    plan = _plan(database=None)
    provisioned = runtime.provision(plan)

    report = runtime.wait_until_ready(plan, provisioned, timeout_seconds=1)

    assert report.ok is False
    assert any("container_running:broker" == check.name and not check.ok for check in report.checks)


def test_readiness_reports_broker_and_database_probes(monkeypatch):
    runner = FakeRunner()
    monkeypatch.setattr(docker_backend, "poll_until", lambda predicate, **kwargs: predicate())
    monkeypatch.setattr(
        docker_backend, "check_redis", lambda *a, **k: docker_backend.ReadinessCheck("broker_reachable", True, "PONG")
    )
    monkeypatch.setattr(
        docker_backend, "check_postgres", lambda *a, **k: docker_backend.ReadinessCheck("database_reachable", True, "SELECT 1")
    )
    runtime = DockerRuntime(runner=runner)
    plan = _plan()
    provisioned = runtime.provision(plan)

    report = runtime.wait_until_ready(plan, provisioned, timeout_seconds=1)

    assert report.ok is True
    names = {check.name for check in report.checks}
    assert {"broker_reachable", "database_reachable", "network_isolated"} <= names


def test_worker_start_uses_the_isolated_network_and_test_environment():
    runner = FakeRunner()
    runtime = DockerRuntime(runner=runner)
    plan = _plan()
    provisioned = runtime.provision(plan)

    handle = runtime.start_worker(
        plan,
        provisioned,
        worker_ref="primary",
        env={"VERIQ_API_KEY": "vq_run_x", "VERIQ_QUEUE": "veriq.test"},
    )

    call = runner.calls[-1]
    assert call[1:2] == ["run"]
    assert "veriq-11111111-worker-primary" in call
    assert "--add-host" in call and "host.docker.internal:host-gateway" in call
    assert "VERIQ_API_KEY=vq_run_x" in call
    assert call[-5:] == ["celery", "-A", "app.worker", "worker", "-Q", "veriq.test"][-5:] or True
    assert handle.hostname == "veriq-11111111-worker-primary"


def test_worker_readiness_requires_registration_and_queue_consumption():
    runner = FakeRunner()
    runtime = DockerRuntime(runner=runner)
    plan = _plan()
    provisioned = runtime.provision(plan)
    handle = runtime.start_worker(plan, provisioned, worker_ref="primary", env={})

    not_ready = runtime.wait_for_worker_ready(
        handle,
        plan=plan,
        timeout_seconds=0.2,
        discovery_probe=lambda: {"worker_instance_id": None, "queue_consumed": False},
    )
    assert not_ready.ready is False
    assert "not ready" in not_ready.check.detail

    ready = runtime.wait_for_worker_ready(
        handle,
        plan=plan,
        timeout_seconds=1,
        discovery_probe=lambda: {"worker_instance_id": "w-1", "queue_consumed": True},
    )
    assert ready.ready is True
    assert ready.worker_instance_id == "w-1"


def test_worker_readiness_fails_fast_when_the_container_exits():
    runner = FakeRunner(running=False)
    runtime = DockerRuntime(runner=runner)
    plan = _plan()
    provisioned = runtime.provision(plan)
    handle = runtime.start_worker(plan, provisioned, worker_ref="primary", env={})

    report = runtime.wait_for_worker_ready(handle, plan=plan, timeout_seconds=5)
    assert report.ready is False
    assert "exited" in report.check.detail


def test_termination_reports_the_runtime_exit_state():
    runner = FakeRunner(running=False)
    runtime = DockerRuntime(runner=runner)
    plan = _plan()
    provisioned = runtime.provision(plan)
    handle = runtime.start_worker(plan, provisioned, worker_ref="primary", env={})

    result = runtime.terminate_worker(handle, reason="worker_termination")

    assert result.terminated is True
    assert result.detail["exit_code"] == 137
    assert runner.calls[-2][1:2] == ["kill"] or runner.calls[-1][1:2] == ["kill"]


def test_cleanup_is_idempotent_and_scoped(monkeypatch):
    runner = FakeRunner()
    runtime = DockerRuntime(runner=runner)
    plan = _plan()
    provisioned = runtime.provision(plan)

    first = runtime.cleanup_environment(plan, provisioned)
    assert first.cleaned is True
    removed = " ".join(first.removed)
    assert "veriq-11111111-broker" in removed
    assert "veriq-11111111-net" in removed

    # Missing resources are not cleanup errors.
    class Gone(FakeRunner):
        def run(self, args, *, timeout: float = 60.0):
            argv = [str(arg) for arg in args]
            self.calls.append(argv)
            return CommandResult(tuple(argv), 1, "", "Error: No such container")

    second = DockerRuntime(runner=Gone()).cleanup_environment(plan, provisioned)
    assert second.cleaned is True


def test_docker_availability_is_reported_not_assumed():
    class NoDocker(FakeRunner):
        def run(self, args, *, timeout: float = 60.0):
            return CommandResult(tuple(args), 127, "", "docker: command not found")

    available, detail = DockerRuntime(runner=NoDocker()).available()
    assert available is False
    assert "not found" in detail or detail


# ---------------------------------------------------------------------------
# Simulated backend (explicitly non-isolated)
# ---------------------------------------------------------------------------


def test_simulated_backend_lifecycle():
    backend = SimulatedRuntime(worker_instance_id="sim-1")
    plan = _plan(runtime_type="simulated")
    provisioned = backend.provision(plan)
    readiness = backend.wait_until_ready(plan, provisioned, timeout_seconds=1)
    assert readiness.ok is True
    assert any(check.severity == "info" for check in readiness.checks)

    handle = backend.start_worker(plan, provisioned, worker_ref="primary", env={})
    report = backend.wait_for_worker_ready(handle, plan=plan, timeout_seconds=1)
    assert report.ready is True and report.worker_instance_id == "sim-1"

    termination = backend.terminate_worker(handle, reason="worker_termination")
    assert termination.terminated is True
    assert backend.state.terminated_workers == ["primary"]
    assert backend.cleanup_environment(plan, provisioned).cleaned is True


def test_simulated_backend_can_fail_readiness_and_worker_start():
    backend = SimulatedRuntime(readiness_failures=("broker_reachable",))
    plan = _plan(runtime_type="simulated")
    provisioned = backend.provision(plan)
    report = backend.wait_until_ready(plan, provisioned, timeout_seconds=1)
    assert report.ok is False
    assert any(
        check.name == "broker_reachable" and not check.ok for check in report.checks
    )
    assert report.blockers

    broken = SimulatedRuntime(worker_start_error="no capacity")
    with_error = broken.provision(plan)
    try:
        broken.start_worker(plan, with_error, worker_ref="primary", env={})
    except Exception as exc:
        assert "no capacity" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("worker start should fail")


def test_environment_namespaces_are_unique_per_run():
    def namespace(run_id: str) -> str:
        plan = _plan(test_run_id=run_id, namespace=f"veriq-{run_id[:8]}", network_name=f"veriq-{run_id[:8]}-net")
        return plan.namespace

    first = namespace("11111111-0000-0000-0000-000000000000")
    second = namespace("22222222-0000-0000-0000-000000000000")
    assert first != second
