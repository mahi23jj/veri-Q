"""Readiness probes and small process helpers for the runtime backends."""

from __future__ import annotations

import socket
import subprocess
import time
from dataclasses import dataclass
from typing import Callable, Protocol, Sequence

from app.runtime.contracts import ReadinessCheck


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class CommandRunner(Protocol):
    def run(self, args: Sequence[str], *, timeout: float = 60.0) -> CommandResult: ...


class SubprocessRunner:
    """Runs the Docker CLI without a shell (no interpolation, no injection)."""

    def run(self, args: Sequence[str], *, timeout: float = 60.0) -> CommandResult:
        argv = [str(arg) for arg in args]
        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            return CommandResult(tuple(argv), 127, "", f"command not found: {exc}")
        except subprocess.TimeoutExpired as exc:
            return CommandResult(
                tuple(argv), 124, exc.stdout or "", f"timed out after {timeout}s"
            )
        return CommandResult(
            tuple(argv),
            completed.returncode,
            completed.stdout or "",
            completed.stderr or "",
        )


def reserve_local_port() -> int:
    """Ask the OS for a free loopback port.

    Only used to publish a readiness port to 127.0.0.1. There is a small race
    between closing the socket and Docker binding it; readiness checks catch it.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def poll_until(
    predicate: Callable[[], bool],
    *,
    timeout_seconds: float,
    interval_seconds: float = 0.5,
) -> bool:
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while True:
        if predicate():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval_seconds)


def check_redis(host: str, port: int, *, timeout: float = 2.0) -> ReadinessCheck:
    """Real PING against the isolated broker (never a production broker)."""
    try:
        import redis  # imported lazily: optional at module import time
    except Exception as exc:  # pragma: no cover - dependency is installed in dev
        return ReadinessCheck(
            name="broker_reachable",
            ok=False,
            detail=f"redis client unavailable: {exc}",
        )
    try:
        client = redis.Redis(
            host=host,
            port=port,
            socket_connect_timeout=timeout,
            socket_timeout=timeout,
        )
        client.ping()
        client.close()
    except Exception as exc:
        return ReadinessCheck(
            name="broker_reachable", ok=False, detail=f"{host}:{port} -> {exc}"
        )
    return ReadinessCheck(name="broker_reachable", ok=True, detail=f"{host}:{port} PONG")


def check_postgres(
    host: str,
    port: int,
    *,
    user: str,
    password: str,
    database: str,
    timeout: float = 3.0,
) -> ReadinessCheck:
    """Real ``SELECT 1`` against the isolated test database."""
    try:
        import psycopg
    except Exception as exc:  # pragma: no cover
        return ReadinessCheck(
            name="database_reachable",
            ok=False,
            detail=f"psycopg unavailable: {exc}",
        )
    try:
        with psycopg.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            dbname=database,
            connect_timeout=int(max(1, timeout)),
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
    except Exception as exc:
        return ReadinessCheck(
            name="database_reachable", ok=False, detail=f"{host}:{port} -> {exc}"
        )
    return ReadinessCheck(
        name="database_reachable", ok=True, detail=f"{host}:{port} SELECT 1"
    )


def check_tcp(host: str, port: int, *, name: str, timeout: float = 2.0) -> ReadinessCheck:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except OSError as exc:
        return ReadinessCheck(name=name, ok=False, detail=f"{host}:{port} -> {exc}")
    return ReadinessCheck(name=name, ok=True, detail=f"{host}:{port} accepting connections")


__all__ = [
    "CommandResult",
    "CommandRunner",
    "SubprocessRunner",
    "check_postgres",
    "check_redis",
    "check_tcp",
    "poll_until",
    "reserve_local_port",
]
