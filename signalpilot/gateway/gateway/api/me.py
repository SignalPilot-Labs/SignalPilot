"""``GET /api/me``: who the caller is and what they may do.

Read by pages outside chat so they can hide or disable admin controls
without a bootstrap round-trip. Read scope, no plan gate: a free org's
member still needs to know their role.
"""

from __future__ import annotations

from fastapi import APIRouter

from ..auth import OrgID, OrgRole, UserID
from ..auth.permissions import normalize_role, permissions_for
from ..auth.user import is_org_admin_role
from ..billing.entitlements import get_entitlement
from ..security.scope_guard import RequireScope
from .deps import deployment_capabilities

router = APIRouter(prefix="/api")


@router.get("/me", dependencies=[RequireScope("read")])
async def whoami(user_id: UserID, org_id: OrgID, role: OrgRole) -> dict:
    entitlement = await get_entitlement(org_id)
    return {
        "user_id": user_id,
        "org_id": org_id,
        "role": normalize_role(role),
        "is_admin": is_org_admin_role(role),
        "permissions": sorted(permissions_for(role)),
        "entitlement": entitlement.to_dict(),
        "capabilities": deployment_capabilities(),
    }
