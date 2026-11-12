"""Test isolation strategy.

Tests never touch the development database: they run against a throwaway
SQLite file (``queueproof_test.db`` in the backend dir, deleted at session
end) whose schema is created from the SQLAlchemy metadata. The JSONB columns
use a ``with_variant(JSON, "sqlite")`` so the same models work on PostgreSQL
(JSONB) in production and SQLite in tests.

Alembic migrations are verified separately via ``alembic upgrade --sql``
(see README), which renders the PostgreSQL DDL without a live server.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Generator
from pathlib import Path

# Settings must exist before app.core.config is imported.
os.environ.setdefault("DATABASE_URL", "sqlite:///./queueproof_test.db")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("CORS_ORIGINS", "http://testserver")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.database import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402

TEST_DB = Path(__file__).resolve().parents[1] / "queueproof_test.db"


@pytest.fixture(scope="session", autouse=True)
def _clean_test_db():
    if TEST_DB.exists():
        TEST_DB.unlink()
    yield
    if TEST_DB.exists():
        TEST_DB.unlink()


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
