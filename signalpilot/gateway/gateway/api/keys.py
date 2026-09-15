"""API key management endpoints + plan usage.

Keys are user-owned. A member mints personal keys limited to the read, query
and execute scopes and sees and revokes only their own; an admin mints any
scope and sees every key in the org. An API-key principal may mint only
within its own scopes, and a sandbox or MCP-agent token may not mint at all.
"""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import APIRouter, HTTPException, Request, Response

from ..auth import OrgID, OrgRole, UserID
from ..auth.permissions import ADMIN_ROLE_REQUIRED, OWNERSHIP_DENIAL
from ..auth.user import is_org_admin_role
from ..common.ip import request_meta
from ..models import ApiKeyCreate, ApiKeyCreatedResponse, ApiKeyResponse, AuditEntry
from ..security.scope_guard import RequireScope
from .deps import StoreD

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# The scopes a member may put on a personal key (brief, decision 1).
MEMBER_KEY_SCOPES: frozenset[str] = frozenset({"read", "query", "execute"})


def _require_minting_principal(request: Request) -> dict:
    """Only a browser user or a stored API key may mint or revoke keys.

    A notebook-session or MCP-agent token acts for a user inside one run; it
    must not be able to leave behind a durable credential.
    """
    auth = getattr(request.state, "auth", None) or {}
    if auth.get("auth_method") in {"notebook_session", "mcp_agent"}:
        raise HTTPException(status_code=403, detail="An interactive user or API key is required")
    return auth


def _check_member_scopes(requested: list[str], auth: dict) -> None:
    """A member's key stays inside MEMBER_KEY_SCOPES and inside the caller's own scopes."""
    if set(requested) - MEMBER_KEY_SCOPES:
        raise HTTPException(status_code=403, detail=ADMIN_ROLE_REQUIRED)
    if auth.get("auth_method") == "api_key" and set(requested) - set(auth.get("scopes") or []):
        raise HTTPException(status_code=403, detail="Insufficient scope")


async def _audit(store: StoreD, request: Request, event_type: str, metadata: dict) -> None:
    client_ip, user_agent = request_meta(request)
    # Audit-DB failure must not block the key operation; best-effort observability.
    try:
        await store.append_audit(
            AuditEntry(
                id=str(uuid.uuid4()),
                timestamp=time.time(),
                event_type=event_type,
                metadata=metadata,
                client_ip=client_ip,
                user_agent=user_agent,
            )
        )
    except Exception:
        logger.warning("Failed to append audit log for %s key_id=%s", event_type, metadata.get("key_id"))


@router.get("/keys", dependencies=[RequireScope("read")])
async def list_keys(store: StoreD, role: OrgRole) -> list[ApiKeyResponse]:
    """Admins see every key in the org; members see the keys they minted."""
    if is_org_admin_role(role):
        records = await store.list_api_keys()
    else:
        records = await store.list_api_keys(user_id=store.user_id or "local")
    return [ApiKeyResponse(**r.model_dump(exclude={"key_hash", "user_id"})) for r in records]


@router.post("/keys", dependencies=[RequireScope("read")])
async def create_key(body: ApiKeyCreate, store: StoreD, role: OrgRole, request: Request) -> ApiKeyCreatedResponse:
    auth = _require_minting_principal(request)
    if not is_org_admin_role(role):
        _check_member_scopes(body.scopes, auth)

    # Abuse ceiling on API keys, read from the org's entitlement.
    from ..governance.org_limits import check_api_key_limit, get_org_limits

    plan = await get_org_limits(store.org_id)
    existing_keys = await store.list_api_keys()
    check_api_key_limit(len(existing_keys), plan)

    record, raw_key = await store.create_api_key(body.name, body.scopes, expires_at=body.expires_at)
    await _audit(
        store,
        request,
        "api_key_create",
        {"key_id": record.id, "name": record.name, "scopes": list(record.scopes)},
    )
    return ApiKeyCreatedResponse(
        **record.model_dump(exclude={"key_hash", "user_id"}),
        raw_key=raw_key,
    )


@router.delete("/keys/{key_id}", dependencies=[RequireScope("read")])
async def delete_key(key_id: str, store: StoreD, role: OrgRole, request: Request):
    _require_minting_principal(request)
    record = await store.get_api_key(key_id)
    if record is None:
        raise HTTPException(status_code=404, detail="API key not found")
    if not is_org_admin_role(role) and record.user_id != (store.user_id or "local"):
        raise HTTPException(status_code=403, detail=OWNERSHIP_DENIAL)
    if not await store.delete_api_key(key_id):
        raise HTTPException(status_code=404, detail="API key not found")
    await _audit(store, request, "api_key_delete", {"key_id": key_id})
    return Response(status_code=204)


@router.get("/plan", dependencies=[RequireScope("read")])
async def get_plan_usage(_user: UserID, org_id: OrgID, store: StoreD, refresh: bool = False):
    """Return the org's entitlement, its abuse ceilings, and current usage against them.

    Usage of metered units (threads, queries, models, seats, eval runs) is the
    credit ledger's business; this route covers only the hard ceilings.
    ``?refresh=1`` bypasses the entitlement cache.
    """
    from ..billing.entitlements import get_entitlement
    from ..governance.org_limits import limits_for

    entitlement = await get_entitlement(org_id, refresh=refresh)
    limits = limits_for(entitlement)
    connections = await store.list_connections()
    keys = await store.list_api_keys()

    return {
        "tier": entitlement.tier,
        "is_billable": entitlement.is_billable,
        "entitlement": entitlement.to_dict(),
        "limits": {
            "connections": limits.connections or "unlimited",
            "api_keys": limits.api_keys or "unlimited",
            "knowledge_storage_mb": limits.knowledge_storage_mb or "unlimited",
            "knowledge_history_versions": limits.knowledge_history_versions or "unlimited",
        },
        "usage": {
            "connections": len(connections),
            "api_keys": len(keys),
        },
    }
