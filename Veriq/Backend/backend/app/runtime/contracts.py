"""Plans and handles exchanged by the runtime components.

Everything here is plain data so it can be persisted or reconstructed after a
backend restart. No component stores a live socket or object handle as the only
record of a running resource.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence


class RuntimeBackendError(Exception):
    """The runtime backend could not perform the requested operation."""


@dataclass(frozen=True)
class BrokerSpec:
    image: str = "redis:7-alpine"
    port: int = 6379
    scheme: str = "redis"


@dataclass(frozen=True)
class DatabaseSpec:
    image: str = "postgres:16-alpine"
    port: int = 5432
    user: str = "veriq"
    password: str = "veriq"
    database: str = "veriq"


@dataclass(frozen=True)
class WorkerSpec:
    image: str
    command: tuple[str, ...]
    queue_name: str
    concurrency: int = 1
    hostname: str = "veriq@%h"
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class EnvironmentPlan:
    """Everything the provisioner needs to build one isolated environment."""

    test_run_id: str
    target_app_id: str
    namespace: str
    runtime_type: str
    network_name: str
    worker: WorkerSpec
    broker: BrokerSpec | None
    database: DatabaseSpec | None
    env: dict[str, str] = field(default_factory=dict)
    runtime_config: dict[str, Any] = field(default_factory=dict)
    provisioning_timeout_seconds: int = 120
    worker_startup_timeout_seconds: int = 90
    expected_task_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReadinessCheck:
    name: str
    ok: bool
    detail: str = ""
    severity: str = "error"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "detail": self.detail,
            "severity": self.severity,
        }


@dataclass(frozen=True)
class ReadinessReport:
    ok: bool
    checks: tuple[ReadinessCheck, ...] = ()
    blockers: tuple[str, ...] = ()

    @classmethod
    def from_checks(cls, checks: Sequence[ReadinessCheck]) -> "ReadinessReport":
        blockers = tuple(
            check.detail or check.name
            for check in checks
            if not check.ok and check.severity == "error"
        )
        return cls(ok=not blockers, checks=tuple(checks), blockers=blockers)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checks": [check.to_dict() for check in self.checks],
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class ProvisionResult:
    network_ref: str | None
    containers: tuple[dict[str, Any], ...] = ()
    broker_ref: str | None = None
    database_ref: str | None = None
    proxy_refs: dict[str, Any] = field(default_factory=dict)
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkerHandle:
    """A persisted reference to one worker resource, not a live object."""

    worker_ref: str
    container_ref: str | None = None
    hostname: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkerReadyReport:
    ready: bool
    check: ReadinessCheck
    worker_instance_id: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkerStatus:
    running: bool
    state: str
    exit_code: int | None = None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TerminationResult:
    terminated: bool
    check: ReadinessCheck
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CleanupResult:
    cleaned: bool
    removed: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "cleaned": self.cleaned,
            "removed": list(self.removed),
            "errors": list(self.errors),
        }


class RuntimeBackend(Protocol):
    """Authorized runtime interface. Only the runner's supervisor uses it."""

    name: str

    def provision(self, plan: EnvironmentPlan) -> ProvisionResult: ...

    def wait_until_ready(
        self,
        plan: EnvironmentPlan,
        provisioned: ProvisionResult,
        *,
        timeout_seconds: int,
    ) -> ReadinessReport: ...

    def start_worker(
        self,
        plan: EnvironmentPlan,
        provisioned: ProvisionResult,
        *,
        worker_ref: str,
        env: dict[str, str],
    ) -> WorkerHandle: ...

    def wait_for_worker_ready(
        self,
        handle: WorkerHandle,
        *,
        plan: EnvironmentPlan,
        timeout_seconds: int,
        discovery_probe: Any | None = None,
    ) -> WorkerReadyReport: ...

    def worker_status(self, handle: WorkerHandle) -> WorkerStatus: ...

    def terminate_worker(
        self, handle: WorkerHandle, *, reason: str, grace_seconds: int = 0
    ) -> TerminationResult: ...

    def stop_worker(self, handle: WorkerHandle) -> None: ...

    def stop_environment(self, plan: EnvironmentPlan, provisioned: ProvisionResult) -> None: ...

    def cleanup_environment(
        self, plan: EnvironmentPlan, provisioned: ProvisionResult
    ) -> CleanupResult: ...


__all__ = [
    "BrokerSpec",
    "CleanupResult",
    "DatabaseSpec",
    "EnvironmentPlan",
    "ProvisionResult",
    "ReadinessCheck",
    "ReadinessReport",
    "RuntimeBackend",
    "RuntimeBackendError",
    "TerminationResult",
    "WorkerHandle",
    "WorkerReadyReport",
    "WorkerSpec",
    "WorkerStatus",
]
