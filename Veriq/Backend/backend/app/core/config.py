from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env.

    Required values have no defaults: if DATABASE_URL is missing,
    pydantic-settings raises a ValidationError naming the field, which
    surfaces at startup instead of failing later with a DB error.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    DATABASE_URL: str = Field(..., description="SQLAlchemy database URL, e.g. postgresql+psycopg://user:pw@host:5432/db")
    APP_ENV: str = Field("development", description="development | test | production")
    CORS_ORIGINS: str = Field(
        "http://localhost:5173",
        description="Comma-separated list of allowed CORS origins.",
    )

    @field_validator("DATABASE_URL")
    @classmethod
    def _database_url_not_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("DATABASE_URL must not be empty")
        return value

    @field_validator("APP_ENV")
    @classmethod
    def _app_env_supported(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in {"development", "test", "production"}:
            raise ValueError("APP_ENV must be one of: development, test, production")
        return value

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
