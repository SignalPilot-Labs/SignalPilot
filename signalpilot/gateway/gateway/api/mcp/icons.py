"""Connector icon route: the provider favicon, proxied through the gateway (CSP img-src)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from gateway.auth import OrgRole
from gateway.mcp_connectors import icons
from gateway.security.scope_guard import RequireScope

from ..deps import StoreD
from .common import caller, is_admin, load_connector, require_enabled

router = APIRouter()

_CACHE_CONTROL = "private, max-age=86400"


@router.get("/connectors/{connector_id}/icon", dependencies=[RequireScope("read")])
async def connector_icon(connector_id: str, store: StoreD, role: OrgRole) -> Response:
    """Icon bytes for a remote connector's host; 404 when nothing usable exists."""
    require_enabled()
    org_id, user_id = caller(store)
    connector = await load_connector(
        store.session, org_id=org_id, user_id=user_id, connector_id=connector_id, admin=is_admin(role)
    )
    origin = icons.icon_origin(connector.url) if connector.transport != "stdio" else None
    if origin is None:
        raise HTTPException(status_code=404, detail="This connector has no icon")
    icon = await icons.fetch_icon(origin)
    if icon is None:
        raise HTTPException(status_code=404, detail="No icon found for this connector")
    return Response(content=icon.content, media_type=icon.content_type, headers={"Cache-Control": _CACHE_CONTROL})
