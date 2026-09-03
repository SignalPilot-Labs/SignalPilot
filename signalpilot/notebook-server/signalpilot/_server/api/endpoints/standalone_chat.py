"""Standalone chat endpoint façade with backwards-compatible helper exports."""

import httpx

from signalpilot._server.api.endpoints.standalone_chat_cancel import (
    cancel,
    router as cancel_router,
)
from signalpilot._server.api.endpoints.standalone_chat_execution import (
    execute,
    router as execution_router,
)
from signalpilot._server.api.endpoints.standalone_chat_prompt import (
    IMPROVEMENT_EXTRA_TOOLS,
    STANDALONE_ALLOWED_TOOLS,
    STANDALONE_DISALLOWED_MCP_TOOLS,
    STANDALONE_SYSTEM_PROMPT,
)
from signalpilot._server.api.endpoints.standalone_chat_runtime import (
    _ANALYSIS_SESSIONS_BY_RUN,
    _archive_analysis_notebook,
    _notebook_failure,
    _project_is_unchanged,
    _recovery_context,
    _runtime_auth_override,
    _seed_analysis_notebook,
    _tree_digest,
)
from signalpilot._server.router import APIRouter

router = APIRouter()
router.include_router(execution_router)
router.include_router(cancel_router)

__all__ = [
    "IMPROVEMENT_EXTRA_TOOLS",
    "STANDALONE_ALLOWED_TOOLS",
    "STANDALONE_DISALLOWED_MCP_TOOLS",
    "STANDALONE_SYSTEM_PROMPT",
    "_ANALYSIS_SESSIONS_BY_RUN",
    "_archive_analysis_notebook",
    "_notebook_failure",
    "_project_is_unchanged",
    "_recovery_context",
    "_runtime_auth_override",
    "_seed_analysis_notebook",
    "_tree_digest",
    "cancel",
    "execute",
    "httpx",
    "router",
]
