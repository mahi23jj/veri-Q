"""Runner/SDK-facing endpoints: create runs and record their event timeline.

Every route here is authenticated with an ``X-API-Key`` header scoped to one
target application. Creating a run does not start any execution.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_target_app
from app.core.database import get_db
from app.models import TargetApp
from app.schemas.experiment_event import ExperimentEventCreate, ExperimentEventResponse
from app.schemas.experiment_run import ExperimentRunResponse
from app.services import run_service

router = APIRouter(tags=["runs"])

_NOT_FOUND = "run or experiment not found"


@router.post(
    "/experiments/{experiment_id}/runs",
    response_model=ExperimentRunResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_run(
    experiment_id: uuid.UUID,
    db: Session = Depends(get_db),
    target_app: TargetApp = Depends(get_current_target_app),
):
    try:
        return run_service.create_run(db, experiment_id, target_app)
    except (run_service.RunNotFoundError, run_service.RunAccessDeniedError) as exc:
        raise HTTPException(status_code=404, detail=_NOT_FOUND) from exc
    except run_service.RunNumberConflictError as exc:
        raise HTTPException(
            status_code=409, detail="concurrent run creation; please retry"
        ) from exc


@router.get("/experiment-runs/{run_id}", response_model=ExperimentRunResponse)
def get_run(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    target_app: TargetApp = Depends(get_current_target_app),
):
    try:
        return run_service.get_run(db, run_id, target_app)
    except (run_service.RunNotFoundError, run_service.RunAccessDeniedError) as exc:
        raise HTTPException(status_code=404, detail=_NOT_FOUND) from exc


@router.get("/experiment-runs/{run_id}/events", response_model=list[ExperimentEventResponse])
def list_events(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    target_app: TargetApp = Depends(get_current_target_app),
):
    try:
        return run_service.list_events(db, run_id, target_app)
    except (run_service.RunNotFoundError, run_service.RunAccessDeniedError) as exc:
        raise HTTPException(status_code=404, detail=_NOT_FOUND) from exc


@router.post(
    "/experiment-runs/{run_id}/events",
    response_model=ExperimentEventResponse,
    status_code=status.HTTP_201_CREATED,
)
def append_event(
    run_id: uuid.UUID,
    payload: ExperimentEventCreate,
    response: Response,
    db: Session = Depends(get_db),
    target_app: TargetApp = Depends(get_current_target_app),
):
    """Append an SDK event. A repeated ``event_id`` returns the stored event."""
    try:
        event, duplicate = run_service.append_event(db, run_id, target_app, payload)
    except (run_service.RunNotFoundError, run_service.RunAccessDeniedError) as exc:
        raise HTTPException(status_code=404, detail=_NOT_FOUND) from exc
    if duplicate:
        response.status_code = status.HTTP_200_OK
    return event
