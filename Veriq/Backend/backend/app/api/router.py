from fastapi import APIRouter

from app.api.routes import (
    applications,
    catalog,
    experiments,
    health,
    observations,
    planning,
    runs,
    runtime,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(applications.router)
api_router.include_router(experiments.router)
api_router.include_router(runs.router)
# SDK writes (X-API-Key) before read/control routes so the paths stay explicit.
api_router.include_router(observations.router)
api_router.include_router(catalog.router)
# Reliability-test planning: contracts, adapters, scenarios, matrix and plans.
api_router.include_router(planning.router)
# Reliability-test runtime: isolated execution, faults, recovery and verdicts.
api_router.include_router(runtime.router)
