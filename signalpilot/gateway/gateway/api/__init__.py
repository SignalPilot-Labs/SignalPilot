"""API router registration — wires all endpoint modules into the FastAPI app."""

import logging

from fastapi import FastAPI

from ..dbt_proxy.api import router as dbt_proxy_router
from ..git.http_server import router as git_http_router
from ..runtime.mode import is_cloud_mode
from .agent_runs import router as agent_runs_router
from .audit import router as audit_router
from .budget import router as budget_router
from .byok import router as byok_router
from .cache import router as cache_router
from .chat import router as chat_router
from .connections import router as connections_router
from .files import router as files_router
from .github import router as github_router
from .health import router as health_router
from .keys import router as keys_router
from .knowledge import router as knowledge_router
from .metrics import router as metrics_router
from .notebook_sessions import router as notebook_sessions_router
from .notion import router as notion_router
from .projects import router as projects_router
from .query import router as query_router
from .sandboxes import router as sandboxes_router
from .schema import router as schema_router
from .security import router as security_router
from .settings import router as settings_router
from .user_secrets import router as user_secrets_router
from .workspace_projects import router as workspace_projects_router

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
    app.include_router(knowledge_router)
    app.include_router(notion_router)
    app.include_router(workspace_projects_router)
    app.include_router(chat_router)
    app.include_router(agent_runs_router)
    app.include_router(notebook_sessions_router)
    app.include_router(github_router)
    app.include_router(user_secrets_router)
    app.include_router(git_http_router)
    from ..notebook_proxy import router as notebook_proxy_router

    app.include_router(notebook_proxy_router)
    app.include_router(dbt_proxy_router)
