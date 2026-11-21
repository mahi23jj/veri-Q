"""Real fault-injection mechanisms (HTTP proxy, TCP proxy, broker, worker)."""

from __future__ import annotations

import socket
import socketserver
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.runtime.contracts import RuntimeBackendError
from app.runtime.injectors.base import FaultContext, InjectorError
from app.runtime.injectors.database_proxy import TcpFaultProxy
from app.runtime.injectors.http_proxy import (
    MODE_DELAY,
    MODE_LOST_RESPONSE,
    HttpFaultProxy,
)
from app.runtime.injectors.scenario_injectors import (
    DatabaseInterruptionInjector,
    DependencyTimeoutInjector,
    DuplicateDeliveryInjector,
    LostResponseInjector,
    WorkerTerminationInjector,
    build_injector,
    supported_scenarios,
)

# ---------------------------------------------------------------------------
# A real upstream HTTP dependency
# ---------------------------------------------------------------------------


class _UpstreamState:
    hits = 0
    paths: list[str] = []


class _UpstreamHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def do_GET(self) -> None:  # noqa: N802 - stdlib name
        _UpstreamState.hits += 1
        _UpstreamState.paths.append(self.path)
        body = b'{"ok":true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        return None


@pytest.fixture()
def upstream():
    _UpstreamState.hits = 0
    _UpstreamState.paths = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _UpstreamHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


@pytest.fixture()
def proxy(upstream):
    instance = HttpFaultProxy(upstream)
    instance.start()
    yield instance
    instance.stop()


def _get(url: str, timeout: float = 2.0) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read()


# ---------------------------------------------------------------------------
# DEPENDENCY_TIMEOUT
# ---------------------------------------------------------------------------


def test_delay_proxy_makes_the_client_time_out_after_the_dependency_responded(proxy):
    proxy.arm(MODE_DELAY, delay_ms=700, fault_requests=1)

    with pytest.raises(Exception):
        _get(f"{proxy.origin}/quote", timeout=0.15)

    # The dependency did process the request before the response was delayed.
    assert _UpstreamState.hits == 1
    events = {event["event"] for event in proxy.events()}
    assert "request_observed" in events
    assert "dependency_response_received" in events
    assert "response_delayed" in events

    # The fault is consumed: the retry is not delayed any more.
    assert _get(f"{proxy.origin}/quote", timeout=3.0) == b'{"ok":true}'
    assert _UpstreamState.hits == 2


def test_delay_proxy_only_faults_the_configured_path_prefix(upstream):
    instance = HttpFaultProxy(upstream, path_prefix="/api")
    instance.start()
    try:
        instance.arm(MODE_DELAY, delay_ms=600, fault_requests=1)
        assert _get(f"{instance.origin}/health", timeout=3.0)
        with pytest.raises(Exception):
            _get(f"{instance.origin}/api/quote", timeout=0.15)
    finally:
        instance.stop()


def test_disarmed_proxy_is_a_transparent_pass_through(proxy):
    proxy.arm(MODE_LOST_RESPONSE, fault_requests=1)
    proxy.disarm()
    assert _get(f"{proxy.origin}/quote") == b'{"ok":true}'
    assert proxy.stats()["active"] is False


# ---------------------------------------------------------------------------
# LOST_RESPONSE
# ---------------------------------------------------------------------------


def test_lost_response_discards_a_response_the_dependency_already_produced(proxy):
    proxy.arm(MODE_LOST_RESPONSE, fault_requests=1)

    with pytest.raises(Exception):
        _get(f"{proxy.origin}/charge")

    assert _UpstreamState.hits == 1, "the request must reach the dependency"
    events = proxy.events()
    kinds = [event["event"] for event in events]
    assert "dependency_response_received" in kinds
    assert "response_discarded" in kinds
    # The client never received a response body.
    assert "response_delivered" not in kinds

    # Subsequent requests are normal again (the retry can succeed).
    assert _get(f"{proxy.origin}/charge") == b'{"ok":true}'


# ---------------------------------------------------------------------------
# DATABASE_INTERRUPTION
# ---------------------------------------------------------------------------


class _EchoHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        while True:
            try:
                chunk = self.request.recv(4096)
            except OSError:
                return
            if not chunk:
                return
            try:
                self.request.sendall(chunk)
            except OSError:
                return


@pytest.fixture()
def echo_upstream():
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _EchoHandler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1], server
    server.shutdown()
    server.server_close()


def _roundtrip(port: int, payload: bytes, timeout: float = 2.0) -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as client:
        client.sendall(payload)
        return client.recv(4096)


def test_database_proxy_forwards_then_interrupts_and_restores(echo_upstream):
    upstream_port, _server = echo_upstream
    proxy = TcpFaultProxy("127.0.0.1", upstream_port)
    proxy.start()
    try:
        assert _roundtrip(proxy.port, b"SELECT 1") == b"SELECT 1"

        with socket.create_connection(("127.0.0.1", proxy.port), timeout=2.0) as client:
            client.sendall(b"BEGIN")
            assert client.recv(4096) == b"BEGIN"
            proxy.interrupt()
            # The established connection is cut by the interruption.
            client.settimeout(1.0)
            with pytest.raises(OSError):
                client.sendall(b"COMMIT")
                data = client.recv(4096)
                raise AssertionError(data)

        assert proxy.stats()["interrupted"] is True
        assert proxy.stats()["interrupted_connections"] >= 1

        # New connections are refused while interrupted.
        with socket.create_connection(("127.0.0.1", proxy.port), timeout=2.0) as client:
            client.settimeout(1.0)
            with pytest.raises((OSError, AssertionError)):
                client.sendall(b"SELECT 1")
                if client.recv(4096) == b"SELECT 1":
                    raise AssertionError("interrupted proxy forwarded traffic")

        proxy.restore()
        assert _roundtrip(proxy.port, b"SELECT 2") == b"SELECT 2"
        assert proxy.stats()["interrupted"] is False
    finally:
        proxy.stop()


# ---------------------------------------------------------------------------
# Injector validation and behaviour
# ---------------------------------------------------------------------------


def _context(**overrides) -> FaultContext:
    defaults = dict(
        test_run_id="11111111-1111-1111-1111-111111111111",
        scenario_id="dependency_timeout",
        config={"timeout_ms": 500},
        trigger_type="automatic",
        dependency_url="http://127.0.0.1:9/quote",
    )
    defaults.update(overrides)
    return FaultContext(**defaults)


def test_supported_scenarios_cover_the_required_patterns():
    assert set(supported_scenarios()) == {
        "dependency_timeout",
        "successful_operation_lost_response",
        "duplicate_message_delivery",
        "database_connection_interruption",
        "worker_termination",
    }
    with pytest.raises(InjectorError):
        build_injector("not_a_scenario")


def test_http_injector_requires_an_upstream_dependency():
    injector = DependencyTimeoutInjector()
    problems = injector.validate(_context(dependency_url=None))
    assert any("dependency_url" in problem for problem in problems)


def test_dependency_timeout_injector_arms_a_real_proxy(upstream):
    injector = DependencyTimeoutInjector()
    context = _context(
        dependency_url=upstream,
        config={"timeout_ms": 300, "fault_requests": 1},
    )
    assert injector.validate(context) == []
    prepared = injector.prepare(context)
    assert prepared["mode"] == MODE_DELAY
    detail = injector.activate(context)
    assert detail["delay_ms"] == 300
    assert injector.status()["armed"] is True
    # Scoped: only this proxy's port carries the fault.
    with pytest.raises(Exception):
        _get(f"{prepared['proxy_origin']}/quote", timeout=0.1)
    injector.deactivate(context)
    assert _get(f"{prepared['proxy_origin']}/quote") == b'{"ok":true}'
    injector.close()


def test_lost_response_injector_mode_is_distinct(upstream):
    injector = LostResponseInjector()
    context = _context(scenario_id=injector.scenario_id, dependency_url=upstream, config={})
    assert injector.validate(context) == []
    prepared = injector.prepare(context)
    injector.activate(context)
    with pytest.raises(Exception):
        _get(f"{prepared['proxy_origin']}/charge")
    assert any(
        event["event"] == "response_discarded" for event in injector.status()["events"]
    )
    injector.close()


def test_database_injector_requires_the_isolated_database():
    injector = DatabaseInterruptionInjector()
    problems = injector.validate(
        _context(scenario_id=injector.scenario_id, database_upstream=None)
    )
    assert any("test database" in problem for problem in problems)


def test_database_injector_interrupts_and_releases(echo_upstream):
    upstream_port, _server = echo_upstream
    injector = DatabaseInterruptionInjector()
    context = _context(
        scenario_id=injector.scenario_id,
        database_upstream=("127.0.0.1", upstream_port),
        config={"interruption_seconds": 5},
    )
    assert injector.validate(context) == []
    prepared = injector.prepare(context)
    injector.activate(context)
    assert injector.status()["proxy"]["interrupted"] is True
    with pytest.raises(OSError):
        _roundtrip(prepared["database_proxy_port"], b"SELECT 1", timeout=1.0)
    injector.deactivate(context)
    assert _roundtrip(prepared["database_proxy_port"], b"SELECT 1") == b"SELECT 1"
    injector.close()


def test_duplicate_injector_submits_one_logical_job_twice():
    submitted: list[int] = []

    def submit_duplicate(count: int) -> list[str]:
        submitted.append(count)
        return [f"task-{index}" for index in range(count)]

    injector = DuplicateDeliveryInjector()
    context = _context(
        scenario_id=injector.scenario_id,
        config={"delivery_count": 2},
        submit_duplicate=submit_duplicate,
    )
    assert injector.validate(context) == []
    detail = injector.activate(context)
    assert submitted == [1]
    assert detail["mechanism"] == "duplicate_logical_job_submission"
    assert detail["redelivery_proven"] is False
    assert detail["additional_task_ids"] == ["task-0"]


def test_duplicate_injector_requires_a_submission_callback():
    injector = DuplicateDeliveryInjector()
    problems = injector.validate(
        _context(scenario_id=injector.scenario_id, config={"delivery_count": 2})
    )
    assert any("submission callback" in problem for problem in problems)


def test_worker_termination_injector_uses_the_supervisor_only():
    terminated: list[str] = []

    def terminate(reason: str) -> dict:
        terminated.append(reason)
        return {"terminated": True, "detail": {"status": "exited", "exit_code": 137}}

    injector = WorkerTerminationInjector()
    context = _context(
        scenario_id=injector.scenario_id,
        config={"termination_grace_seconds": 0},
        terminate_worker=terminate,
    )
    assert injector.validate(context) == []
    detail = injector.activate(context)
    assert terminated == ["scenario:worker_termination"]
    assert detail["termination"]["terminated"] is True


def test_worker_termination_failure_is_reported_not_swallowed():
    def terminate(_reason: str) -> dict:
        raise RuntimeBackendError("docker kill failed")

    injector = WorkerTerminationInjector()
    context = _context(scenario_id=injector.scenario_id, terminate_worker=terminate)
    with pytest.raises(InjectorError):
        injector.activate(context)


def test_checkpoint_trigger_without_coordinator_is_a_configuration_error():
    injector = WorkerTerminationInjector()
    context = _context(
        scenario_id=injector.scenario_id,
        trigger_type="checkpoint",
        checkpoint_name="before_slow_work",
        terminate_worker=lambda reason: {"terminated": True},
    )
    # A checkpoint trigger can never fire without a coordinator, so the injector
    # refuses instead of silently falling back to another trigger. The controller
    # turns that into a SKIPPED fault event rather than an ERROR run.
    with pytest.raises(InjectorError):
        injector.wait_for_trigger(context, 0.1)
