"""FastAPI application factory."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.limits import BodySizeLimitMiddleware, SlidingWindowLimiter
from app.core.logging import configure_logging
from app.core.request_context import REQUEST_ID_HEADER, RequestIdMiddleware
from app.db.session import get_sessionmaker
from app.services.execution.collector import SessionFactory
from app.services.execution.executor import InProcessExecutor, RunExecutor
from app.services.execution.service import sweep_orphaned_runs

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    executor: RunExecutor | None = None,
    session_factory: SessionFactory | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if settings.sweep_orphaned_runs_on_startup:
            try:
                swept = sweep_orphaned_runs(app.state.session_factory)
                if swept:
                    logger.warning("Marked %d orphaned run(s) as errored", swept)
            except Exception:  # the API must still start if the database is down
                logger.exception("Orphaned-run sweep failed")
        yield
        app.state.executor.shutdown()

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        # Interactive docs are handy locally; hide them on the public deployment.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.session_factory = session_factory or get_sessionmaker()
    app.state.executor = executor or InProcessExecutor(
        settings.max_concurrent_runs, watchdog_grace_s=settings.run_watchdog_grace_s
    )
    app.state.run_limiter = SlidingWindowLimiter(settings.run_rate_limit_per_minute)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,  # JWT bearer tokens, not cookies (decision D-14)
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER],
    )
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_bytes)
    # Added last so it runs first and every response (including errors) carries the ID.
    app.add_middleware(RequestIdMiddleware)

    register_exception_handlers(app)
    app.include_router(api_router)
    return app


app = create_app()
