"""The enforcement point (R1): Streamable HTTP MCP endpoint per connector for the sandbox.

Auth: the run's gateway session JWT (notebook-session token) carrying the
``mcp_proxy`` capability. The caller (org, user, run) comes from the token;
tool policy is enforced per call and every ``tools/call`` is audited.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from gateway.db.models import GatewayChatConversation, GatewayChatRun
from gateway.mcp_connectors.proxy_server import ConnectorProxy, McpProxyResponse, ProxyCaller
from gateway.security.scope_guard import RequireScope
from gateway.store.mcp import connectors as connector_store

from ..deps import StoreD
from .common import caller, require_enabled

logger = logging.getLogger(__name__)
router = APIRouter()

PROXY_CAPABILITY = "mcp_proxy"


async def _resolve_caller(request: Request, store: StoreD) -> ProxyCaller:
    auth = getattr(request.state, "auth", None) or {}
    if auth.get("auth_method") != "notebook_session":
        raise HTTPException(status_code=403, detail="The connector proxy accepts run session tokens only")
    if PROXY_CAPABILITY not in (auth.get("capabilities") or []):
        raise HTTPException(status_code=403, detail="This run may not use connectors")
    org_id, user_id = caller(store)
    identity = auth.get("execution_identity") or ""
    run_id = identity.removeprefix("chat:") if isinstance(identity, str) and identity.startswith("chat:") else None
    conversation_id = None
    run_origin = "user"
    if run_id:
        row = (
            await store.session.execute(
                select(GatewayChatRun.conversation_id, GatewayChatConversation.origin)
                .join(GatewayChatConversation, GatewayChatConversation.id == GatewayChatRun.conversation_id, isouter=True)
                .where(GatewayChatRun.id == run_id, GatewayChatRun.org_id == org_id)
            )
        ).first()
        if row is not None:
            conversation_id = row[0]
            run_origin = row[1] or "user"
    return ProxyCaller(
        org_id=org_id, user_id=user_id, run_id=run_id, conversation_id=conversation_id, run_origin=run_origin
    )


async def _serve(connector_id: str, request: Request, store: StoreD) -> McpProxyResponse:
    require_enabled()
    proxy_caller = await _resolve_caller(request, store)
    connector = await connector_store.get_connector(store.session, org_id=proxy_caller.org_id, connector_id=connector_id)
    if connector is None or not connector_store.is_visible_to(connector, user_id=proxy_caller.user_id, is_admin=False):
        raise HTTPException(status_code=404, detail="Connector not found")
    if connector.transport == "stdio":
        raise HTTPException(status_code=400, detail="Sandbox connectors are not proxied")
    proxy = ConnectorProxy(store.session, connector, proxy_caller)
    return McpProxyResponse(proxy.build_server())


@router.post("/proxy/{connector_id}/mcp", dependencies=[RequireScope("execute")])
async def proxy_post(connector_id: str, request: Request, store: StoreD) -> McpProxyResponse:
    return await _serve(connector_id, request, store)


@router.get("/proxy/{connector_id}/mcp", dependencies=[RequireScope("execute")])
async def proxy_get(connector_id: str, request: Request, store: StoreD) -> McpProxyResponse:
    """Stateless transport: the SDK answers GET with 405, which the client tolerates."""
    return await _serve(connector_id, request, store)
