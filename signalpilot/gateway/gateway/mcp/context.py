"""Context variables and session helpers for MCP tool calls."""

from __future__ import annotations

import contextvars
import os as _os
from contextlib import asynccontextmanager

from gateway.db.engine import get_session_factory
from gateway.governance.context import current_org_id_var
from gateway.store import Store

# Context variables set by MCPAuthMiddleware with the authenticated user_id and org_id
mcp_user_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("mcp_user_id", default=None)
mcp_org_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("mcp_org_id", default=None)
mcp_raw_key_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("mcp_raw_key", default=None)
# Set by the audit wrapper before a tool runs; child SQL queries link back to this ID
mcp_audit_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("mcp_audit_id", default=None)
mcp_client_ip_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("mcp_client_ip", default=None)
mcp_user_agent_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("mcp_user_agent", default=None)
mcp_scopes_var: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar("mcp_scopes", default=None)
mcp_allowed_connection_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "mcp_allowed_connection", default=None
)
mcp_capabilities_var: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar(
    "mcp_capabilities", default=None
)
mcp_execution_identity_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "mcp_execution_identity", default=None
)
# Session-JWT project pin (chat/notebook sessions) — lets project-scoped tools
# (dbt_execute) resolve their workspace without a request parameter the agent
# could spoof.
mcp_project_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "mcp_project_id", default=None
)
mcp_branch_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "mcp_branch", default=None
)
# Evaluation document identifiers are bound to the stored API key.
# Knowledge tools include these proposed documents with active documents during a run.
mcp_eval_doc_ids_var: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar(
    "mcp_eval_doc_ids", default=None
)
# The stored API key binds the run to one connection.
# Access to another connection can disclose the expected result and invalidate the grade.
# The server sets this binding. The agent cannot remove it through a request header.
mcp_eval_connection_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "mcp_eval_connection", default=None
)
# The stored API key binds each tool call to a run and task.
# Audit metadata records this attribution for observed coverage.
mcp_eval_run_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "mcp_eval_run", default=None
)
mcp_eval_task_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "mcp_eval_task", default=None
)

_is_cloud = _os.environ.get("SP_DEPLOYMENT_MODE") == "cloud"


@asynccontextmanager
async def _store_session(user_id: str | None = None, org_id: str | None = None):
    """Create a Store with a managed DB session for MCP tool calls.

    If user_id or org_id are not provided, reads from the context variables set
    by MCPAuthMiddleware during key validation.

    Sets current_org_id_var for the duration of the context and resets it on exit.
    MCP tool calls share the same asyncio task across calls via the FastMCP server
    loop, so we must use explicit try/finally reset here (unlike HTTP request
    handlers where FastAPI provides task-level isolation).
    """
    if user_id is None:
        user_id = mcp_user_id_var.get(None)
    if org_id is None:
        org_id = mcp_org_id_var.get(None)
    if not org_id:
        raise RuntimeError(
            "MCP _store_session invoked with no org_id — mcp_org_id_var was not set by MCPAuthMiddleware. "
            "Check auth/mcp_api_key.py local/cloud branches both call mcp_org_id_var.set(...)."
        )
    token = current_org_id_var.set(org_id)
    try:
        factory = get_session_factory()
        async with factory() as session:
            yield Store(
                session,
                org_id=org_id,
                user_id=user_id,
                eval_connection=mcp_eval_connection_var.get(None),
                allowed_connection_name=mcp_allowed_connection_var.get(None),
            )
    finally:
        current_org_id_var.reset(token)


def _require_mcp_admin_scope() -> str | None:
    """Return None if the caller has admin scope; otherwise a user-facing error string.

    Local no-key sessions receive every valid scope from MCPAuthMiddleware.
    Stored local keys are checked exactly like stored cloud keys.
    """
    scopes = mcp_scopes_var.get(None) or []
    if "admin" in scopes:
        return None
    return "Error: admin scope required for this action"


def _require_mcp_scope(scope: str) -> str | None:
    """Mirror the flat HTTP API-key scope model for every MCP tool call."""
    scopes = mcp_scopes_var.get(None)
    if scopes is None:
        return f"Error: authentication context missing; {scope} scope required"
    if scope in scopes:
        return None
    return f"Error: {scope} scope required for this action"


def _gateway_url() -> str:
    """Get the gateway API URL for internal calls from MCP to REST."""
    import os

    return os.environ.get("SP_GATEWAY_URL", "http://localhost:3300")


def _gw_headers() -> dict[str, str]:
    """Build auth headers for internal MCP->gateway HTTP calls."""
    key = mcp_raw_key_var.get(None)
    if key:
        if key.startswith("sp_"):
            return {"X-API-Key": key}
        return {"Authorization": f"Bearer {key}"}
    return {}
