"""SDK test fixtures.

All HTTP is mocked with ``httpx.MockTransport``; these tests never touch a
running VeriQ backend.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest

from veriq import VeriQ, VeriQConfig
from veriq.transport.http import HTTPTransport

API_URL = "http://backend.test"
API_KEY = "vq_unit_api_key_not_a_real_secret"


def event_response(event_id: uuid.UUID | None = None) -> dict[str, Any]:
    return {
        "id": str(event_id or uuid.uuid4()),
        "experiment_run_id": str(uuid.uuid4()),
        "event_type": "sdk.test_event",
        "source": "SDK",
        "payload": {"message": "SDK communication successful"},
        "occurred_at": "2026-11-11T10:00:00+00:00",
    }


class MockBackend:
    """Queues responses (or transport exceptions) and records requests."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self._queue: list[tuple[str, Any, Any]] = []

    def reply(self, status: int = 201, json_body: Any = None) -> "MockBackend":
        self._queue.append(("response", status, json_body))
        return self

    def raise_error(self, exc: Exception) -> "MockBackend":
        self._queue.append(("raise", exc, None))
        return self

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self._queue:
            raise AssertionError(f"unexpected request: {request.method} {request.url}")
        kind, value, body = self._queue.pop(0)
        if kind == "raise":
            raise value
        if body is None:
            return httpx.Response(value, text="")
        return httpx.Response(value, json=body)

    @property
    def json_bodies(self) -> list[dict[str, Any]]:
        return [httpx.Response(200, content=r.content).json() for r in self.requests]


@pytest.fixture()
def backend() -> MockBackend:
    return MockBackend()


def make_config(**overrides: Any) -> VeriQConfig:
    params: dict[str, Any] = {"api_url": API_URL, "api_key": API_KEY, "timeout": 2.0}
    params.update(overrides)
    return VeriQConfig(**params)


def make_transport(backend: MockBackend, config: VeriQConfig | None = None) -> HTTPTransport:
    client = httpx.Client(transport=httpx.MockTransport(backend.handler))
    return HTTPTransport(config or make_config(), client=client)


@pytest.fixture()
def transport(backend: MockBackend) -> HTTPTransport:
    return make_transport(backend)


@pytest.fixture()
def veriq(backend: MockBackend) -> VeriQ:
    return VeriQ(transport=make_transport(backend))
