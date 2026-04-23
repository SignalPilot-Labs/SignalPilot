"""API router registration — wires all endpoint modules into the FastAPI app."""

import logging

from fastapi import FastAPI

from ..deployment import is_cloud_mode
from .health import router as health_router
from .settings import router as settings_router
from .connections import router as connections_router
from .schema import router as schema_router
from .sandboxes import router as sandboxes_router
from .query import router as query_router
from .audit import router as audit_router
from .budget import router as budget_router
from .cache import router as cache_router
from .metrics import router as metrics_router
from .projects import router as projects_router
from .keys import router as keys_router
from .files import router as files_router
from .security import router as security_router
from .byok import router as byok_router

logger = logging.getLogger(__name__)


def register_routers(app: FastAPI) -> None:
    """Include all API routers into the application."""
    app.include_router(health_router)
    app.include_router(settings_router)
    app.include_router(connections_router)
    app.include_router(schema_router)
    if not is_cloud_mode():
        app.include_router(sandboxes_router)
        app.include_router(projects_router)
        app.include_router(files_router)
    else:
        logger.info("Cloud mode: skipping registration of files, projects, sandboxes routers")
    app.include_router(query_router)
    app.include_router(audit_router)
    app.include_router(budget_router)
    app.include_router(cache_router)
    app.include_router(metrics_router)
    app.include_router(keys_router)
    app.include_router(security_router)
    app.include_router(byok_router)
