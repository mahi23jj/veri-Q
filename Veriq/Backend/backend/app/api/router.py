from fastapi import APIRouter

from app.api.routes import applications, experiments, health, runs

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(applications.router)
api_router.include_router(experiments.router)
api_router.include_router(runs.router)
