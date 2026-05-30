"""API key management endpoints + plan usage."""

import logging
import time
import uuid

from fastapi import APIRouter, HTTPException, Request, Response

from ..auth import OrgAdmin, OrgID, UserID
from ..models import ApiKeyCreate, ApiKeyCreatedResponse, ApiKeyResponse, AuditEntry
from ..security.scope_guard import RequireScope
from .deps import StoreD

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


def _extract_request_meta(request: Request) -> tuple[str | None, str | None]:
    """Extract client_ip and user_agent from the incoming HTTP request."""
    client_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
        request.client.host if request.client else None
    )
    user_agent = request.headers.get("user-agent")
    return client_ip, user_agent


@router.get("/keys", dependencies=[RequireScope("admin")])
async def list_keys(store: StoreD) -> list[ApiKeyResponse]:
    records = await store.list_api_keys()
    return [ApiKeyResponse(**r.model_dump(exclude={"key_hash", "user_id"})) for r in records]


@router.post("/keys", dependencies=[RequireScope("admin")])
async def create_key(body: ApiKeyCreate, store: StoreD, _role: OrgAdmin, request: Request) -> ApiKeyCreatedResponse:
    # Enforce API key limit based on org's plan tier
    from ..governance.plan_limits import check_api_key_limit, get_org_limits

    plan = await get_org_limits(store.org_id)
    existing_keys = await store.list_api_keys()
    check_api_key_limit(len(existing_keys), plan)

    record, raw_key = await store.create_api_key(body.name, body.scopes, expires_at=body.expires_at)

    client_ip, user_agent = _extract_request_meta(request)
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

    client_ip, user_agent = _extract_request_meta(request)
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
async def get_plan_usage(_user: UserID, org_id: OrgID, store: StoreD):
    """Return current plan tier, limits, and usage for the org."""
    from ..governance.plan_limits import daily_query_counter, get_org_limits

    plan = await get_org_limits(org_id)
    connections = await store.list_connections()
    keys = await store.list_api_keys()
    queries_today = daily_query_counter.get_count(org_id)

    return {
        "tier": plan.tier,
        "limits": {
            "connections": plan.connections or "unlimited",
            "users": plan.users or "unlimited",
            "api_keys": plan.api_keys or "unlimited",
            "queries_per_day": plan.queries_per_day or "unlimited",
            "audit_retention_days": plan.audit_retention_days or "unlimited",
        },
        "usage": {
            "connections": len(connections),
            "api_keys": len(keys),
            "queries_today": queries_today,
        },
        "features": {
            "pii_redaction": plan.pii_redaction,
            "byok": plan.byok,
            "sso": plan.sso,
            "budget_controls": plan.budget_controls,
            "audit_export": plan.audit_export,
        },
    }
