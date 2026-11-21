"""Real TCP fault proxy used for DATABASE_INTERRUPTION.

    Celery task -> this TCP proxy -> test PostgreSQL

Interruption closes every forwarded connection and refuses new ones until the
fault is released. That is a connection-path interruption, deliberately not a
transaction-level failure: whatever the application already committed stays
committed, and its transaction state is its own business.

The proxy only ever points at the isolated test database passed in by the
provisioner; it never resolves or touches production infrastructure.
"""

from __future__ import annotations

import socket
import select
import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProxyStats:
    accepted: int = 0
    blocked: int = 0
    interrupted_connections: int = 0
    active: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)


class TcpFaultProxy:
    """Single-hop TCP forwarder with a controllable interruption window."""

    def __init__(
        self,
        upstream_host: str,
        upstream_port: int,
        *,
        bind_host: str = "0.0.0.0",
        connect_timeout: float = 5.0,
    ) -> None:
        self._upstream = (upstream_host, int(upstream_port))
        self._bind_host = bind_host
        self._connect_timeout = connect_timeout
        self._lock = threading.Lock()
        self._stats = ProxyStats()
        self._interrupted = False
        self._sockets: set[socket.socket] = set()
        self._listener: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._listener is not None:
            return
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((self._bind_host, 0))
        listener.listen(64)
        listener.settimeout(0.5)
        self._listener = listener
        self._stopping.clear()
        self._thread = threading.Thread(
            target=self._accept_loop, name="veriq-db-fault-proxy", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        listener, self._listener = self._listener, None
        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=5)
        self._close_all()

    @property
    def port(self) -> int:
        if self._listener is None:
            raise RuntimeError("proxy is not started")
        return int(self._listener.getsockname()[1])

    # ------------------------------------------------------------------
    # Fault control
    # ------------------------------------------------------------------
    def interrupt(self) -> None:
        with self._lock:
            self._interrupted = True
        self._record("interruption_started")
        self._close_all()

    def restore(self) -> None:
        with self._lock:
            self._interrupted = False
        self._record("interruption_released")

    @property
    def interrupted(self) -> bool:
        with self._lock:
            return self._interrupted

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "accepted": self._stats.accepted,
                "blocked": self._stats.blocked,
                "interrupted_connections": self._stats.interrupted_connections,
                "active_connections": self._stats.active,
                "interrupted": self._interrupted,
                "upstream": f"{self._upstream[0]}:{self._upstream[1]}",
                "port": self.port if self._listener is not None else None,
                "events": list(self._stats.events),
            }

    def _record(self, event: str, **payload: Any) -> None:
        with self._lock:
            self._stats.events.append({"event": event, "at": time.time(), **payload})

    # ------------------------------------------------------------------
    # Forwarding
    # ------------------------------------------------------------------
    def _accept_loop(self) -> None:
        while not self._stopping.is_set():
            listener = self._listener
            if listener is None:
                return
            try:
                client, _address = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with self._lock:
                self._stats.accepted += 1
                blocked = self._interrupted
            if blocked:
                with self._lock:
                    self._stats.blocked += 1
                self._record("connection_blocked")
                try:
                    client.close()
                except OSError:
                    pass
                continue
            try:
                upstream = socket.create_connection(
                    self._upstream, timeout=self._connect_timeout
                )
            except OSError as exc:
                self._record("upstream_connect_failed", error=str(exc))
                try:
                    client.close()
                except OSError:
                    pass
                continue
            with self._lock:
                self._sockets.update({client, upstream})
                self._stats.active += 1
            threading.Thread(
                target=self._pump,
                args=(client, upstream),
                name="veriq-db-fault-forward",
                daemon=True,
            ).start()

    def _pump(self, client: socket.socket, upstream: socket.socket) -> None:
        sockets = [client, upstream]
        try:
            while not self._stopping.is_set():
                readable, _, errored = select.select(sockets, [], sockets, 0.5)
                if errored:
                    break
                for source in readable:
                    target = upstream if source is client else client
                    try:
                        chunk = source.recv(65536)
                    except OSError:
                        chunk = b""
                    if not chunk:
                        return
                    target.sendall(chunk)
        except OSError:
            pass
        finally:
            for sock in sockets:
                try:
                    sock.close()
                except OSError:
                    pass
            with self._lock:
                self._sockets.difference_update(sockets)
                self._stats.active = max(0, self._stats.active - 1)

    def _close_all(self) -> None:
        with self._lock:
            sockets = list(self._sockets)
            self._sockets.clear()
            self._stats.interrupted_connections += len(sockets)
        for sock in sockets:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass


__all__ = ["TcpFaultProxy"]
