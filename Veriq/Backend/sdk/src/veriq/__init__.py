"""VeriQ Python SDK.

Reports experiment events from a target application to a VeriQ backend.

This first milestone is transport only: no Celery instrumentation, no
automatic execution identity, no checkpoints, and no failure injection.
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
