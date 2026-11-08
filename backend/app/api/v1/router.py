"""Aggregates all v1 routers under the /api/v1 prefix."""

from fastapi import APIRouter

from app.api.v1 import auth, health, scenarios, taxonomy

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(taxonomy.router)
api_router.include_router(scenarios.router)
