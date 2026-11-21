"""Recovery Observer: correlate persisted evidence into recovery measurements.

It reuses the existing observability tables. It never writes execution events:
application facts come from ``execution_events`` (SDK) and VeriQ's own facts come
from ``runtime_events`` (runner/injector/broker), each keeping its own authority.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.runtime.recovery import (
    SOURCE_BROKER,
    SOURCE_INJECTOR,
    SOURCE_RUNNER,
    SOURCE_SDK,
    AttemptView,
    EvidenceRecord,
    ObservationResult,
    RecoveryPolicy,
    derive_observation,
)
from app.models.observation import ExecutionEvent, TaskExecution
from app.models.runtime import RuntimeEvent, TestCaseRun
from app.runtime.execution import correlated_executions


@dataclass
class CollectedEvidence:
    attempts: list[TaskExecution]
    result: ObservationResult
    runner_events: list[RuntimeEvent]
    conflicts: list[str]
    notes: list[str]


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class RecoveryObserver:
    def __init__(self, db: Session) -> None:
        self._db = db

    # ------------------------------------------------------------------
    def collect(
        self,
        run: TestCaseRun,
        *,
        policy: RecoveryPolicy,
        fault_activated: bool,
        fault_activation_at: datetime | None = None,
        runner_failure: str | None = None,
        task_submitted: bool = True,
    ) -> CollectedEvidence:
        executions = correlated_executions(
            self._db, target_app_id=run.target_app_id, test_run_id=run.id
        )
        runtime_events = list(
            self._db.scalars(
                select(RuntimeEvent)
                .where(RuntimeEvent.test_case_run_id == run.id)
                .order_by(RuntimeEvent.occurred_at, RuntimeEvent.id)
            ).all()
        )

        evidence: list[EvidenceRecord] = []
        attempts: list[AttemptView] = []
        conflicts: list[str] = []
        notes: list[str] = []
        retry_requests = 0

        for index, execution in enumerate(executions, start=1):
            events = list(
                self._db.scalars(
                    select(ExecutionEvent)
                    .where(ExecutionEvent.task_execution_id == execution.id)
                    .order_by(ExecutionEvent.occurred_at, ExecutionEvent.id)
                ).all()
            )
            types = [event.event_type for event in events]
            retry_requested = "TASK_RETRY_REQUESTED" in types
            retry_requests += sum(1 for event_type in types if event_type == "TASK_RETRY_REQUESTED")
            if "TASK_SUCCEEDED" in types and "TASK_FAILED" in types:
                conflicts.append(
                    f"attempt {index} reported both TASK_SUCCEEDED and TASK_FAILED"
                )
            for event in events:
                evidence.append(
                    EvidenceRecord(
                        source=SOURCE_SDK,
                        event_type=event.event_type,
                        occurred_at=_as_utc(event.occurred_at) or datetime.now(timezone.utc),
                        detail={
                            "attempt": index,
                            "execution_id": str(execution.execution_id),
                            "celery_task_id": execution.celery_task_id,
                            "payload": event.payload or {},
                        },
                    )
                )
            attempts.append(
                AttemptView(
                    index=index,
                    started_at=_as_utc(execution.started_at) or datetime.now(timezone.utc),
                    finished_at=_as_utc(execution.finished_at),
                    status=execution.status,
                    retry_requested=retry_requested,
                )
            )
            evidence.append(
                EvidenceRecord(
                    source=SOURCE_SDK,
                    event_type="TASK_EXECUTION_ATTEMPT",
                    occurred_at=_as_utc(execution.started_at) or datetime.now(timezone.utc),
                    detail={
                        "attempt": index,
                        "status": execution.status,
                        "celery_task_id": execution.celery_task_id,
                        "worker_instance_id": execution.worker_instance_id,
                        "queue_name": execution.queue_name,
                        "duration_ms": execution.duration_ms,
                    },
                )
            )

        for event in runtime_events:
            source = event.source if event.source in (SOURCE_RUNNER, SOURCE_INJECTOR, SOURCE_BROKER) else SOURCE_RUNNER
            evidence.append(
                EvidenceRecord(
                    source=source,
                    event_type=event.event_type,
                    occurred_at=_as_utc(event.occurred_at) or datetime.now(timezone.utc),
                    detail=dict(event.payload or {}),
                )
            )

        extra_missing: list[str] = []
        if conflicts:
            extra_missing.append("CONFLICTING_EXECUTION_EVIDENCE")
        if runner_failure:
            notes.append(f"runner_failure: {runner_failure}")
        if not fault_activated:
            notes.append("fault was not observed as activated")

        result = derive_observation(
            policy=policy,
            attempts=attempts,
            retry_request_count=retry_requests,
            fault_activated=fault_activated,
            evidence=evidence,
            task_submitted=task_submitted,
            fault_activation_at=fault_activation_at,
            extra_missing=extra_missing,
        )
        return CollectedEvidence(
            attempts=executions,
            result=result,
            runner_events=runtime_events,
            conflicts=conflicts,
            notes=notes,
        )


def summarize_attempts(executions: list[TaskExecution]) -> list[dict[str, Any]]:
    return [
        {
            "execution_id": str(execution.execution_id),
            "celery_task_id": execution.celery_task_id,
            "status": execution.status,
            "started_at": execution.started_at.isoformat() if execution.started_at else None,
            "finished_at": execution.finished_at.isoformat() if execution.finished_at else None,
            "worker_instance_id": execution.worker_instance_id,
            "duration_ms": execution.duration_ms,
        }
        for execution in executions
    ]


def runs_with_evidence(db: Session, run: TestCaseRun) -> int:
    return len(
        correlated_executions(db, target_app_id=run.target_app_id, test_run_id=run.id)
    )


__all__ = ["CollectedEvidence", "RecoveryObserver", "summarize_attempts"]


def test_run_id(run_id: uuid.UUID) -> uuid.UUID:  # pragma: no cover - convenience
    return run_id
