"""Validated SDK configuration.

Credentials are held privately: ``repr()``, ``str()`` and every error message
redact the API key so configuration objects are safe to log.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from veriq.exceptions import VeriQConfigError

DEFAULT_TIMEOUT_SECONDS = 10.0
# Bounded so a hung backend cannot pin a caller's worker process indefinitely.
MAX_TIMEOUT_SECONDS = 120.0
API_PREFIX = "/api/v1"
_MAX_API_KEY_LENGTH = 512


def _normalize_base_url(api_url: str) -> str:
    if not isinstance(api_url, str) or not api_url.strip():
        raise VeriQConfigError("api_url must be a non-empty string")

    candidate = api_url.strip()
    parts = urlsplit(candidate)
    if parts.scheme not in {"http", "https"}:
        raise VeriQConfigError("api_url must start with http:// or https://")
    if not parts.netloc:
        raise VeriQConfigError("api_url must include a host")
    if parts.username or parts.password:
        raise VeriQConfigError("api_url must not embed credentials; pass api_key instead")

    path = parts.path.rstrip("/")
    # Accept both "http://host:8000" and "http://host:8000/api/v1" so a copied
    # dashboard URL works; the transport appends "/api/v1" exactly once.
    if path.endswith(API_PREFIX):
        path = path[: -len(API_PREFIX)]
    if path and not path.startswith("/"):
        path = "/" + path

    return urlunsplit((parts.scheme.lower(), parts.netloc, path, "", ""))


def _validate_api_key(api_key: str) -> str:
    if not isinstance(api_key, str) or not api_key.strip():
        raise VeriQConfigError("api_key must be a non-empty string")
    key = api_key.strip()
    if len(key) > _MAX_API_KEY_LENGTH:
        raise VeriQConfigError("api_key is unreasonably long")
    if any(ch.isspace() for ch in key):
        raise VeriQConfigError("api_key must not contain whitespace")
    return key


def _validate_timeout(timeout: float) -> float:
    try:
        value = float(timeout)
    except (TypeError, ValueError) as exc:
        raise VeriQConfigError("timeout must be a number of seconds") from exc
    if value <= 0:
        raise VeriQConfigError("timeout must be greater than 0 seconds")
    if value > MAX_TIMEOUT_SECONDS:
        raise VeriQConfigError(
            f"timeout must not exceed {MAX_TIMEOUT_SECONDS:g} seconds"
        )
    return value


class VeriQConfig:
    """Immutable-ish configuration for a :class:`veriq.VeriQ` client."""

    __slots__ = ("_api_key", "_base_url", "_timeout")

    def __init__(
        self, api_url: str, api_key: str, *, timeout: float = DEFAULT_TIMEOUT_SECONDS
    ) -> None:
        self._base_url = _normalize_base_url(api_url)
        self._api_key = _validate_api_key(api_key)
        self._timeout = _validate_timeout(timeout)

    @property
    def base_url(self) -> str:
        """Normalized backend root, without a trailing slash or ``/api/v1``."""
        return self._base_url

    @property
    def api_url(self) -> str:
        """Full API root, e.g. ``http://localhost:8000/api/v1``."""
        return f"{self._base_url}{API_PREFIX}"

    @property
    def timeout(self) -> float:
        return self._timeout

    @property
    def api_key(self) -> str:
        """The raw key. Only the transport should read this."""
        return self._api_key

    def redacted(self) -> dict[str, object]:
        """Log-safe view of the configuration."""
        return {"api_url": self.base_url, "timeout": self.timeout, "api_key": "***"}

    def __repr__(self) -> str:
        return (
            f"VeriQConfig(api_url={self.base_url!r}, timeout={self.timeout!r}, "
            "api_key='***')"
        )

    __str__ = __repr__
