"""Usage endpoints for the admin "usage by member" and personal "my usage" pages.

- GET /api/usage/org?days=30 : admin scope + org admin. Aggregates chat runs
  and warehouse queries per member for the org. Access is audit-logged.
- GET /api/usage/me?days=30  : read scope. The caller's own usage only.

``days`` is clamped to 1..90 rather than rejected so the pages can pass any
preset without a validation round-trip.
"""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import APIRouter, HTTPException, Query, Request

from ..auth import OrgAdmin
from ..common.ip import request_meta
from ..models import AuditEntry
from ..models.usage import MyUsageResponse, OrgUsageResponse
from ..runtime.mode import is_cloud_mode
from ..security.scope_guard import RequireScope
from ..store import usage as usage_store
from .deps import StoreD

logger = logging.getLogger(__name__)

router = APIRouter(tags=["usage"])


@router.get("/api/usage/org", response_model=OrgUsageResponse, dependencies=[RequireScope("admin")])
async def get_org_usage(request: Request, store: StoreD, _role: OrgAdmin, days: int = Query(30)) -> OrgUsageResponse:
    """Per-member usage for the whole org (org admins only)."""
    days = usage_store.clamp_days(days)
    org_id = store.org_id or "local"
    result = await usage_store.org_usage(store.session, org_id, days)

    client_ip, user_agent = request_meta(request)
    try:
        await store.append_audit(
            AuditEntry(
                id=str(uuid.uuid4()),
                timestamp=time.time(),
                event_type="usage_org_view",
                metadata={"days": days, "members": len(result.members)},
                client_ip=client_ip,
                user_agent=user_agent,
            )
        )
    except Exception:
        logger.warning("Failed to append audit log for usage_org_view org=%s", org_id)
    return result


@router.get("/api/usage/me", response_model=MyUsageResponse, dependencies=[RequireScope("read")])
async def get_my_usage(store: StoreD, days: int = Query(30)) -> MyUsageResponse:
    """The caller's own usage. Needs a user identity in cloud mode."""
    if is_cloud_mode() and not store.user_id:
        raise HTTPException(status_code=403, detail="User identity required")
    days = usage_store.clamp_days(days)
    org_id = store.org_id or "local"
    user_id = store.user_id or "local"
    return await usage_store.user_usage(store.session, org_id, user_id, days)
