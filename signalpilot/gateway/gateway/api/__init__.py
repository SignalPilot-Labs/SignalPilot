"""API router registration — wires all endpoint modules into the FastAPI app."""

from fastapi import FastAPI

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


def register_routers(app: FastAPI) -> None:
    """Include all API routers into the application."""
    app.include_router(health_router)
    app.include_router(settings_router)
    app.include_router(connections_router)
    app.include_router(schema_router)
    app.include_router(sandboxes_router)
    app.include_router(query_router)
    app.include_router(audit_router)
    app.include_router(budget_router)
    app.include_router(cache_router)
    app.include_router(metrics_router)
    app.include_router(projects_router)
    app.include_router(keys_router)
