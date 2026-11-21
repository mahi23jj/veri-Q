"""Execution Controller: submits the task under test and tracks its identity.

A Celery task id is not an execution attempt: a retry reuses the task id while
creating a new attempt context, and a duplicate logical-job submission can carry
different message identities. The controller therefore records:

* one ``logical_job_id`` per test case run (shared by every delivery);
* the submitted Celery task ids;
* the test-run correlation header (``veriq_operation_id``) the SDK repeats on
  every lifecycle event.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.observation import TaskExecution


class SubmissionError(Exception):
    """The task could not be submitted to the test broker."""


@dataclass(frozen=True)
class SubmissionResult:
    task_id: str
    queue: str
    submitted_at: datetime
    headers: dict[str, str] = field(default_factory=dict)


class ExecutionController:
    """Submits tasks to the isolated broker; never touches the worker runtime."""

    def __init__(
        self,
        *,
        broker_url: str,
        send: Callable[..., str] | None = None,
        task_default_queue: str = "veriq.test",
    ) -> None:
        self._broker_url = broker_url
        self._send = send
        self._default_queue = task_default_queue
        self._app: Any | None = None

    # ------------------------------------------------------------------
    def _celery_app(self) -> Any:
        if self._app is not None:
            return self._app
        try:
            from celery import Celery
        except Exception as exc:  # pragma: no cover - dependency installed in dev
            raise SubmissionError(f"celery is not available: {exc}") from exc
        app = Celery("veriq-runner", broker=self._broker_url)
        app.conf.update(
            task_serializer="json",
            result_serializer="json",
            accept_content=["json"],
            enable_utc=True,
            timezone="UTC",
            broker_connection_retry_on_startup=True,
        )
        self._app = app
        return app

    def submit(
        self,
        *,
        task_name: str,
        payload: Mapping[str, Any],
        queue: str,
        operation_id: str,
        logical_job_id: str,
        task_id: str | None = None,
    ) -> SubmissionResult:
        headers = {
            # Correlates every SDK event of every attempt with this test case run.
            "veriq_operation_id": str(operation_id),
            "veriq_logical_job_id": str(logical_job_id),
            "veriq_test_run_id": str(operation_id),
        }
        identifier = task_id or str(uuid.uuid4())
        submitted_at = datetime.now(timezone.utc)
        if self._send is not None:
            self._send(
                task_name=task_name,
                payload=dict(payload),
                queue=queue,
                task_id=identifier,
                headers=dict(headers),
            )
            return SubmissionResult(
                task_id=identifier, queue=queue, submitted_at=submitted_at, headers=headers
            )

        app = self._celery_app()
        try:
            # ``headers`` is delivered inside the Celery protocol v2 message and
            # surfaced on ``task.request`` where the SDK reads it.
            app.send_task(
                task_name,
                kwargs=dict(payload),
                queue=queue or self._default_queue,
                task_id=identifier,
                headers=headers,
            )
        except Exception as exc:
            raise SubmissionError(f"could not submit '{task_name}': {exc}") from exc
        return SubmissionResult(
            task_id=identifier, queue=queue, submitted_at=submitted_at, headers=headers
        )

    def close(self) -> None:
        app, self._app = self._app, None
        if app is not None:
            try:
                app.close()
            except Exception:  # pragma: no cover - teardown best effort
                pass


# ---------------------------------------------------------------------------
# Observation helpers (correlation is by test-run id, not by task id)
# ---------------------------------------------------------------------------


def correlated_executions(
    db: Session, *, target_app_id: uuid.UUID, test_run_id: uuid.UUID
) -> list[TaskExecution]:
    return list(
        db.scalars(
            select(TaskExecution)
            .where(
                TaskExecution.target_app_id == target_app_id,
                TaskExecution.veriq_operation_id == test_run_id,
            )
            .order_by(TaskExecution.started_at, TaskExecution.id)
        ).all()
    )


def task_is_running(
    db: Session, *, target_app_id: uuid.UUID, test_run_id: uuid.UUID
) -> bool:
    for execution in correlated_executions(db, target_app_id=target_app_id, test_run_id=test_run_id):
        if execution.status in ("RUNNING", "RETRYING"):
            return True
    return False


__all__ = [
    "ExecutionController",
    "SubmissionError",
    "SubmissionResult",
    "correlated_executions",
    "task_is_running",
]
