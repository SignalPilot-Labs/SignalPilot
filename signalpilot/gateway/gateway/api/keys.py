"""API key management endpoints + plan usage."""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import APIRouter, HTTPException, Request, Response

from ..auth import OrgAdmin, OrgID, UserID
from ..common.ip import request_meta
from ..models import ApiKeyCreate, ApiKeyCreatedResponse, ApiKeyResponse, AuditEntry
from ..security.scope_guard import RequireScope
from .deps import StoreD

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


@router.get("/keys", dependencies=[RequireScope("admin")])
async def list_keys(store: StoreD) -> list[ApiKeyResponse]:
    records = await store.list_api_keys()
    return [ApiKeyResponse(**r.model_dump(exclude={"key_hash", "user_id"})) for r in records]


@router.post("/keys", dependencies=[RequireScope("admin")])
async def create_key(body: ApiKeyCreate, store: StoreD, _role: OrgAdmin, request: Request) -> ApiKeyCreatedResponse:
    # Abuse ceiling on API keys, read from the org's entitlement.
    from ..governance.org_limits import check_api_key_limit, get_org_limits

    plan = await get_org_limits(store.org_id)
    existing_keys = await store.list_api_keys()
    check_api_key_limit(len(existing_keys), plan)

    record, raw_key = await store.create_api_key(body.name, body.scopes, expires_at=body.expires_at)

    client_ip, user_agent = request_meta(request)
    # Audit-DB failure must not block the successful key creation; best-effort observability.
    try:
        await store.append_audit(
            AuditEntry(
                id=str(uuid.uuid4()),
                timestamp=time.time(),
                event_type="api_key_create",
                metadata={"key_id": record.id, "name": record.name, "scopes": list(record.scopes)},
                client_ip=client_ip,
                user_agent=user_agent,
            )
        )
    except Exception:
        logger.warning("Failed to append audit log for api_key_create key_id=%s", record.id)

    return ApiKeyCreatedResponse(
        **record.model_dump(exclude={"key_hash", "user_id"}),
        raw_key=raw_key,
    )


@router.delete("/keys/{key_id}", dependencies=[RequireScope("admin")])
async def delete_key(key_id: str, store: StoreD, _role: OrgAdmin, request: Request):
    if not await store.delete_api_key(key_id):
        raise HTTPException(status_code=404, detail="API key not found")

    client_ip, user_agent = request_meta(request)
    # Audit-DB failure must not block the successful key deletion; best-effort observability.
    try:
        await store.append_audit(
            AuditEntry(
                id=str(uuid.uuid4()),
                timestamp=time.time(),
                event_type="api_key_delete",
                metadata={"key_id": key_id},
                client_ip=client_ip,
                user_agent=user_agent,
            )
        )
    except Exception:
        logger.warning("Failed to append audit log for api_key_delete key_id=%s", key_id)

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
