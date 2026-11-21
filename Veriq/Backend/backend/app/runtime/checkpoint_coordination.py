"""Test-only checkpoint coordination.

A normal checkpoint is report-only telemetry: it never pauses a task. A
reliability test that must inject a fault exactly at a checkpoint uses this
separate, explicitly enabled protocol:

1. the runner registers a waiter for (test case run, checkpoint name);
2. the SDK reports the checkpoint on its normal telemetry request;
3. the backend recognises the report as belonging to the active run (correlated
   through ``veriq_operation_id``), activates the fault **synchronously** while
   handling that report, then answers the SDK;
4. the task continues only after the acknowledgement, so a
   ``before_external_request`` checkpoint is still "before" the request.

Failures are bounded: a missing checkpoint times out, stale or duplicate reports
are ignored, and the application is never blocked indefinitely.

Activation happens in memory here (no database write) so the observation path
keeps a single writer; the runner persists the FaultEvent afterwards.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.runtime import CheckpointWait

# run_id (str) -> activator(checkpoint_name, detail) -> bool
_ACTIVATORS: dict[str, Callable[[str, dict[str, Any]], bool]] = {}
_LOCK = threading.RLock()


def register(run_id: str, activator: Callable[[str, dict[str, Any]], bool]) -> None:
    """Enable checkpoint coordination for one active run."""
    with _LOCK:
        _ACTIVATORS[str(run_id)] = activator


def unregister(run_id: str) -> None:
    with _LOCK:
        _ACTIVATORS.pop(str(run_id), None)


def is_registered(run_id: str) -> bool:
    with _LOCK:
        return str(run_id) in _ACTIVATORS


def registered_runs() -> tuple[str, ...]:
    with _LOCK:
        return tuple(sorted(_ACTIVATORS))


def notify_checkpoint(
    db: Session,
    *,
    operation_id: uuid.UUID | None,
    checkpoint_name: str | None,
    execution_id: uuid.UUID | None,
    celery_task_id: str | None,
    occurred_at: datetime | None = None,
) -> str | None:
    """Called after a checkpoint event is stored; returns the coordination state.

    ``None`` means this checkpoint did not belong to any active test run, which
    is the normal case for production telemetry.
    """
    if operation_id is None or not checkpoint_name:
        return None

    with _LOCK:
        activator = _ACTIVATORS.get(str(operation_id))
    if activator is None:
        return None

    now = occurred_at or datetime.now(timezone.utc)
    existing = db.scalar(
        select(CheckpointWait).where(
            CheckpointWait.test_case_run_id == operation_id,
            CheckpointWait.checkpoint_name == checkpoint_name,
        )
    )
    if existing is not None and existing.state == "ACKNOWLEDGED":
        existing.state = "DUPLICATE"
        existing.detail = {
            **(existing.detail or {}),
            "duplicate_reports": int((existing.detail or {}).get("duplicate_reports", 0)) + 1,
            "last_report_at": now.isoformat(),
        }
        return "DUPLICATE"

    if existing is None:
        existing = CheckpointWait(
            test_case_run_id=operation_id,
            checkpoint_name=checkpoint_name,
            celery_task_id=celery_task_id,
            execution_id=execution_id,
            state="WAITING",
            received_at=now,
        )
        db.add(existing)
    else:
        existing.received_at = now

    started = time.monotonic()
    try:
        activated = bool(
            activator(
                checkpoint_name,
                {
                    "execution_id": str(execution_id) if execution_id else None,
                    "celery_task_id": celery_task_id,
                    "reported_at": now.isoformat(),
                },
            )
        )
    except Exception as exc:  # activation must never break telemetry
        existing.state = "STALE"
        existing.detail = {"error": f"{type(exc).__name__}: {exc}"}
        return "STALE"

    elapsed_ms = int((time.monotonic() - started) * 1000)
    if activated:
        existing.state = "ACKNOWLEDGED"
        existing.acknowledged_at = datetime.now(timezone.utc)
        existing.detail = {
            **(existing.detail or {}),
            "activation_ms": elapsed_ms,
            "activated": True,
        }
        return "ACKNOWLEDGED"

    existing.state = "STALE"
    existing.detail = {
        **(existing.detail or {}),
        "activation_ms": elapsed_ms,
        "activated": False,
        "reason": "activator declined or the run is no longer active",
    }
    return "STALE"


__all__ = [
    "is_registered",
    "notify_checkpoint",
    "register",
    "registered_runs",
    "unregister",
]
