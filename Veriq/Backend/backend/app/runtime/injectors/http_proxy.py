"""Real HTTP fault proxy for DEPENDENCY_TIMEOUT and LOST_RESPONSE.

The proxy sits between the application and the test dependency:

    Application -> this proxy -> test dependency

Two technically different behaviours are implemented:

``delay``
    The request is forwarded, the dependency processes it, then the response is
    held back longer than the application's timeout. The application normally
    times out while reading the response. (A slow dependency, not a lost
    response.)

``lost_response``
    The request is forwarded, the dependency processes it and returns a
    response, and that response is discarded without ever reaching the
    application. The application observes its normal timeout/connection error.

Only the first matching request is faulted by default (``fault_requests``), so
a retry can succeed and recovery becomes observable. Every step is recorded so
the evidence can distinguish "request forwarded" from "response discarded" from
"client disconnected".
"""

from __future__ import annotations

import http.client
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Mapping
from urllib.parse import urlsplit

MODE_DELAY = "delay"
MODE_LOST_RESPONSE = "lost_response"

_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}


@dataclass(frozen=True)
class FaultDecision:
    faulted: bool
    request_index: int
    delay_ms: int = 0
    drop_response: bool = False


class HttpFaultProxy:
    """Threaded HTTP proxy with per-run scoping (one instance, one port)."""

    def __init__(
        self,
        upstream_url: str,
        *,
        advertised_host: str = "127.0.0.1",
        bind_host: str = "0.0.0.0",
        path_prefix: str | None = None,
        request_timeout: float = 15.0,
    ) -> None:
        parsed = urlsplit(upstream_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("upstream_url must be an absolute http(s) URL")
        self._scheme = parsed.scheme
        self._upstream_host = parsed.hostname
        self._upstream_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        self._upstream_base = parsed.path.rstrip("/")
        self._advertised_host = advertised_host
        self._bind_host = bind_host
        self._path_prefix = path_prefix
        self._request_timeout = request_timeout

        self._lock = threading.Lock()
        self._mode: str | None = None
        self._delay_ms = 0
        self._remaining = 0
        self._active = False
        self._request_index = 0
        self._events: list[dict[str, Any]] = []
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._server is not None:
            return
        proxy = self

        class _Server(ThreadingHTTPServer):
            daemon_threads = True
            allow_reuse_address = True

        server = _Server((self._bind_host, 0), _ProxyHandler)
        server.proxy = proxy  # type: ignore[attr-defined]
        self._server = server
        self._thread = threading.Thread(
            target=server.serve_forever, name="veriq-http-fault-proxy", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            try:
                server.shutdown()
            except Exception:  # pragma: no cover - defensive
                pass
            try:
                server.server_close()
            except Exception:  # pragma: no cover
                pass
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=5)
        with self._lock:
            self._active = False

    @property
    def port(self) -> int:
        if self._server is None:
            raise RuntimeError("proxy is not started")
        return int(self._server.server_address[1])

    @property
    def origin(self) -> str:
        return f"http://{self._advertised_host}:{self.port}"

    # ------------------------------------------------------------------
    # Fault control
    # ------------------------------------------------------------------
    def arm(self, mode: str, *, delay_ms: int = 0, fault_requests: int = 1) -> None:
        if mode not in (MODE_DELAY, MODE_LOST_RESPONSE):
            raise ValueError(f"unsupported proxy mode '{mode}'")
        with self._lock:
            self._mode = mode
            self._delay_ms = max(0, int(delay_ms))
            self._remaining = max(1, int(fault_requests))
            self._active = True

    def disarm(self) -> None:
        with self._lock:
            self._active = False

    def decision_for(self, path: str, method: str) -> FaultDecision:
        with self._lock:
            self._request_index += 1
            index = self._request_index
            faulted = False
            if (
                self._active
                and self._remaining > 0
                and (self._path_prefix is None or path.startswith(self._path_prefix))
            ):
                faulted = True
                self._remaining -= 1
            return FaultDecision(
                faulted=faulted,
                request_index=index,
                delay_ms=self._delay_ms if faulted else 0,
                drop_response=faulted and self._mode == MODE_LOST_RESPONSE,
            )

    def record(self, event: str, **payload: Any) -> None:
        with self._lock:
            self._events.append(
                {
                    "event": event,
                    "at": time.time(),
                    **payload,
                }
            )

    def events(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(event) for event in self._events]

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "active": self._active,
                "mode": self._mode,
                "delay_ms": self._delay_ms,
                "remaining_faults": self._remaining,
                "requests_observed": self._request_index,
                "events": len(self._events),
                "origin": self.origin if self._server is not None else None,
            }

    def status(self) -> dict[str, Any]:
        return self.stats()

    # ------------------------------------------------------------------
    # Forwarding
    # ------------------------------------------------------------------
    def forward(
        self,
        method: str,
        path: str,
        headers: Mapping[str, str],
        body: bytes,
        decision: FaultDecision,
    ) -> tuple[int, list[tuple[str, str]], bytes]:
        target = f"{self._upstream_base}{path}" if self._upstream_base else path
        connection_class = (
            http.client.HTTPSConnection
            if self._scheme == "https"
            else http.client.HTTPConnection
        )
        connection = connection_class(
            self._upstream_host, self._upstream_port, timeout=self._request_timeout
        )
        forward_headers = {
            key: value
            for key, value in headers.items()
            if key.lower() not in _HOP_BY_HOP
        }
        forward_headers["Host"] = f"{self._upstream_host}:{self._upstream_port}"
        try:
            connection.request(method, target, body=body or None, headers=forward_headers)
            response = connection.getresponse()
            payload = response.read()
            response_headers = [
                (key, value)
                for key, value in response.getheaders()
                if key.lower() not in _HOP_BY_HOP
            ]
            self.record(
                "dependency_response_received",
                status=response.status,
                bytes=len(payload),
                request_index=decision.request_index,
            )
            return response.status, response_headers, payload
        finally:
            connection.close()


class _ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    server_version = "VeriQFaultProxy/1.0"

    @property
    def proxy(self) -> HttpFaultProxy:
        return self.server.proxy  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        # Never write request URLs (they can contain test inputs) to stderr.
        return None

    def _handle(self) -> None:
        proxy = self.proxy
        length = 0
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        body = self.rfile.read(length) if length else b""
        decision = proxy.decision_for(self.path, self.command)
        proxy.record(
            "request_observed",
            method=self.command,
            path=self.path,
            faulted=decision.faulted,
            request_index=decision.request_index,
        )
        try:
            status, headers, payload = proxy.forward(
                self.command, self.path, dict(self.headers.items()), body, decision
            )
        except Exception as exc:
            proxy.record(
                "dependency_request_failed",
                error=f"{type(exc).__name__}: {exc}",
                request_index=decision.request_index,
            )
            self._respond(502, [("Content-Type", "text/plain")], b"upstream unavailable")
            return

        if decision.drop_response:
            proxy.record(
                "response_discarded",
                status=status,
                bytes=len(payload),
                request_index=decision.request_index,
            )
            # Close without writing anything: the application sees a broken
            # connection, exactly as when a response is lost in transit.
            self.close_connection = True
            try:
                self.connection.close()
            except Exception:  # pragma: no cover
                pass
            return

        if decision.delay_ms:
            proxy.record(
                "response_delayed",
                delay_ms=decision.delay_ms,
                request_index=decision.request_index,
            )
            time.sleep(decision.delay_ms / 1000.0)

        try:
            self._respond(status, headers, payload)
        except (BrokenPipeError, ConnectionResetError):
            # The application already timed out and closed the connection: this
            # is the expected observation for an injected delay.
            proxy.record(
                "client_disconnected",
                request_index=decision.request_index,
                delay_ms=decision.delay_ms,
            )
        else:
            proxy.record(
                "response_delivered",
                request_index=decision.request_index,
                delay_ms=decision.delay_ms,
            )

    def _respond(
        self, status: int, headers: list[tuple[str, str]], payload: bytes
    ) -> None:
        self.send_response(status)
        for key, value in headers:
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if payload:
            self.wfile.write(payload)

    do_GET = _handle
    do_POST = _handle
    do_PUT = _handle
    do_PATCH = _handle
    do_DELETE = _handle
    do_HEAD = _handle
    do_OPTIONS = _handle


__all__ = [
    "FaultDecision",
    "HttpFaultProxy",
    "MODE_DELAY",
    "MODE_LOST_RESPONSE",
]
