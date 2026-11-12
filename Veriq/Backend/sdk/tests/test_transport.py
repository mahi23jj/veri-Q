import uuid

import httpx
import pytest

from veriq import VeriQEvent
from veriq.exceptions import (
    VeriQAuthenticationError,
    VeriQClientClosedError,
    VeriQConnectionError,
    VeriQError,
    VeriQHTTPError,
    VeriQServerError,
    VeriQTimeoutError,
    VeriQValidationError,
)
from veriq.transport.http import HTTPTransport

from .conftest import API_KEY, API_URL, MockBackend, event_response, make_config, make_transport


def _send(transport: HTTPTransport, run_id: uuid.UUID | None = None) -> tuple[int, dict]:
    event = VeriQEvent.create(run_id or uuid.uuid4(), "sdk.test_event", {"message": "hi"})
    return transport.send_event(event.experiment_run_id, event.to_request_body())


def test_authentication_header_and_url(transport: HTTPTransport, backend: MockBackend):
    run_id = uuid.uuid4()
    backend.reply(201, event_response())
    _send(transport, run_id)

    request = backend.requests[0]
    assert request.method == "POST"
    assert str(request.url) == f"{API_URL}/api/v1/experiment-runs/{run_id}/events"
    assert request.headers["X-API-Key"] == API_KEY
    assert request.headers["User-Agent"].startswith("veriq-sdk/")
    assert backend.json_bodies[0]["event_type"] == "sdk.test_event"
    assert uuid.UUID(backend.json_bodies[0]["event_id"])


def test_successful_submission_returns_status_and_body(transport: HTTPTransport, backend: MockBackend):
    expected = event_response()
    backend.reply(201, expected)
    status, body = _send(transport)
    assert status == 201
    assert body == expected


@pytest.mark.parametrize("status", [401, 403])
def test_authentication_errors(transport: HTTPTransport, backend: MockBackend, status: int):
    backend.reply(status, {"detail": "invalid or missing API key"})
    with pytest.raises(VeriQAuthenticationError) as excinfo:
        _send(transport)
    assert excinfo.value.status_code == status
    assert "invalid or missing API key" in str(excinfo.value)
    assert API_KEY not in str(excinfo.value)


@pytest.mark.parametrize("status", [404, 422])
def test_validation_errors(transport: HTTPTransport, backend: MockBackend, status: int):
    backend.reply(status, {"detail": "run or experiment not found"})
    with pytest.raises(VeriQValidationError) as excinfo:
        _send(transport)
    assert excinfo.value.status_code == status


def test_server_error_is_not_reported_as_user_error(transport: HTTPTransport, backend: MockBackend):
    backend.reply(503, {"detail": "database unavailable"})
    with pytest.raises(VeriQServerError) as excinfo:
        _send(transport)
    assert excinfo.value.status_code == 503
    assert not isinstance(excinfo.value, VeriQValidationError)


def test_unexpected_client_error_maps_to_base_http_error(transport: HTTPTransport, backend: MockBackend):
    backend.reply(418, {"detail": "teapot"})
    with pytest.raises(VeriQHTTPError) as excinfo:
        _send(transport)
    assert excinfo.value.status_code == 418


def test_non_json_error_body_still_raises_clearly(transport: HTTPTransport, backend: MockBackend):
    backend.reply(502, None)
    with pytest.raises(VeriQServerError):
        _send(transport)


def test_connection_failure(transport: HTTPTransport, backend: MockBackend):
    backend.raise_error(httpx.ConnectError("connection refused"))
    with pytest.raises(VeriQConnectionError) as excinfo:
        _send(transport)
    assert API_URL in str(excinfo.value)
    assert API_KEY not in str(excinfo.value)


def test_request_timeout(transport: HTTPTransport, backend: MockBackend):
    backend.raise_error(httpx.ReadTimeout("timed out"))
    with pytest.raises(VeriQTimeoutError) as excinfo:
        _send(transport)
    assert "timed out" in str(excinfo.value)


def test_timeout_uses_configured_bound(backend: MockBackend):
    # A timeout passed per request is what bounds a hung backend.
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["timeout"] = request.extensions.get("timeout")
        return httpx.Response(201, json=event_response())

    transport = HTTPTransport(
        make_config(timeout=3.0), client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    _send(transport)
    assert seen["timeout"] == {"connect": 3.0, "read": 3.0, "write": 3.0, "pool": 3.0}


def test_transport_closes_owned_client():
    transport = HTTPTransport(make_config())
    owned = transport._client
    assert not owned.is_closed
    transport.close()
    assert transport.closed
    assert owned.is_closed
    transport.close()  # idempotent
    assert owned.is_closed


def test_injected_client_is_not_closed_by_transport(backend: MockBackend):
    transport = make_transport(backend)
    injected = transport._client
    transport.close()
    assert transport.closed
    assert not injected.is_closed
    injected.close()


def test_using_closed_transport_raises(backend: MockBackend):
    transport = make_transport(backend)
    transport.close()
    with pytest.raises(VeriQClientClosedError):
        _send(transport)
    assert backend.requests == []


def test_all_transport_errors_share_the_sdk_base_class(backend: MockBackend):
    assert issubclass(VeriQAuthenticationError, VeriQError)
    assert issubclass(VeriQValidationError, VeriQError)
    assert issubclass(VeriQTimeoutError, VeriQError)
    assert issubclass(VeriQConnectionError, VeriQError)
