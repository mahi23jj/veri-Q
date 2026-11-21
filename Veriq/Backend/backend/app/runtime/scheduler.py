"""Background scheduling for reliability test runs.

A run always executes in its own database session and is bounded by the
orchestrator's deadlines. Nothing here is required for correctness: the run row
already records its state, so an interrupted process can be recovered.
"""

from __future__ import annotations

import logging
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from app.core.config import settings

logger = logging.getLogger("veriq.runner.scheduler")

_LOCK = threading.Lock()
_EXECUTOR: ThreadPoolExecutor | None = None
_FUTURES: dict[str, Future] = {}


def _executor() -> ThreadPoolExecutor:
    global _EXECUTOR
    with _LOCK:
        if _EXECUTOR is None:
            _EXECUTOR = ThreadPoolExecutor(
                max_workers=max(1, settings.RUNNER_MAX_CONCURRENT_RUNS),
                thread_name_prefix="veriq-runner",
            )
        return _EXECUTOR


def _run(run_id: str) -> None:
    from app.core.database import SessionLocal
    from app.runtime.orchestrator import TestOrchestrator
    from app.runtime.runtime_backend import backend_for_run

    session = SessionLocal()
    try:
        from app.models import TestCaseRun

        run = session.get(TestCaseRun, uuid.UUID(run_id))
        if run is None:
            logger.warning("test case run %s disappeared before execution", run_id)
            return
        backend = backend_for_run(run)
        TestOrchestrator(db=session, backend=backend).execute(run.id)
    except Exception:  # pragma: no cover - defensive; the run row keeps state
        logger.exception("test case run %s crashed the runner thread", run_id)
        try:
            session.rollback()
        except Exception:
            pass
    finally:
        session.close()
        with _LOCK:
            _FUTURES.pop(run_id, None)


def schedule(run_id: uuid.UUID) -> Future:
    future = _executor().submit(_run, str(run_id))
    with _LOCK:
        _FUTURES[str(run_id)] = future
    return future


def is_scheduled(run_id: uuid.UUID) -> bool:
    with _LOCK:
        return str(run_id) in _FUTURES


def active_runs() -> tuple[str, ...]:
    with _LOCK:
        return tuple(sorted(_FUTURES))


def shutdown(wait: bool = False) -> None:
    global _EXECUTOR
    with _LOCK:
        executor, _EXECUTOR = _EXECUTOR, None
        _FUTURES.clear()
    if executor is not None:
        executor.shutdown(wait=wait, cancel_futures=False)


def stats() -> dict[str, Any]:
    with _LOCK:
        return {
            "configured_concurrency": settings.RUNNER_MAX_CONCURRENT_RUNS,
            "scheduled": sorted(_FUTURES),
        }


__all__ = ["active_runs", "is_scheduled", "schedule", "shutdown", "stats"]
