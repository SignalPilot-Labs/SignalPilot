"""Activity (audit log) routes (R5)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from gateway.auth import OrgAdmin, OrgRole
from gateway.security.scope_guard import RequireScope
from gateway.store.mcp import tool_calls as audit_store

from ..deps import StoreD
from .common import caller, is_admin, load_connector, require_enabled

router = APIRouter()


@router.get("/connectors/{connector_id}/activity", dependencies=[RequireScope("read")])
async def connector_activity(
    connector_id: str,
    store: StoreD,
    role: OrgRole,
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    require_enabled()
    org_id, user_id = caller(store)
    connector = await load_connector(
        store.session, org_id=org_id, user_id=user_id, connector_id=connector_id, admin=is_admin(role)
    )
    calls = await audit_store.list_calls(store.session, org_id=org_id, connector_id=connector.id, limit=limit)
    return {"calls": calls}


@router.get("/activity", dependencies=[RequireScope("read")])
async def org_activity(store: StoreD, _role: OrgAdmin, limit: int = Query(default=200, ge=1, le=500)) -> dict[str, Any]:
    require_enabled()
    org_id, _ = caller(store)
    return {"calls": await audit_store.list_calls(store.session, org_id=org_id, limit=limit)}
