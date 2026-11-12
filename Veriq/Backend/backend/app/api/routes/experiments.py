from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.experiment import ExperimentCreate, ExperimentResponse, ExperimentUpdate
from app.schemas.target_app import PaginatedResponse
from app.services import experiment_service

router = APIRouter(prefix="/experiments", tags=["experiments"])


@router.post("", response_model=ExperimentResponse, status_code=status.HTTP_201_CREATED)
def create_experiment(payload: ExperimentCreate, db: Session = Depends(get_db)):
    try:
        return experiment_service.create_experiment(db, payload)
    except experiment_service.InvalidTargetAppError as exc:
        raise HTTPException(status_code=422, detail=f"target_app_id does not reference an existing application: {exc}") from exc


@router.get("", response_model=PaginatedResponse)
def list_experiments(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    target_app_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
):
    items, total = experiment_service.list_experiments(db, skip=skip, limit=limit, target_app_id=target_app_id)
    return {
        "items": [ExperimentResponse.model_validate(i) for i in items],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.get("/{experiment_id}", response_model=ExperimentResponse)
def get_experiment(experiment_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        return experiment_service.get_experiment(db, experiment_id)
    except experiment_service.ExperimentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="experiment not found") from exc


@router.patch("/{experiment_id}", response_model=ExperimentResponse)
def update_experiment(experiment_id: uuid.UUID, payload: ExperimentUpdate, db: Session = Depends(get_db)):
    try:
        return experiment_service.update_experiment(db, experiment_id, payload)
    except experiment_service.ExperimentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="experiment not found") from exc
    except experiment_service.NotDraftError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/{experiment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_experiment(experiment_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        experiment_service.delete_experiment(db, experiment_id)
    except experiment_service.ExperimentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="experiment not found") from exc
    except experiment_service.NotDraftError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except experiment_service.ExperimentInUseError as exc:
        raise HTTPException(status_code=409, detail="experiment cannot be deleted while runs reference it") from exc
    return None
