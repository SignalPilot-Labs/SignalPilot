"""Org policy routes (R4)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from gateway.auth import OrgAdmin
from gateway.mcp_connectors.upstream import pool as upstream_pool
from gateway.security.scope_guard import RequireScope
from gateway.store.mcp import policy as policy_store

from ..deps import StoreD
from .common import caller, require_enabled
from .schemas import OrgPolicyUpdate

router = APIRouter()


@router.get("/policy", dependencies=[RequireScope("read")])
async def get_policy(store: StoreD) -> dict[str, Any]:
    require_enabled()
    org_id, _ = caller(store)
    return policy_store.policy_to_dict(await policy_store.get_policy(store.session, org_id=org_id))


@router.put("/policy", dependencies=[RequireScope("write")])
async def put_policy(body: OrgPolicyUpdate, store: StoreD, _role: OrgAdmin) -> dict[str, Any]:
    require_enabled()
    org_id, _ = caller(store)
    row = await policy_store.upsert_policy(
        store.session, org_id=org_id, allow_personal=body.allow_personal, allowed_hosts=body.allowed_hosts
    )
    # Personal connectors may have lost access: drop their live upstream sessions.
    await upstream_pool.close_all()
    return policy_store.policy_to_dict(row)
