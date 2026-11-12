"""HTTP transport for the VeriQ backend.

One reusable ``httpx.Client`` per transport (never one per event), bounded
timeouts, the API key sent only in the ``X-API-Key`` header, and backend
errors mapped onto the SDK exception hierarchy.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx

from veriq._version import __version__
from veriq.config import API_PREFIX, VeriQConfig
from veriq.exceptions import (
    VeriQAuthenticationError,
    VeriQClientClosedError,
    VeriQConnectionError,
    VeriQHTTPError,
    VeriQServerError,
    VeriQTimeoutError,
    VeriQValidationError,
)

API_KEY_HEADER = "X-API-Key"
_MAX_BODY_CHARS = 500


def _detail_from_response(response: httpx.Response) -> str:
    """Extract a bounded, human-readable error detail from a response."""
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()[:_MAX_BODY_CHARS]
        if detail is not None:
            return str(detail)[:_MAX_BODY_CHARS]
    text = response.text.strip()
    return text[:_MAX_BODY_CHARS] if text else "no response body"


class HTTPTransport:
    """Synchronous HTTP transport bound to one backend + API key."""

    def __init__(self, config: VeriQConfig, *, client: httpx.Client | None = None) -> None:
        self._config = config
        self._closed = False
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=config.timeout)

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def config(self) -> VeriQConfig:
        """The configuration this transport was built from."""
        return self._config

    def _headers(self) -> dict[str, str]:
        return {
            API_KEY_HEADER: self._config.api_key,
            "Accept": "application/json",
            "User-Agent": f"veriq-sdk/{__version__}",
        }

    def send_event(self, run_id: uuid.UUID, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        """POST one event body; return ``(status_code, response_json)``.

        Raises the mapped SDK exception for transport and HTTP failures. No
        retries happen here: a caller that retries must reuse the same event ID.
        """
        if self._closed:
            raise VeriQClientClosedError("the VeriQ client is closed")

        url = f"{self._config.api_url}/experiment-runs/{run_id}/events"
        try:
            response = self._client.post(
                url, json=body, headers=self._headers(), timeout=self._config.timeout
            )
        except httpx.TimeoutException as exc:
            raise VeriQTimeoutError(
                f"request to the VeriQ backend timed out after {self._config.timeout:g}s"
            ) from exc
        except httpx.HTTPError as exc:
            # httpx messages contain the URL, never request headers.
            raise VeriQConnectionError(
                f"could not reach the VeriQ backend at {self._config.base_url}"
            ) from exc

        if response.status_code in (200, 201):
            try:
                payload = response.json()
            except ValueError as exc:
                raise VeriQHTTPError(
                    "the VeriQ backend returned a non-JSON success response",
                    status_code=response.status_code,
                ) from exc
            if not isinstance(payload, dict):
                raise VeriQHTTPError(
                    "the VeriQ backend returned an unexpected response shape",
                    status_code=response.status_code,
                )
            return response.status_code, payload

        detail = _detail_from_response(response)
        message = f"VeriQ backend rejected the event ({response.status_code}): {detail}"

        if response.status_code in (401, 403):
            raise VeriQAuthenticationError(
                message, status_code=response.status_code, response_body=detail
            )
        if response.status_code in (400, 404, 409, 422):
            raise VeriQValidationError(
                message, status_code=response.status_code, response_body=detail
            )
        if response.status_code >= 500:
            raise VeriQServerError(
                message, status_code=response.status_code, response_body=detail
            )
        raise VeriQHTTPError(
            message, status_code=response.status_code, response_body=detail
        )

    def close(self) -> None:
        """Release the HTTP client. Idempotent. Injected clients are left open."""
        if self._closed:
            return
        self._closed = True
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "HTTPTransport":
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()
