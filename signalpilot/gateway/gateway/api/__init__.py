"""API router registration — wires all endpoint modules into the FastAPI app."""

import logging

from fastapi import Depends, FastAPI

from ..http.middleware.rate_limit import enforce_principal_rate_limit

_rate_dep = [Depends(enforce_principal_rate_limit)]

from ..runtime.mode import is_cloud_mode
from .audit import router as audit_router
from .budget import router as budget_router
from .byok import router as byok_router
from .cache import router as cache_router
from .connections import router as connections_router
from .files import router as files_router
from .health import router as health_router
from .jupyter_adapter import root_router as jupyter_root_router
from .jupyter_adapter import router as jupyter_router
from .keys import router as keys_router
from .metrics import router as metrics_router
from .projects import router as projects_router
from .query import router as query_router
from .sandboxes import router as sandboxes_router
from .schema import router as schema_router
from .sessions import router as sessions_router
from .security import router as security_router
from .settings import router as settings_router

logger = logging.getLogger(__name__)


def register_routers(app: FastAPI) -> None:
    """Include all API routers into the application."""
    app.include_router(health_router, dependencies=_rate_dep)
    app.include_router(settings_router, dependencies=_rate_dep)
    app.include_router(connections_router, dependencies=_rate_dep)
    app.include_router(schema_router, dependencies=_rate_dep)
    if not is_cloud_mode():
        app.include_router(sandboxes_router, dependencies=_rate_dep)
        app.include_router(sessions_router, dependencies=_rate_dep)
        app.include_router(projects_router, dependencies=_rate_dep)
        app.include_router(files_router, dependencies=_rate_dep)
        # Jupyter routers: no rate_dep — WebSocket can't inject Request
        app.include_router(jupyter_router)
        app.include_router(jupyter_root_router)
    else:
        logger.info("Cloud mode: skipping registration of files, projects, sandboxes routers")
    app.include_router(query_router, dependencies=_rate_dep)
    app.include_router(audit_router, dependencies=_rate_dep)
    app.include_router(budget_router, dependencies=_rate_dep)
    app.include_router(cache_router, dependencies=_rate_dep)
    app.include_router(metrics_router, dependencies=_rate_dep)
    app.include_router(keys_router, dependencies=_rate_dep)
    app.include_router(security_router, dependencies=_rate_dep)
    app.include_router(byok_router, dependencies=_rate_dep)
