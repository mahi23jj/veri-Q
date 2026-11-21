"""Runtime backend selection for one test case run.

The choice is explicit and recorded on the environment row. The simulated
backend exists for tests and local demos; it never claims isolation.
"""

from __future__ import annotations

from typing import Any

from app.models.runtime import TestCaseRun
from app.runtime.contracts import RuntimeBackend
from app.runtime.docker_backend import DockerRuntime
from app.runtime.simulated_backend import SimulatedRuntime


def backend_for_run(
    run: TestCaseRun, *, simulated_options: dict[str, Any] | None = None
) -> RuntimeBackend:
    profile = run.runtime_profile_snapshot or {}
    runtime_type = str(profile.get("runtime_type") or "docker")
    if runtime_type == "simulated":
        return SimulatedRuntime(**(simulated_options or {}))
    return DockerRuntime()


__all__ = ["backend_for_run"]
