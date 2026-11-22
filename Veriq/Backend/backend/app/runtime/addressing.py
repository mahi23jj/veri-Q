"""Network addressing for the backend process that drives a Docker run.

The runner publishes the per-run broker and database ports on the Docker
host's loopback interface. That address is reachable directly when the backend
runs on the host, but a backend running inside a container has its own
loopback: it must reach the host through Docker's host gateway instead.

``RUNNER_SUBMIT_HOST`` overrides the detection for unusual setups (a remote
Docker daemon, a custom host alias, ...).
"""

from __future__ import annotations

from pathlib import Path

from app.core.config import settings

CONTAINER_SUBMIT_HOST = "host.docker.internal"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost"})


def running_in_container() -> bool:
    """True when this backend process is itself a containerised process."""

    return Path("/.dockerenv").exists()


def runner_submit_host() -> str:
    """Host name this backend must use to reach a run's published ports."""

    configured = (settings.RUNNER_SUBMIT_HOST or "").strip()
    if configured:
        return configured
    return CONTAINER_SUBMIT_HOST if running_in_container() else "127.0.0.1"


__all__ = [
    "CONTAINER_SUBMIT_HOST",
    "LOOPBACK_HOSTS",
    "runner_submit_host",
    "running_in_container",
]
