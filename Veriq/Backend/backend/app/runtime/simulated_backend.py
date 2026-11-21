"""Simulated runtime backend.

Explicitly **not isolated**: it records provisioning and worker lifecycle in
memory so the orchestrator, fault controller, observer and evaluator can be
exercised deterministically (tests, local demos) without a container runtime.

It must never be presented as a real test environment: the environment row keeps
``runtime_type = "simulated"`` and readiness reports carry a ``simulated``
marker. Production runs use :class:`app.runtime.docker_backend.DockerRuntime`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

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


@dataclass
class SimulatedBackendState:
    provisioned: list[ProvisionResult] = field(default_factory=list)
    started_workers: list[str] = field(default_factory=list)
    terminated_workers: list[str] = field(default_factory=list)
    stopped_workers: list[str] = field(default_factory=list)
    cleaned: list[str] = field(default_factory=list)

    @property
    def active_workers(self) -> list[str]:
        return [
            worker
            for worker in self.started_workers
            if worker not in self.terminated_workers and worker not in self.stopped_workers
        ]


class SimulatedRuntime:
    name = "simulated"

    def __init__(
        self,
        *,
        provision_error: str | None = None,
        readiness_failures: tuple[str, ...] = (),
        worker_start_error: str | None = None,
        worker_ready_failure: str | None = None,
        worker_instance_id: str = "simulated-worker",
        queue_consumed: bool = True,
        terminate_result: bool = True,
        cleanup_errors: tuple[str, ...] = (),
    ) -> None:
        self.state = SimulatedBackendState()
        self._provision_error = provision_error
        self._readiness_failures = set(readiness_failures)
        self._worker_start_error = worker_start_error
        self._worker_ready_failure = worker_ready_failure
        self._worker_instance_id = worker_instance_id
        self._queue_consumed = queue_consumed
        self._terminate_result = terminate_result
        self._cleanup_errors = tuple(cleanup_errors)

    def provision(self, plan: EnvironmentPlan) -> ProvisionResult:
        if self._provision_error:
            raise RuntimeBackendError(self._provision_error)
        result = ProvisionResult(
            network_ref=plan.network_name,
            containers=(
                {"role": "simulated", "name": f"{plan.namespace}-simulated", "container_id": "sim"},
            ),
            broker_ref=(
                f"redis://{plan.namespace}-broker:6379/0" if plan.broker is not None else None
            ),
            database_ref=(
                f"postgresql://{plan.namespace}-database:5432/veriq"
                if plan.database is not None
                else None
            ),
            detail={"simulated": True},
        )
        self.state.provisioned.append(result)
        return result

    def wait_until_ready(
        self,
        plan: EnvironmentPlan,
        provisioned: ProvisionResult,
        *,
        timeout_seconds: int,
    ) -> ReadinessReport:
        checks = [
            ReadinessCheck(
                name="simulated_runtime",
                ok=True,
                detail="simulated backend: no real isolation is provided",
                severity="info",
            ),
            ReadinessCheck(
                name="broker_reachable",
                ok="broker_reachable" not in self._readiness_failures,
                detail=(
                    "simulated broker unreachable"
                    if "broker_reachable" in self._readiness_failures
                    else "simulated broker ready"
                ),
            ),
            ReadinessCheck(
                name="database_reachable",
                ok="database_reachable" not in self._readiness_failures,
                detail=(
                    "simulated database unreachable"
                    if "database_reachable" in self._readiness_failures
                    else "simulated database ready"
                ),
            ),
        ]
        if "application_starts" in self._readiness_failures:
            checks.append(
                ReadinessCheck(
                    name="application_starts",
                    ok=False,
                    detail="simulated application start failure",
                )
            )
        return ReadinessReport.from_checks(checks)

    def start_worker(
        self,
        plan: EnvironmentPlan,
        provisioned: ProvisionResult,
        *,
        worker_ref: str,
        env: dict[str, str],
    ) -> WorkerHandle:
        if self._worker_start_error:
            raise RuntimeBackendError(self._worker_start_error)
        self.state.started_workers.append(worker_ref)
        return WorkerHandle(
            worker_ref=worker_ref,
            container_ref=f"sim-{worker_ref}",
            hostname=f"{plan.namespace}-{worker_ref}",
            detail={"simulated": True},
        )

    def wait_for_worker_ready(
        self,
        handle: WorkerHandle,
        *,
        plan: EnvironmentPlan,
        timeout_seconds: int,
        discovery_probe: Any | None = None,
    ) -> WorkerReadyReport:
        if self._worker_ready_failure:
            return WorkerReadyReport(
                ready=False,
                check=ReadinessCheck(
                    name="worker_ready", ok=False, detail=self._worker_ready_failure
                ),
            )
        return WorkerReadyReport(
            ready=True,
            check=ReadinessCheck(
                name="worker_ready",
                ok=True,
                detail=f"simulated worker consuming '{plan.worker.queue_name}'",
            ),
            worker_instance_id=self._worker_instance_id,
            detail={"queue_consumed": self._queue_consumed, "simulated": True},
        )

    def worker_status(self, handle: WorkerHandle) -> WorkerStatus:
        running = handle.worker_ref in self.state.active_workers
        return WorkerStatus(
            running=running,
            state="running" if running else "terminated",
            detail={"simulated": True},
        )

    def terminate_worker(
        self, handle: WorkerHandle, *, reason: str, grace_seconds: int = 0
    ) -> TerminationResult:
        self.state.terminated_workers.append(handle.worker_ref)
        return TerminationResult(
            terminated=self._terminate_result,
            check=ReadinessCheck(
                name="worker_terminated",
                ok=self._terminate_result,
                detail=(
                    f"simulated termination of {handle.worker_ref} ({reason})"
                    if self._terminate_result
                    else "simulated termination failed"
                ),
            ),
            detail={"reason": reason, "simulated": True},
        )

    def stop_worker(self, handle: WorkerHandle) -> None:
        self.state.stopped_workers.append(handle.worker_ref)

    def stop_environment(self, plan: EnvironmentPlan, provisioned: ProvisionResult) -> None:
        self.state.stopped_workers.extend(self.state.active_workers)

    def cleanup_environment(
        self, plan: EnvironmentPlan, provisioned: ProvisionResult
    ) -> CleanupResult:
        self.state.cleaned.append(plan.namespace)
        return CleanupResult(
            cleaned=not self._cleanup_errors,
            removed=(f"simulated:{plan.namespace}",),
            errors=self._cleanup_errors,
        )


__all__ = ["SimulatedRuntime"]
