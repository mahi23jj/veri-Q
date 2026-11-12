"""Shared API dependencies."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import API_KEY_HEADER
from app.models import TargetApp
from app.services import run_service

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="invalid or missing API key",
    headers={"WWW-Authenticate": "ApiKey"},
)


def get_current_target_app(
    api_key: str | None = Header(default=None, alias=API_KEY_HEADER),
    db: Session = Depends(get_db),
) -> TargetApp:
    """Authenticate SDK/runner requests with the ``X-API-Key`` header.

    The header value is never logged or echoed back in the error message.
    """
    if not api_key or not api_key.strip():
        raise _UNAUTHORIZED
    target_app = run_service.get_target_app_for_api_key(db, api_key.strip())
    if target_app is None:
        raise _UNAUTHORIZED
    return target_app
