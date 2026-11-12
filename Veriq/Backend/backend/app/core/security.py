"""API-key helpers for authenticating SDK/runner traffic.

Keys are generated once and only their SHA-256 hash is persisted, so a leaked
database dump does not leak usable credentials. The plaintext key is returned
to the caller exactly once, at creation/rotation time.
"""

from __future__ import annotations

import hashlib
import secrets

# Header name used by the SDK and runner. Kept in one place so the API layer
# and documentation cannot drift apart.
API_KEY_HEADER = "X-API-Key"
API_KEY_PREFIX = "vq_"
_API_KEY_ENTROPY_BYTES = 32


def generate_api_key() -> str:
    """Return a new random API key (plaintext, shown to the developer once)."""
    return f"{API_KEY_PREFIX}{secrets.token_urlsafe(_API_KEY_ENTROPY_BYTES)}"


def hash_api_key(api_key: str) -> str:
    """Return the hex SHA-256 digest stored in ``target_apps.api_key_hash``."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()
