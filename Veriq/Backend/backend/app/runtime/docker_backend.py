"""Docker runtime backend.

Only this module (through the supervisor) may touch the container runtime. The
SDK has no Docker socket, no worker-termination authority and no knowledge of
container identifiers.

Isolation for the MVP:

* a dedicated user-defined network per test run;
* unique container and network names per run (``veriq-<run8>-*``);
* broker and database containers with **no** published port except a loopback
  readiness port, so they cannot be reached from outside the machine;
* a per-run database role/database and a per-run broker instance (not merely a
  different Redis database number);
* the dedicated worker runs the application's own image but consumes only the
  test queue, with concurrency 1 and no privileged mode.

This is process/network isolation, not a security boundary: the MVP targets
explicitly configured, trusted applications. See docs/reliability-runtime.md.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Sequence

from app.runtime.contracts import (
    CleanupResult,
    EnvironmentPlan,
    ProvisionResult,
    ReadinessCheck,
    ReadinessReport,
    RuntimeBackendError,
    TerminationResult,
    WorkerHandle,
    WorkerReadyReport,
    WorkerStatus,
)
from app.runtime.readiness import (
    CommandRunner,
    SubprocessRunner,
    check_postgres,
    check_redis,
    poll_until,
    reserve_local_port,
)

_LABEL_KEY = "veriq.test_case_run"
_MISSING_MARKERS = ("no such container", "no such network", "not found")


def _is_missing(stderr: str) -> bool:
    lowered = stderr.lower()
    return any(marker in lowered for marker in _MISSING_MARKERS)


@dataclass(frozen=True)
class _Container:
    role: str
    name: str
    container_id: str
    host_port: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "name": self.name,
            "container_id": self.container_id,
            "host_port": self.host_port,
        }


class DockerRuntime:
    """Real Docker CLI adapter. No third-party Docker SDK dependency."""

    name = "docker"

    def __init__(
        self,
        *,
        runner: CommandRunner | None = None,
        docker_binary: str = "docker",
        poll_interval: float = 0.75,
    ) -> None:
        self._runner = runner or SubprocessRunner()
        self._docker = docker_binary
        self._poll_interval = poll_interval

    # ------------------------------------------------------------------
    # CLI plumbing
    # ------------------------------------------------------------------
    def _run(self, args: Sequence[str], *, timeout: float = 90.0):
        return self._runner.run([self._docker, *args], timeout=timeout)

    def _require(self, args: Sequence[str], *, timeout: float = 90.0, action: str):
        result = self._run(args, timeout=timeout)
        if not result.ok:
            raise RuntimeBackendError(
                f"{action} failed (exit {result.returncode}): {result.stderr.strip()[:500]}"
            )
        return result

    def available(self) -> tuple[bool, str]:
        result = self._run(["version", "--format", "{{.Server.Version}}"], timeout=15)
        if not result.ok:
            return False, result.stderr.strip()[:300] or "docker unavailable"
        return True, result.stdout.strip() or "ok"

    def image_present(self, image: str) -> bool:
        result = self._run(["image", "inspect", image], timeout=30)
        return result.ok

    # ------------------------------------------------------------------
    # Provisioning
    # ------------------------------------------------------------------
    def provision(self, plan: EnvironmentPlan) -> ProvisionResult:
        if not self.image_present(plan.worker.image):
            raise RuntimeBackendError(
                f"target application image '{plan.worker.image}' is not available on the "
                "runner host; build or pull it before starting a test"
            )

        network = plan.network_name
        created = self._run(
            [
                "network",
                "create",
                "--label",
                f"{_LABEL_KEY}={plan.test_run_id}",
                network,
            ],
            timeout=60,
        )
        if not created.ok and "already exists" not in created.stderr.lower():
            raise RuntimeBackendError(
                f"could not create network '{network}': {created.stderr.strip()[:300]}"
            )

        containers: list[_Container] = []
        detail: dict[str, Any] = {}
        try:
            broker_name = f"{plan.namespace}-broker"
            if plan.broker is not None:
                host_port = reserve_local_port()
                container = self._start_container(
                    plan,
                    role="broker",
                    name=broker_name,
                    image=plan.broker.image,
                    command=(),
                    env={},
                    publish={plan.broker.port: host_port},
                    extra_args=("--tmpfs", "/data"),
                )
                containers.append(
                    _Container("broker", broker_name, container, host_port)
                )
                detail["broker_url_internal"] = (
                    f"{plan.broker.scheme}://{broker_name}:{plan.broker.port}/0"
                )
                detail["broker_readiness"] = {"host": "127.0.0.1", "port": host_port}
                # The runner process lives outside the per-run network, so it
                # submits through the loopback-published broker port; the worker
                # keeps using the internal service name.
                detail["broker_submit_ref"] = (
                    f"{plan.broker.scheme}://127.0.0.1:{host_port}/0"
                )

            database_name = f"{plan.namespace}-database"
            if plan.database is not None:
                host_port = reserve_local_port()
                container = self._start_container(
                    plan,
                    role="database",
                    name=database_name,
                    image=plan.database.image,
                    command=(),
                    env={
                        "POSTGRES_USER": plan.database.user,
                        "POSTGRES_PASSWORD": plan.database.password,
                        "POSTGRES_DB": plan.database.database,
                    },
                    publish={plan.database.port: host_port},
                    # No named volume: the data disappears with the container.
                    extra_args=("--tmpfs", "/var/lib/postgresql/data"),
                )
                containers.append(
                    _Container("database", database_name, container, host_port)
                )
                detail["database_url_internal"] = (
                    "postgresql://"
                    f"{plan.database.user}:{plan.database.password}"
                    f"@{database_name}:{plan.database.port}/{plan.database.database}"
                )
                detail["database_readiness"] = {
                    "host": "127.0.0.1",
                    "port": host_port,
                    "user": plan.database.user,
                    "password": plan.database.password,
                    "database": plan.database.database,
                }
        except Exception:
            # Never leave half a run's infrastructure behind.
            self._remove_network(network)
            raise

        return ProvisionResult(
            network_ref=network,
            containers=tuple(container.to_dict() for container in containers),
            broker_ref=detail.get("broker_url_internal"),
            database_ref=detail.get("database_url_internal"),
            detail=detail,
        )

    def _start_container(
        self,
        plan: EnvironmentPlan,
        *,
        role: str,
        name: str,
        image: str,
        command: Sequence[str],
        env: dict[str, str],
        publish: dict[int, int] | None = None,
        extra_args: Sequence[str] = (),
    ) -> str:
        args: list[str] = [
            "run",
            "-d",
            "--name",
            name,
            "--label",
            f"{_LABEL_KEY}={plan.test_run_id}",
            "--label",
            f"veriq.role={role}",
            "--network",
            plan.network_name,
            "--security-opt",
            "no-new-privileges",
        ]
        for container_port, host_port in (publish or {}).items():
            args += ["-p", f"127.0.0.1:{host_port}:{container_port}"]
        for key, value in env.items():
            args += ["-e", f"{key}={value}"]
        args += list(extra_args)
        args.append(image)
        args += [str(part) for part in command]
        result = self._require(args, timeout=180, action=f"start {role} container")
        return result.stdout.strip()

    # ------------------------------------------------------------------
    # Readiness
    # ------------------------------------------------------------------
    def wait_until_ready(
        self,
        plan: EnvironmentPlan,
        provisioned: ProvisionResult,
        *,
        timeout_seconds: int,
    ) -> ReadinessReport:
        checks: dict[str, ReadinessCheck] = {}

        def containers_running() -> bool:
            pending = False
            for container in provisioned.containers:
                name = container["name"]
                status = self._container_state(name)
                if status.get("running"):
                    checks[f"container_running:{container['role']}"] = ReadinessCheck(
                        name=f"container_running:{container['role']}",
                        ok=True,
                        detail=f"{name} running",
                    )
                else:
                    pending = True
                    checks[f"container_running:{container['role']}"] = ReadinessCheck(
                        name=f"container_running:{container['role']}",
                        ok=False,
                        detail=f"{name} is {status.get('status') or 'missing'}",
                    )
            return not pending and bool(provisioned.containers)

        containers_ok = poll_until(
            containers_running,
            timeout_seconds=timeout_seconds,
            interval_seconds=self._poll_interval,
        )

        broker_target = provisioned.detail.get("broker_readiness")
        if broker_target:
            def broker_ok() -> bool:
                check = check_redis(
                    broker_target["host"], int(broker_target["port"])
                )
                checks["broker_reachable"] = check
                return check.ok

            poll_until(
                broker_ok,
                timeout_seconds=timeout_seconds,
                interval_seconds=self._poll_interval,
            )
        elif plan.broker is not None:
            checks["broker_reachable"] = ReadinessCheck(
                name="broker_reachable", ok=False, detail="broker was not provisioned"
            )

        database_target = provisioned.detail.get("database_readiness")
        if database_target:
            def database_ok() -> bool:
                check = check_postgres(
                    database_target["host"],
                    int(database_target["port"]),
                    user=database_target["user"],
                    password=database_target["password"],
                    database=database_target["database"],
                )
                checks["database_reachable"] = check
                return check.ok

            poll_until(
                database_ok,
                timeout_seconds=timeout_seconds,
                interval_seconds=self._poll_interval,
            )
        elif plan.database is not None:
            checks["database_reachable"] = ReadinessCheck(
                name="database_reachable",
                ok=False,
                detail="database was not provisioned",
            )

        checks["network_isolated"] = ReadinessCheck(
            name="network_isolated",
            ok=True,
            detail=f"dedicated network {plan.network_name}; broker/database published to loopback only",
            severity="info",
        )
        if not containers_ok and not any(
            not check.ok for name, check in checks.items() if name.startswith("container_running:")
        ):
            checks["containers_running"] = ReadinessCheck(
                name="containers_running", ok=False, detail="containers did not start in time"
            )
        return ReadinessReport.from_checks(list(checks.values()))

    # ------------------------------------------------------------------
    # Worker lifecycle
    # ------------------------------------------------------------------
    def start_worker(
        self,
        plan: EnvironmentPlan,
        provisioned: ProvisionResult,
        *,
        worker_ref: str,
        env: dict[str, str],
    ) -> WorkerHandle:
        name = f"{plan.namespace}-worker-{worker_ref}"
        args: list[str] = [
            "run",
            "-d",
            "--name",
            name,
            "--label",
            f"{_LABEL_KEY}={plan.test_run_id}",
            "--label",
            "veriq.role=worker",
            "--network",
            plan.network_name,
            "--add-host",
            "host.docker.internal:host-gateway",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "256",
        ]
        for key, value in env.items():
            args += ["-e", f"{key}={value}"]
        args.append(plan.worker.image)
        args += [str(part) for part in plan.worker.command]
        result = self._require(args, timeout=180, action="start worker container")
        return WorkerHandle(
            worker_ref=worker_ref,
            container_ref=result.stdout.strip(),
            hostname=name,
            detail={"container_name": name},
        )

    def wait_for_worker_ready(
        self,
        handle: WorkerHandle,
        *,
        plan: EnvironmentPlan,
        timeout_seconds: int,
        discovery_probe: Any | None = None,
    ) -> WorkerReadyReport:
        name = (handle.detail or {}).get("container_name") or handle.worker_ref
        deadline = time.monotonic() + timeout_seconds
        last_detail = "worker not started"
        while time.monotonic() < deadline:
            status = self._container_state(name)
            if status.get("status") in {"exited", "dead"}:
                return WorkerReadyReport(
                    ready=False,
                    check=ReadinessCheck(
                        name="worker_ready",
                        ok=False,
                        detail=(
                            f"worker container exited (code {status.get('exit_code')}): "
                            f"{self._logs_tail(name)}"
                        ),
                    ),
                    detail=status,
                )
            logs = self._logs_tail(name)
            registered = "ready." in logs or "ready " in logs
            probe_result: dict[str, Any] | None = None
            if discovery_probe is not None:
                try:
                    probe_result = discovery_probe()
                except Exception as exc:  # pragma: no cover - defensive
                    probe_result = {"error": str(exc)}
            discovered = bool(probe_result and probe_result.get("worker_instance_id"))
            queue_consumed = bool(probe_result and probe_result.get("queue_consumed"))
            # A worker started with an explicit queue must report that queue; the
            # consumer flag is informative only (Celery does not always expose it).
            queue_reported = bool(
                probe_result and probe_result.get("queue_reported", queue_consumed)
            )
            if registered and (discovery_probe is None or (discovered and queue_reported)):
                return WorkerReadyReport(
                    ready=True,
                    check=ReadinessCheck(
                        name="worker_ready",
                        ok=True,
                        detail=f"worker registered and consuming '{plan.worker.queue_name}'",
                    ),
                    worker_instance_id=(
                        probe_result.get("worker_instance_id") if probe_result else None
                    ),
                    detail={"logs": logs[-800:], "probe": probe_result or {}},
                )
            last_detail = (
                f"registered={registered} discovered={discovered} "
                f"queue_reported={queue_reported} queue_consumed={queue_consumed}"
            )
            time.sleep(self._poll_interval)
        return WorkerReadyReport(
            ready=False,
            check=ReadinessCheck(
                name="worker_ready",
                ok=False,
                detail=f"worker not ready within {timeout_seconds}s ({last_detail})",
            ),
            detail={"logs": self._logs_tail(name)[-800:]},
        )

    def worker_status(self, handle: WorkerHandle) -> WorkerStatus:
        name = (handle.detail or {}).get("container_name") or handle.worker_ref
        state = self._container_state(name)
        return WorkerStatus(
            running=bool(state.get("running")),
            state=str(state.get("status") or "unknown"),
            exit_code=state.get("exit_code"),
            detail=state,
        )

    def terminate_worker(
        self, handle: WorkerHandle, *, reason: str, grace_seconds: int = 0
    ) -> TerminationResult:
        name = (handle.detail or {}).get("container_name") or handle.worker_ref
        if grace_seconds > 0:
            args = ["stop", "-t", str(grace_seconds), name]
        else:
            args = ["kill", name]
        result = self._run(args, timeout=60)
        if not result.ok and not _is_missing(result.stderr):
            return TerminationResult(
                terminated=False,
                check=ReadinessCheck(
                    name="worker_terminated",
                    ok=False,
                    detail=f"docker {args[0]} failed: {result.stderr.strip()[:300]}",
                ),
                detail={"reason": reason},
            )

        state = self._container_state(name)
        # The outcome is whatever the runtime reports, never assumed.
        terminated = state.get("status") in {"exited", "dead"} or not state.get("running")
        return TerminationResult(
            terminated=bool(terminated),
            check=ReadinessCheck(
                name="worker_terminated",
                ok=bool(terminated),
                detail=(
                    f"container {name} {state.get('status')} "
                    f"(exit code {state.get('exit_code')})"
                ),
            ),
            detail={"reason": reason, **state},
        )

    def stop_worker(self, handle: WorkerHandle) -> None:
        name = (handle.detail or {}).get("container_name") or handle.worker_ref
        if not name:
            return
        self._run(["stop", "-t", "5", name], timeout=60)

    def stop_environment(self, plan: EnvironmentPlan, provisioned: ProvisionResult) -> None:
        for container in provisioned.containers:
            self._run(["stop", "-t", "5", container["name"]], timeout=60)

    def cleanup_environment(
        self, plan: EnvironmentPlan, provisioned: ProvisionResult
    ) -> CleanupResult:
        removed: list[str] = []
        errors: list[str] = []
        names = [container["name"] for container in provisioned.containers]
        # Any worker container left over is removed by label, so a restart
        # cleanup does not need an in-memory handle.
        listed = self._run(
            [
                "ps",
                "-a",
                "--filter",
                f"label={_LABEL_KEY}={plan.test_run_id}",
                "--format",
                "{{.Names}}",
            ],
            timeout=30,
        )
        if listed.ok:
            for name in [line.strip() for line in listed.stdout.splitlines() if line.strip()]:
                if name not in names:
                    names.append(name)

        for name in names:
            result = self._run(["rm", "-f", name], timeout=60)
            if result.ok:
                removed.append(f"container:{name}")
            elif not _is_missing(result.stderr):
                errors.append(f"container {name}: {result.stderr.strip()[:200]}")

        network = provisioned.network_ref or plan.network_name
        if network:
            result = self._run(["network", "rm", network], timeout=60)
            if result.ok:
                removed.append(f"network:{network}")
            elif not _is_missing(result.stderr):
                errors.append(f"network {network}: {result.stderr.strip()[:200]}")

        return CleanupResult(cleaned=not errors, removed=tuple(removed), errors=tuple(errors))

    # ------------------------------------------------------------------
    # Inspection helpers
    # ------------------------------------------------------------------
    def _container_state(self, name: str) -> dict[str, Any]:
        result = self._run(
            [
                "inspect",
                "--format",
                "{{json .State}}",
                name,
            ],
            timeout=30,
        )
        if not result.ok:
            return {"status": "missing", "running": False, "exit_code": None}
        try:
            state = json.loads(result.stdout.strip() or "{}")
        except json.JSONDecodeError:
            return {"status": "unknown", "running": False, "exit_code": None}
        return {
            "status": state.get("Status") or "unknown",
            "running": bool(state.get("Running")),
            "exit_code": state.get("ExitCode"),
            "started_at": state.get("StartedAt"),
            "finished_at": state.get("FinishedAt"),
            "oom_killed": state.get("OOMKilled"),
        }

    def _logs_tail(self, name: str, lines: int = 60) -> str:
        result = self._run(["logs", "--tail", str(lines), name], timeout=30)
        text = (result.stdout or "") + (result.stderr or "")
        return re.sub(r"\x1b\[[0-9;]*m", "", text)[-4000:]

    def _remove_network(self, network: str) -> None:
        self._run(["network", "rm", network], timeout=30)


__all__ = ["DockerRuntime"]
