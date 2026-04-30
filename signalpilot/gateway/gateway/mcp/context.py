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
            "Check mcp_auth.py local/cloud branches both call mcp_org_id_var.set(...)."
        )
    token = current_org_id_var.set(org_id)
    try:
        factory = get_session_factory()
        async with factory() as session:
            yield Store(session, org_id=org_id, user_id=user_id)
    finally:
        current_org_id_var.reset(token)


def _gateway_url() -> str:
    """Get the gateway API URL for internal MCP→REST calls."""
    import os

    return os.environ.get("SP_GATEWAY_URL", "http://localhost:3300")


def _gw_headers() -> dict[str, str]:
    """Build auth headers for internal MCP->gateway HTTP calls."""
    key = mcp_raw_key_var.get(None)
    if key:
        return {"X-API-Key": key}
    return {}
