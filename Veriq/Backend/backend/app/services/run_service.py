"""Service functions for experiment runs and their event timeline.

The platform still has no execution engine: a run is created in PENDING state
and only the events recorded against it exist. Nothing here starts, crashes or
controls a Celery worker.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_api_key
from app.models import Experiment, ExperimentEvent, ExperimentRun, TargetApp
from app.schemas.experiment_event import SDK_EVENT_SOURCE, ExperimentEventCreate


class RunNotFoundError(Exception):
    """The run does not exist."""


class RunAccessDeniedError(Exception):
    """The authenticated target app does not own the run."""


class RunNumberConflictError(Exception):
    """Two concurrent run creations picked the same run_number."""


def get_target_app_for_api_key(db: Session, api_key: str) -> TargetApp | None:
    """Resolve an API key to its target app, or ``None`` when unknown."""
    return db.scalar(select(TargetApp).where(TargetApp.api_key_hash == hash_api_key(api_key)))


def _get_owned_run(db: Session, run_id: uuid.UUID, target_app: TargetApp) -> ExperimentRun:
    run = db.get(ExperimentRun, run_id)
    if run is None:
        raise RunNotFoundError(str(run_id))
    experiment = db.get(Experiment, run.experiment_id)
    if experiment is None or experiment.target_app_id != target_app.id:
        # The run belongs to a different application: do not leak it.
        raise RunAccessDeniedError(str(run_id))
    return run


def _snapshot(experiment: Experiment) -> dict:
    """Freeze the configuration this run was created from."""
    return {
        "experiment_id": str(experiment.id),
        "target_app_id": str(experiment.target_app_id),
        "name": experiment.name,
        "task_name": experiment.task_name,
        "scenario": experiment.scenario,
        "checkpoint_name": experiment.checkpoint_name,
        "timeout_seconds": experiment.timeout_seconds,
        "experiment_config_snapshot": experiment.config_snapshot,
    }


def create_run(db: Session, experiment_id: uuid.UUID, target_app: TargetApp) -> ExperimentRun:
    experiment = db.get(Experiment, experiment_id)
    if experiment is None:
        raise RunNotFoundError(str(experiment_id))
    if experiment.target_app_id != target_app.id:
        raise RunAccessDeniedError(str(experiment_id))

    last_number = db.scalar(
        select(func.max(ExperimentRun.run_number)).where(ExperimentRun.experiment_id == experiment.id)
    )
    run = ExperimentRun(
        experiment_id=experiment.id,
        run_number=int(last_number or 0) + 1,
        status="PENDING",
        config_snapshot=_snapshot(experiment),
        created_at=datetime.now(timezone.utc),
    )
    db.add(run)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise RunNumberConflictError(str(experiment_id)) from exc
    db.refresh(run)
    return run


def get_run(db: Session, run_id: uuid.UUID, target_app: TargetApp) -> ExperimentRun:
    return _get_owned_run(db, run_id, target_app)


def list_events(
    db: Session, run_id: uuid.UUID, target_app: TargetApp
) -> list[ExperimentEvent]:
    run = _get_owned_run(db, run_id, target_app)
    rows = db.scalars(
        select(ExperimentEvent)
        .where(ExperimentEvent.experiment_run_id == run.id)
        .order_by(ExperimentEvent.occurred_at, ExperimentEvent.id)
    ).all()
    return list(rows)


def append_event(
    db: Session, run_id: uuid.UUID, target_app: TargetApp, payload: ExperimentEventCreate
) -> tuple[ExperimentEvent, bool]:
    """Append one event; return ``(event, duplicate)``.

    When the caller supplies ``event_id`` it is treated as an idempotency key.
    Re-submitting the same id returns the stored row instead of a second one,
    so a retrying SDK cannot inflate the evidence timeline.
    """
    run = _get_owned_run(db, run_id, target_app)

    if payload.event_id is not None:
        existing = db.scalar(
            select(ExperimentEvent).where(
                ExperimentEvent.experiment_run_id == run.id,
                ExperimentEvent.client_event_id == payload.event_id,
            )
        )
        if existing is not None:
            return existing, True

    event = ExperimentEvent(
        experiment_run_id=run.id,
        event_type=payload.event_type,
        source=SDK_EVENT_SOURCE,
        payload=payload.payload,
        occurred_at=payload.occurred_at or datetime.now(timezone.utc),
        client_event_id=payload.event_id,
    )
    db.add(event)
    try:
        db.commit()
    except IntegrityError:
        # Concurrent duplicate submission: the unique constraint won.
        db.rollback()
        if payload.event_id is not None:
            existing = db.scalar(
                select(ExperimentEvent).where(
                    ExperimentEvent.experiment_run_id == run.id,
                    ExperimentEvent.client_event_id == payload.event_id,
                )
            )
            if existing is not None:
                return existing, True
        raise
    db.refresh(event)
    return event, False
