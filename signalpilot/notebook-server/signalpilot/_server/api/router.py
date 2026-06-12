from __future__ import annotations

from typing import TYPE_CHECKING

from signalpilot._server.api.endpoints.agent import router as agent_router
from signalpilot._server.api.endpoints.ai import router as ai_router
from signalpilot._server.api.endpoints.assets import router as assets_router
from signalpilot._server.api.endpoints.branches import (
    router as branches_router,
)
from signalpilot._server.api.endpoints.cache import router as cache_router
from signalpilot._server.api.endpoints.chat import router as chat_router
from signalpilot._server.api.endpoints.config import router as config_router
from signalpilot._server.api.endpoints.datasources import (
    router as datasources_router,
)
from signalpilot._server.api.endpoints.dbt import router as dbt_router
from signalpilot._server.api.endpoints.document import (
    router as document_router,
)
from signalpilot._server.api.endpoints.documentation import (
    router as documentation_router,
)
from signalpilot._server.api.endpoints.editing import router as editing_router
from signalpilot._server.api.endpoints.execution import (
    router as execution_router,
)
from signalpilot._server.api.endpoints.export import router as export_router
from signalpilot._server.api.endpoints.file_explorer import (
    router as file_explorer_router,
)
from signalpilot._server.api.endpoints.files import router as files_router
from signalpilot._server.api.endpoints.fs_events import (
    router as fs_events_router,
)
from signalpilot._server.api.endpoints.git import router as git_router
from signalpilot._server.api.endpoints.health import (
    root_health_router,
    router as health_router,
)
from signalpilot._server.api.endpoints.home import router as home_router
from signalpilot._server.api.endpoints.login import router as login_router
from signalpilot._server.api.endpoints.lsp import router as lsp_router
from signalpilot._server.api.endpoints.mount_config import (
    router as mount_config_router,
)
from signalpilot._server.api.endpoints.notebook_static import (
    router as notebook_static_router,
)
from signalpilot._server.api.endpoints.notion_analysis import (
    router as notion_analysis_router,
)
from signalpilot._server.api.endpoints.packages import (
    router as packages_router,
)
from signalpilot._server.api.endpoints.project_sync import (
    router as project_sync_router,
)
from signalpilot._server.api.endpoints.secrets import router as secrets_router
from signalpilot._server.api.endpoints.sql import router as sql_router
from signalpilot._server.api.endpoints.terminal import (
    router as terminal_router,
)
from signalpilot._server.api.endpoints.ws_endpoint import router as ws_router
from signalpilot._server.router import APIRouter

if TYPE_CHECKING:
    from starlette.routing import BaseRoute


# Define the app routes
def build_routes(base_url: str = "") -> list[BaseRoute]:
    app_router = APIRouter(prefix=base_url)
    app_router.include_router(
        execution_router, prefix="/api/kernel", name="execution"
    )
    app_router.include_router(
        config_router, prefix="/api/kernel", name="config"
    )
    app_router.include_router(
        editing_router, prefix="/api/kernel", name="editing"
    )
    app_router.include_router(files_router, prefix="/api/kernel", name="files")
    app_router.include_router(
        file_explorer_router, prefix="/api/files", name="file_explorer"
    )
    app_router.include_router(
        fs_events_router, prefix="/api/files", name="fs_events"
    )
    app_router.include_router(
        secrets_router, prefix="/api/secrets", name="secrets"
    )
    app_router.include_router(cache_router, prefix="/api/cache", name="cache")
    app_router.include_router(
        documentation_router, prefix="/api/documentation", name="documentation"
    )
    app_router.include_router(
        document_router, prefix="/api/document", name="document"
    )
    app_router.include_router(
        datasources_router, prefix="/api/datasources", name="datasources"
    )
    app_router.include_router(sql_router, prefix="/api/sql", name="sql")
    app_router.include_router(dbt_router, prefix="/api/dbt", name="dbt")
    app_router.include_router(ai_router, prefix="/api/ai", name="ai")
    app_router.include_router(agent_router, prefix="/api/agent", name="agent")
    app_router.include_router(chat_router, prefix="/api/chat", name="chat")
    app_router.include_router(
        branches_router, prefix="/api/branches", name="branches"
    )
    app_router.include_router(
        project_sync_router, prefix="/api/project", name="project_sync"
    )
    app_router.include_router(git_router, prefix="/api/git", name="git")
    app_router.include_router(
        notion_analysis_router,
        prefix="/api/notion-analysis",
        name="notion_analysis",
    )
    app_router.include_router(home_router, prefix="/api/home", name="home")
    app_router.include_router(login_router, prefix="/auth", name="auth")
    app_router.include_router(
        export_router, prefix="/api/export", name="export"
    )
    app_router.include_router(
        terminal_router, prefix="/terminal", name="terminal"
    )
    app_router.include_router(
        packages_router, prefix="/api/packages", name="packages"
    )
    app_router.include_router(lsp_router, prefix="/api/lsp", name="lsp")
    app_router.include_router(health_router, prefix="/api", name="health")
    app_router.include_router(root_health_router, name="root_health")
    app_router.include_router(
        notebook_static_router,
        prefix="/api/notebook",
        name="notebook_static",
    )
    # mount_config_router MUST be last — its /api prefix would shadow
    # more-specific /api/* mounts if placed earlier
    app_router.include_router(
        mount_config_router, prefix="/api", name="mount_config"
    )
    app_router.include_router(ws_router, name="ws")
    app_router.include_router(assets_router, name="assets")

    return app_router.routes
