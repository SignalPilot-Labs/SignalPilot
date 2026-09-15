"""Creator-or-admin access to saved chat reports.

Saved reports, their versions and their share grants are user-owned: the
store filters every mutation by ``owner_user_id``. These helpers put the
same rule in front of the route, in the shape the dashboards use
(``can_edit``: the creator, or an org admin):

* the report (or the version's report) is not in the caller's org: 404;
* it belongs to someone else and the caller is not an admin: 403
  ``You can only change resources you created``;
* otherwise the helper returns the owner's user id, which is the identity
  the store call runs as. An admin therefore acts on the owner's behalf,
  so ``version.owner_user_id == report.owner_user_id`` stays true and the
  owner keeps seeing the versions and share links the admin made.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select

from gateway.auth.permissions import OWNERSHIP_DENIAL
from gateway.auth.user import is_org_admin_role
from gateway.db.models import GatewaySavedReport, GatewaySavedReportVersion


def _actor(owner_user_id: str, caller_user_id: str, role: str) -> str:
    if owner_user_id == caller_user_id or is_org_admin_role(role):
        return owner_user_id
    raise HTTPException(status_code=403, detail=OWNERSHIP_DENIAL)


async def report_actor(store, role: str, *, report_id: str) -> str:
    """The user id to act as on ``report_id``; 404 unknown, 403 not yours."""
    owner = (
        await store.session.execute(
            select(GatewaySavedReport.owner_user_id).where(
                GatewaySavedReport.id == report_id,
                GatewaySavedReport.org_id == store._require_org_id(),
            )
        )
    ).scalar_one_or_none()
    if owner is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return _actor(owner, store.user_id or "local", role)


async def version_actor(store, role: str, *, version_id: str) -> str:
    """The user id to act as on ``version_id``'s report; 404 unknown, 403 not yours."""
    owner = (
        await store.session.execute(
            select(GatewaySavedReport.owner_user_id)
            .join(GatewaySavedReport, GatewaySavedReport.id == GatewaySavedReportVersion.report_id)
            .where(
                GatewaySavedReportVersion.id == version_id,
                GatewaySavedReport.org_id == store._require_org_id(),
            )
        )
    ).scalar_one_or_none()
    if owner is None:
        raise HTTPException(status_code=404, detail="Report version not found")
    return _actor(owner, store.user_id or "local", role)
