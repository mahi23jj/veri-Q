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

    # ------------------------------------------------------------------
    # Reliability runner (isolated execution layer)
    # ------------------------------------------------------------------
    # The runner is opt-in per application: it needs a runtime profile with an
    # available image. These defaults only bound time and concurrency.
    RUNNER_ENABLED: bool = Field(
        True, description="Allow starting approved test cases in the isolated runner."
    )
    RUNNER_MAX_CONCURRENT_RUNS: int = Field(
        2, description="Maximum concurrent isolated test runs in this backend process."
    )
    RUNNER_PROVISIONING_TIMEOUT_SECONDS: int = Field(180, description="Environment provisioning limit.")
    RUNNER_WORKER_STARTUP_TIMEOUT_SECONDS: int = Field(
        120, description="Dedicated worker readiness limit."
    )
    RUNNER_FAULT_ACTIVATION_TIMEOUT_SECONDS: int = Field(
        45, description="How long a coordinated checkpoint may take to arrive."
    )
    RUNNER_EXECUTION_TIMEOUT_SECONDS: int = Field(120, description="Primary task execution limit.")
    RUNNER_RECOVERY_TIMEOUT_SECONDS: int = Field(150, description="Recovery observation limit.")
    RUNNER_FINALIZATION_TIMEOUT_SECONDS: int = Field(120, description="Cleanup limit.")
    RUNNER_TOTAL_TIMEOUT_SECONDS: int = Field(900, description="Overall run limit.")
    RUNNER_CALLBACK_BASE_URL: str = Field(
        "http://host.docker.internal:8000",
        description="VeriQ API origin as seen from inside the isolated worker container.",
    )
    RUNNER_SUBMIT_HOST: str = Field(
        "",
        description=(
            "Host name this backend uses to reach a run's published broker/database "
            "ports. Empty means auto-detect: host.docker.internal inside a container, "
            "127.0.0.1 on the host."
        ),
    )
    RUNNER_AUTO_RECOVER: bool = Field(
        False,
        description="Finalize environments left behind by an interrupted backend on startup.",
    )
    RUNNER_SIMULATED_ALLOWED: bool = Field(
        True,
        description=(
            "Allow the explicitly non-isolated simulated runtime (tests/demos only). "
            "Production deployments should disable it."
        ),
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
