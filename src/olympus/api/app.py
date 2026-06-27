"""FastAPI application factory.

``create_app`` builds and configures the ASGI application: logging, middleware,
exception handlers, CORS, lifecycle (startup/shutdown of the DB engine), and the
versioned routers. Using a factory (rather than a module-level app) makes the
app trivially constructible in tests with overridden settings.

Per the architecture, the API is a thin edge; this module wires it, it contains
no business logic.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from olympus import __version__
from olympus.api.middleware import RequestContextMiddleware
from olympus.api.v1.router import api_v1_router
from olympus.data.database.engine import create_engine, dispose_engine
from olympus.platform.config import Settings, get_settings
from olympus.platform.config.settings import Environment
from olympus.platform.errors import register_exception_handlers
from olympus.platform.logging import configure_logging, get_logger

log = get_logger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage startup/shutdown resources (the DB engine/pool)."""

    settings: Settings = app.state.settings
    log.info("api_startup", environment=settings.environment.value, version=__version__)
    create_engine(settings)
    # Start the Workflow Engine's worker pool and recover any in-flight workflows
    # after a restart. Skipped under TESTING so unit tests drive their own
    # workflow service instances deterministically (no stray background pool).
    workflow_started = False
    if settings.environment is not Environment.TESTING:
        try:
            from olympus.api.dependencies import workflow_service_provider

            service = workflow_service_provider()
            await service.recover()
            service.start_pool()
            workflow_started = True
            log.info("workflow_pool_started")
        except Exception as exc:  # never let orchestration startup block the API
            log.error("workflow_startup_error", error=str(exc))
    try:
        yield
    finally:
        if workflow_started:
            try:
                from olympus.api.dependencies import workflow_service_provider

                await workflow_service_provider().stop_pool()
            except Exception as exc:
                log.error("workflow_shutdown_error", error=str(exc))
        await dispose_engine()
        log.info("api_shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""

    settings = settings or get_settings()
    configure_logging(settings)

    app = FastAPI(
        title="Project Olympus API",
        version=__version__,
        # Hide interactive docs in production.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
        lifespan=_lifespan,
    )
    app.state.settings = settings

    # Middleware (order matters: request-context outermost).
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    # Versioned API routes.
    app.include_router(api_v1_router, prefix="/api/v1")

    return app
