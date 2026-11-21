"""Runner Supervisor: the only component with worker-lifecycle authority.

The SDK never receives worker termination authority; it only reports telemetry.
Every operation here is scoped to one ``RunnerWorker`` row and therefore to one
test case run.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.observation import Worker, WorkerQueue
from app.models.runtime import RunnerWorker
from app.runtime.contracts import (
    EnvironmentPlan,
    ProvisionResult,
    RuntimeBackend,
    RuntimeBackendError,
    TerminationResult,
    WorkerHandle,
    WorkerReadyReport,
    WorkerStatus,
)

RecordFn = Callable[[str, str, dict[str, Any]], None]


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class RunnerSupervisor:
    backend: RuntimeBackend
    record: RecordFn | None = None

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.record is not None:
            self.record("RUNNER", event_type, payload)

    # ------------------------------------------------------------------
    def start_worker(
        self,
        db: Session,
        *,
        worker: RunnerWorker,
        plan: EnvironmentPlan,
        provisioned: ProvisionResult,
        env: dict[str, str],
    ) -> RunnerWorker:
        worker.lifecycle_state = "STARTING"
        worker.started_at = _now()
        try:
            handle = self.backend.start_worker(
                plan, provisioned, worker_ref=worker.worker_key, env=env
            )
        except RuntimeBackendError as exc:
            worker.lifecycle_state = "FAILED"
            worker.error = str(exc)
            db.commit()
            self._emit("worker_start_failed", {"worker_key": worker.worker_key, "error": str(exc)})
            raise
        worker.container_ref = handle.container_ref
        worker.hostname = handle.hostname
        db.commit()
        self._emit(
            "worker_started",
            {
                "worker_key": worker.worker_key,
                "container_ref": handle.container_ref,
                "queue": worker.queue_name,
                "concurrency": worker.concurrency,
                "runtime": self.backend.name,
            },
        )
        return worker

    def wait_for_worker_ready(
        self,
        db: Session,
        *,
        worker: RunnerWorker,
        plan: EnvironmentPlan,
        timeout_seconds: int,
        target_app_id: uuid.UUID,
    ) -> WorkerReadyReport:
        handle = self._handle(worker)
        probe = lambda: self._discovery_probe(  # noqa: E731 - small local closure
            db, target_app_id=target_app_id, queue_name=worker.queue_name, since=worker.started_at
        )
        report = self.backend.wait_for_worker_ready(
            handle, plan=plan, timeout_seconds=timeout_seconds, discovery_probe=probe
        )
        if report.ready:
            worker.lifecycle_state = "READY"
            worker.ready_at = _now()
            worker.worker_instance_id = report.worker_instance_id
            db.commit()
            self._emit(
                "worker_ready",
                {
                    "worker_key": worker.worker_key,
                    "queue": worker.queue_name,
                    "worker_instance_id": report.worker_instance_id,
                    "queue_consumed": bool((report.detail or {}).get("queue_consumed")),
                },
            )
        else:
            worker.lifecycle_state = "FAILED"
            worker.error = report.check.detail
            db.commit()
            self._emit("worker_not_ready", {"worker_key": worker.worker_key, "detail": report.check.detail})
        return report

    def terminate_worker(
        self,
        db: Session,
        *,
        worker: RunnerWorker,
        reason: str,
        grace_seconds: int = 0,
    ) -> TerminationResult:
        worker.lifecycle_state = "TERMINATING"
        db.commit()
        self._emit(
            "worker_termination_requested",
            {"worker_key": worker.worker_key, "reason": reason, "grace_seconds": grace_seconds},
        )
        result = self.backend.terminate_worker(
            self._handle(worker), reason=reason, grace_seconds=grace_seconds
        )
        worker.terminated_at = _now()
        worker.termination_reason = reason
        worker.exit_info = dict(result.detail)
        worker.lifecycle_state = "TERMINATED" if result.terminated else "FAILED"
        worker.error = None if result.terminated else result.check.detail
        db.commit()
        self._emit(
            "worker_terminated" if result.terminated else "worker_termination_failed",
            {
                "worker_key": worker.worker_key,
                "reason": reason,
                "detail": result.check.detail,
                **{k: v for k, v in result.detail.items() if k != "reason"},
            },
        )
        return result

    def restart_worker(
        self,
        db: Session,
        *,
        worker: RunnerWorker,
        plan: EnvironmentPlan,
        provisioned: ProvisionResult,
        env: dict[str, str],
        timeout_seconds: int,
        target_app_id: uuid.UUID,
    ) -> RunnerWorker:
        """Start a replacement worker (same key) after an unexpected exit."""
        self._emit("worker_restart_requested", {"worker_key": worker.worker_key})
        return self.start_worker(
            db, worker=worker, plan=plan, provisioned=provisioned, env=env
        )

    def get_worker_status(self, worker: RunnerWorker) -> WorkerStatus:
        return self.backend.worker_status(self._handle(worker))

    def stop_worker(self, db: Session, *, worker: RunnerWorker) -> None:
        if worker.lifecycle_state in ("STOPPED", "TERMINATED", "FAILED"):
            return
        self.backend.stop_worker(self._handle(worker))
        worker.lifecycle_state = "STOPPED"
        db.commit()
        self._emit("worker_stopped", {"worker_key": worker.worker_key})

    # ------------------------------------------------------------------
    def _handle(self, worker: RunnerWorker) -> WorkerHandle:
        return WorkerHandle(
            worker_ref=worker.worker_key,
            container_ref=worker.container_ref,
            hostname=worker.hostname,
            detail={"container_name": worker.hostname} if worker.hostname else {},
        )

    @staticmethod
    def _discovery_probe(
        db: Session,
        *,
        target_app_id: uuid.UUID,
        queue_name: str,
        since: datetime | None,
    ) -> dict[str, Any]:
        """Ask the observation tables whether the worker registered and consumes the queue."""
        stmt = select(Worker).where(Worker.target_app_id == target_app_id)
        workers = list(db.scalars(stmt.order_by(Worker.last_seen_at.desc())).all())
        for worker in workers:
            if since is not None:
                seen = worker.last_seen_at
                if seen is not None and seen.tzinfo is None:
                    seen = seen.replace(tzinfo=timezone.utc)
                boundary = since if since.tzinfo is not None else since.replace(tzinfo=timezone.utc)
                if seen is not None and seen < boundary:
                    continue
            # The worker was started with an explicit ``-Q <queue>``, so a queue
            # reported by a worker process that appeared after this run started
            # is evidence that the run's queue is wired up. ``is_consumed`` is
            # kept as separate information: Celery does not always expose its
            # consumer set to the SDK, so it must not decide readiness.
            queue = db.scalar(
                select(WorkerQueue).where(
                    WorkerQueue.worker_id == worker.id,
                    WorkerQueue.queue_name == queue_name,
                )
            )
            if queue is not None:
                return {
                    "worker_instance_id": worker.worker_instance_id,
                    "queue_reported": True,
                    "queue_consumed": bool(queue.is_consumed),
                    "worker_hostname": worker.worker_hostname,
                }
        return {"worker_instance_id": None, "queue_reported": False, "queue_consumed": False}


__all__ = ["RunnerSupervisor"]
