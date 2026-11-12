from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Scenario = Literal["crash_after_commit"]


def _strip_non_empty(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("must not be empty")
    return value


class ExperimentCreate(BaseModel):
    target_app_id: uuid.UUID
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    task_name: str = Field(..., min_length=1, max_length=255)
    scenario: Scenario = "crash_after_commit"
    checkpoint_name: str | None = Field(default=None, max_length=150)
    timeout_seconds: int = Field(default=60, gt=0, le=3600)

    @field_validator("name", "task_name")
    @classmethod
    def _fields_not_empty(cls, value: str) -> str:
        return _strip_non_empty(value)


class ExperimentUpdate(BaseModel):
    """PATCH body: every field optional; only DRAFT experiments may be edited."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    task_name: str | None = Field(default=None, min_length=1, max_length=255)
    scenario: Scenario | None = None
    checkpoint_name: str | None = Field(default=None, max_length=150)
    timeout_seconds: int | None = Field(default=None, gt=0, le=3600)

    @field_validator("name", "task_name")
    @classmethod
    def _fields_not_empty(cls, value: str | None) -> str | None:
        return _strip_non_empty(value) if value is not None else None


class ExperimentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    target_app_id: uuid.UUID
    name: str
    description: str | None
    task_name: str
    scenario: str
    checkpoint_name: str | None
    timeout_seconds: int
    status: str
    config_snapshot: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
