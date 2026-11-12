from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Experiment, ExperimentRun, TargetApp
from app.schemas.experiment import ExperimentCreate, ExperimentUpdate


class ExperimentNotFoundError(Exception):
    pass


class InvalidTargetAppError(Exception):
    pass


class NotDraftError(Exception):
    pass


class ExperimentInUseError(Exception):
    pass


def create_experiment(db: Session, payload: ExperimentCreate) -> Experiment:
    target_app = db.get(TargetApp, payload.target_app_id)
    if target_app is None:
        raise InvalidTargetAppError(str(payload.target_app_id))

    experiment = Experiment(
        target_app_id=payload.target_app_id,
        name=payload.name,
        description=payload.description,
        task_name=payload.task_name,
        scenario=payload.scenario,
        checkpoint_name=payload.checkpoint_name,
        timeout_seconds=payload.timeout_seconds,
        status="DRAFT",
    )
    db.add(experiment)
    db.commit()
    db.refresh(experiment)
    return experiment


def list_experiments(
    db: Session, skip: int = 0, limit: int = 100, target_app_id: uuid.UUID | None = None
) -> tuple[list[Experiment], int]:
    stmt = select(Experiment)
    if target_app_id is not None:
        stmt = stmt.where(Experiment.target_app_id == target_app_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Experiment.created_at.desc()).offset(skip).limit(limit)).all()
    return list(rows), int(total)


def get_experiment(db: Session, experiment_id: uuid.UUID) -> Experiment:
    experiment = db.get(Experiment, experiment_id)
    if experiment is None:
        raise ExperimentNotFoundError(str(experiment_id))
    return experiment


def update_experiment(db: Session, experiment_id: uuid.UUID, payload: ExperimentUpdate) -> Experiment:
    experiment = get_experiment(db, experiment_id)
    if experiment.status != "DRAFT":
        raise NotDraftError(f"experiment {experiment_id} is {experiment.status}; only DRAFT can be edited")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(experiment, field, value)
    db.commit()
    db.refresh(experiment)
    return experiment


def delete_experiment(db: Session, experiment_id: uuid.UUID) -> None:
    experiment = get_experiment(db, experiment_id)
    if experiment.status != "DRAFT":
        raise NotDraftError(f"experiment {experiment_id} is {experiment.status}; only DRAFT can be deleted")
    has_runs = db.scalar(
        select(func.count()).select_from(ExperimentRun).where(ExperimentRun.experiment_id == experiment.id)
    )
    if has_runs:
        raise ExperimentInUseError(str(experiment_id))
    db.delete(experiment)
    db.commit()
