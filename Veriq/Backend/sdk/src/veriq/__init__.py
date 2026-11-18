"""VeriQ Python SDK.

Reports experiment events, ordinary task-execution telemetry and Celery
discovery to a VeriQ backend.

Celery instrumentation lives in :mod:`veriq.celery` (``from veriq.celery import
integrate``) and is optional: importing this package does not require Celery.
Telemetry is report-only — the SDK never pauses, controls or terminates a
worker.
"""

from veriq._version import __version__
from veriq.client import EventReceipt, VeriQ
from veriq.config import VeriQConfig
from veriq.events import VeriQEvent
from veriq.exceptions import (
    VeriQAuthenticationError,
    VeriQClientClosedError,
    VeriQConfigError,
    VeriQConnectionError,
    VeriQError,
    VeriQHTTPError,
    VeriQServerError,
    VeriQTimeoutError,
    VeriQTransportError,
    VeriQValidationError,
)

__all__ = [
    "VeriQ",
    "VeriQConfig",
    "VeriQEvent",
    "EventReceipt",
    "VeriQError",
    "VeriQConfigError",
    "VeriQClientClosedError",
    "VeriQTransportError",
    "VeriQConnectionError",
    "VeriQTimeoutError",
    "VeriQHTTPError",
    "VeriQAuthenticationError",
    "VeriQValidationError",
    "VeriQServerError",
    "__version__",
]
