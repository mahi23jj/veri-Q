"""The public VeriQ client.

The client only builds events and delegates delivery; HTTP details live in
:mod:`veriq.transport.http`. No module-level mutable state is used, so several
clients (for example one per worker process) are independent.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from veriq.config import DEFAULT_TIMEOUT_SECONDS, VeriQConfig
from veriq.events import VeriQEvent
from veriq.exceptions import VeriQClientClosedError, VeriQConfigError, VeriQHTTPError
from veriq.transport.http import HTTPTransport

__all__ = ["VeriQ", "EventReceipt"]


@dataclass(frozen=True)
class EventReceipt:
    """Outcome of one successful ``send_event`` call."""

    event_id: uuid.UUID
    experiment_run_id: uuid.UUID
    server_event_id: uuid.UUID
    duplicate: bool
    status_code: int


class VeriQ:
    """Synchronous client for reporting experiment events to VeriQ.

    Usage::

        veriq = VeriQ(api_url="http://localhost:8000", api_key="vq_...")
        veriq.send_event(run_id, "sdk.test_event", {"message": "ok"})
        veriq.close()
    """

    def __init__(
        self,
        config: VeriQConfig | None = None,
        *,
        api_url: str | None = None,
        api_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport: HTTPTransport | None = None,
    ) -> None:
        if config is not None and (api_url is not None or api_key is not None):
            raise VeriQConfigError("pass either a VeriQConfig or api_url/api_key, not both")
        if config is None and api_url is None and api_key is None and transport is not None:
            # An injected transport carries its own configuration (used by
            # tests and by callers who build a custom transport).
            config = transport.config
        if config is None:
            if api_url is None or api_key is None:
                raise VeriQConfigError("api_url and api_key are required")
            config = VeriQConfig(api_url=api_url, api_key=api_key, timeout=timeout)
        self._config = config
        self._transport = transport if transport is not None else HTTPTransport(config)

    @property
    def closed(self) -> bool:
        return self._transport.closed

    def send_event(
        self,
        experiment_run_id: uuid.UUID | str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        occurred_at: datetime | None = None,
        event_id: uuid.UUID | str | None = None,
    ) -> EventReceipt:
        """Submit one event to the backend and return its receipt.

        Failures raise a :class:`veriq.exceptions.VeriQError` subclass; nothing
        is swallowed. If the caller retries a failed submission, reuse the same
        ``event_id`` so the backend can deduplicate.
        """
        if self._transport.closed:
            raise VeriQClientClosedError("the VeriQ client is closed")

        event = VeriQEvent.create(
            experiment_run_id=experiment_run_id,
            event_type=event_type,
            payload=payload,
            occurred_at=occurred_at,
            event_id=event_id,
        )
        status_code, body = self._transport.send_event(
            event.experiment_run_id, event.to_request_body()
        )
        server_event_id = body.get("id")
        try:
            parsed_server_id = uuid.UUID(str(server_event_id))
        except (TypeError, ValueError) as exc:
            raise VeriQHTTPError(
                "the VeriQ backend response did not include a valid event id",
                status_code=status_code,
            ) from exc
        return EventReceipt(
            event_id=event.event_id,
            experiment_run_id=event.experiment_run_id,
            server_event_id=parsed_server_id,
            duplicate=status_code == 200,
            status_code=status_code,
        )

    def close(self) -> None:
        """Close the underlying HTTP client. Safe to call more than once."""
        self._transport.close()

    def __enter__(self) -> "VeriQ":
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"VeriQ(api_url={self._config.base_url!r}, closed={self.closed})"
