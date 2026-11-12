from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.target_app import (
    PaginatedResponse,
    TargetAppCreate,
    TargetAppCreatedResponse,
    TargetAppResponse,
)
from app.services import application_service

router = APIRouter(prefix="/applications", tags=["applications"])


@router.post("", response_model=TargetAppCreatedResponse, status_code=status.HTTP_201_CREATED)
def create_application(payload: TargetAppCreate, db: Session = Depends(get_db)):
    """Register an application. The returned ``api_key`` is shown only once."""
    try:
        app, api_key = application_service.create_application(db, payload)
    except application_service.DuplicateApplicationNameError as exc:
        raise HTTPException(status_code=409, detail=f"application name already exists: {exc}") from exc
    return TargetAppCreatedResponse(
        **TargetAppResponse.model_validate(app).model_dump(), api_key=api_key
    )


@router.post("/{application_id}/api-key", response_model=TargetAppCreatedResponse)
def rotate_api_key(application_id: uuid.UUID, db: Session = Depends(get_db)):
    """Issue a new API key for an existing application (invalidates the old one)."""
    try:
        app, api_key = application_service.rotate_api_key(db, application_id)
    except application_service.ApplicationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="application not found") from exc
    return TargetAppCreatedResponse(
        **TargetAppResponse.model_validate(app).model_dump(), api_key=api_key
    )


@router.get("", response_model=PaginatedResponse)
def list_applications(
    skip: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db)
):
    items, total = application_service.list_applications(db, skip=skip, limit=limit)
    return {
        "items": [TargetAppResponse.model_validate(i) for i in items],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.get("/{application_id}", response_model=TargetAppResponse)
def get_application(application_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        return application_service.get_application(db, application_id)
    except application_service.ApplicationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="application not found") from exc


@router.delete("/{application_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_application(application_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        application_service.delete_application(db, application_id)
    except application_service.ApplicationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="application not found") from exc
    except application_service.ApplicationInUseError as exc:
        raise HTTPException(
            status_code=409,
            detail="application cannot be deleted while experiments reference it",
        ) from exc
    return None
