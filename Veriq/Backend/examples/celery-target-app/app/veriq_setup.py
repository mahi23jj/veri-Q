"""VeriQ SDK initialisation shared by the API process and both Celery workers.

The integration is optional: when ``VERIQ_API_URL`` or ``VERIQ_API_KEY`` is
missing the application runs exactly as before. When present, the SDK reports
task lifecycle telemetry, worker/queue discovery and report-only checkpoints.
"""

from __future__ import annotations

import os

from app.celery_app import celery_app

_client = None
_integration = None


def get_veriq():
    """Build (once) the SDK client from the environment, or return ``None``."""
    global _client
    if _client is not None:
        return _client
    api_url = os.environ.get("VERIQ_API_URL")
    api_key = os.environ.get("VERIQ_API_KEY")
    if not api_url or not api_key:
        return None

    from veriq import VeriQ

    _client = VeriQ(api_url=api_url, api_key=api_key)
    return _client


def integrate_celery():
    """Install Celery signal handlers once per process, when configured."""
    global _integration
    client = get_veriq()
    if client is None:
        return None
    if _integration is None:
        from veriq.celery import integrate

        _integration = integrate(celery_app, client)
    return _integration


def checkpoint(name: str, payload: dict | None = None) -> None:
    """Report a read-only checkpoint if the SDK is configured."""
    client = get_veriq()
    if client is not None:
        client.checkpoint(name, payload)
