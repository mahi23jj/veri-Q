from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import generate_api_key, hash_api_key
from app.models import Experiment, TargetApp
from app.schemas.target_app import TargetAppCreate


class ApplicationNotFoundError(Exception):
    pass


class DuplicateApplicationNameError(Exception):
    pass


class ApplicationInUseError(Exception):
    pass


def create_application(db: Session, payload: TargetAppCreate) -> tuple[TargetApp, str]:
    """Create an application and mint its first API key.

    Returns ``(application, plaintext_api_key)``; only the hash is persisted.
    """
    api_key = generate_api_key()
    app = TargetApp(
        name=payload.name,
        description=payload.description,
        environment=payload.environment,
        api_key_hash=hash_api_key(api_key),
    )
    db.add(app)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateApplicationNameError(payload.name) from exc
    db.refresh(app)
    return app, api_key


def rotate_api_key(db: Session, application_id: uuid.UUID) -> tuple[TargetApp, str]:
    """Replace the application's API key; the old key stops working at once."""
    app = get_application(db, application_id)
    api_key = generate_api_key()
    app.api_key_hash = hash_api_key(api_key)
    db.commit()
    db.refresh(app)
    return app, api_key


def list_applications(db: Session, skip: int = 0, limit: int = 100) -> tuple[list[TargetApp], int]:
    total = db.scalar(select(func.count()).select_from(TargetApp)) or 0
    rows = db.scalars(
        select(TargetApp).order_by(TargetApp.created_at.desc()).offset(skip).limit(limit)
    ).all()
    return list(rows), int(total)


def get_application(db: Session, application_id: uuid.UUID) -> TargetApp:
    app = db.get(TargetApp, application_id)
    if app is None:
        raise ApplicationNotFoundError(str(application_id))
    return app


def delete_application(db: Session, application_id: uuid.UUID) -> None:
    app = get_application(db, application_id)
    has_experiments = db.scalar(
        select(func.count()).select_from(Experiment).where(Experiment.target_app_id == app.id)
    )
    if has_experiments:
        raise ApplicationInUseError(str(application_id))
    db.delete(app)
    db.commit()
