"""Workspaces API application factory.

Usage (uvicorn):
    uvicorn workspaces_api.main:app --host 0.0.0.0 --port 3400

Usage (programmatic):
    from workspaces_api.main import create_app
    app = create_app()
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI

from workspaces_api.agent.spawner import StubSpawner
from workspaces_api.config import get_settings
from workspaces_api.db import make_engine, make_sessionmaker
from workspaces_api.errors import register_exception_handlers
from workspaces_api.events.bus import EventBus
from workspaces_api.routes import health_router, runs_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    app.state.engine = engine
    app.state.session_factory = make_sessionmaker(engine)
    app.state.spawner = StubSpawner()
    app.state.bus = EventBus()
    logger.info(
        "workspaces_api starting mode=%s", settings.sp_deployment_mode
    )
    try:
        yield
    finally:
        await engine.dispose()
        logger.info("workspaces_api stopped")


def create_app() -> FastAPI:
    """Build and return the Workspaces API FastAPI application."""
    app = FastAPI(
        title="Workspaces API",
        version="0.0.0",
        lifespan=_lifespan,
    )

    register_exception_handlers(app)

    app.include_router(health_router)
    app.include_router(runs_router)

    return app


app = create_app()
