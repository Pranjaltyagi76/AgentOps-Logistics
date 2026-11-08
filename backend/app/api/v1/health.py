"""Health and version endpoints."""

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import __version__
from app.api.deps import get_app_settings
from app.core.config import Settings
from app.core.errors import ServiceUnavailableError
from app.db.session import get_db, ping

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


class HealthOut(BaseModel):
    status: Literal["ok"]
    db: Literal["ok"]


class VersionOut(BaseModel):
    name: str
    version: str
    git_sha: str
    environment: str


@router.get("/health", response_model=HealthOut)
def health(db: Annotated[Session, Depends(get_db)]) -> HealthOut:
    try:
        ping(db)
    except SQLAlchemyError as exc:
        logger.warning("Database health check failed: %s", type(exc).__name__)
        raise ServiceUnavailableError(
            "Database is unreachable", code="db_unavailable", details={"db": "unavailable"}
        ) from exc
    return HealthOut(status="ok", db="ok")


@router.get("/version", response_model=VersionOut)
def version(settings: Annotated[Settings, Depends(get_app_settings)]) -> VersionOut:
    return VersionOut(
        name=settings.app_name,
        version=__version__,
        git_sha=settings.git_sha,
        environment=settings.app_env,
    )
