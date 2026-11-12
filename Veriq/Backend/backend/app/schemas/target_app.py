from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Environment = Literal["development", "test"]


class TargetAppCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    description: str | None = None
    environment: Environment = "development"

    @field_validator("name")
    @classmethod
    def _name_not_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class TargetAppResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    environment: str
    created_at: datetime
    updated_at: datetime


class TargetAppCreatedResponse(TargetAppResponse):
    """Creation/rotation response: the plaintext API key is returned once.

    It is never stored in plaintext and never returned by list/get.
    """

    api_key: str


class PaginatedResponse(BaseModel):
    items: list
    total: int
    skip: int
    limit: int
