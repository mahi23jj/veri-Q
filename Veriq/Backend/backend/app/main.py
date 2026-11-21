from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings

logger = logging.getLogger("veriq")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Runs left behind by an interrupted backend are only cleaned up when the
    # operator opts in: finalizing them touches the container runtime.
    if settings.RUNNER_AUTO_RECOVER:
        from app.core.database import SessionLocal
        from app.services import runtime_service

        session = SessionLocal()
        try:
            recovered = runtime_service.recover_interrupted_runs(session)
            if recovered:
                logger.warning("recovered %d interrupted test run(s)", len(recovered))
        except Exception:  # pragma: no cover - startup must not depend on cleanup
            session.rollback()
            logger.exception("could not recover interrupted test runs")
        finally:
            session.close()
    yield
    from app.runtime import scheduler

    scheduler.shutdown(wait=False)


app = FastAPI(
    title="QueueProof",
    description=(
        "Background-job observability and reliability testing for Celery "
        "applications: discovery, planning, isolated execution and evidence-based "
        "recovery verdicts."
    ),
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/")
def root() -> dict:
    return {"service": "QueueProof", "docs": "/docs", "health": "/api/v1/health"}
