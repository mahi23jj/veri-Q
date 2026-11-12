"""Exception hierarchy for the VeriQ SDK.

Every failure the SDK can raise is a :class:`VeriQError`. Messages never contain
the API key or raw HTTP headers, so they are safe to log.
"""

from __future__ import annotations

from typing import Any


class VeriQError(Exception):
    """Base class for every SDK error."""


class VeriQConfigError(VeriQError, ValueError):
    """Invalid SDK configuration (URL, API key, timeout)."""


class VeriQClientClosedError(VeriQError):
    """The client was already closed and cannot send more events."""


class VeriQTransportError(VeriQError):
    """The event could not be delivered (network-level failure)."""


class VeriQConnectionError(VeriQTransportError):
    """No connection to the VeriQ backend could be established."""


class VeriQTimeoutError(VeriQTransportError):
    """The VeriQ backend did not answer within the configured timeout."""


class VeriQHTTPError(VeriQError):
    """The backend answered with an error status.

    ``status_code`` is ``None`` for locally detected validation problems (for
    example an empty ``event_type``) that never reached the backend.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_body: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class VeriQAuthenticationError(VeriQHTTPError):
    """The API key is missing, invalid, or not allowed to reach this run."""


class VeriQValidationError(VeriQHTTPError):
    """The backend rejected the request as invalid, or the event is malformed."""


class VeriQServerError(VeriQHTTPError):
    """The backend failed with a 5xx status. Safe to retry with the same event ID."""
