"""Single-writer lease per (project, branch).

The lease makes the one-live-compute-session-per-branch invariant explicit and
inspectable. Sync batches renew it; read-only (frozen) sessions never take
one. TTL-expired leases are reclaimable by any new holder.
"""

from __future__ import annotations

import time

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import GatewayWorkspaceLease

LEASE_TTL_SECONDS = 90.0


class LeaseHeld(RuntimeError):
    """Another live holder owns the (project, branch) lease."""

    def __init__(self, holder: str, expires_at: float) -> None:
        super().__init__(f"Lease held by {holder} until {expires_at:.0f}")
        self.holder = holder
        self.expires_at = expires_at


async def acquire_lease(
    db: AsyncSession,
    *,
    org_id: str,
    project_id: str,
    branch: str,
    holder: str,
    session_id: str | None = None,
    ttl_seconds: float = LEASE_TTL_SECONDS,
) -> float:
    """Acquire (or re-acquire/renew as the same holder) the branch lease.

    Returns the new expiry. Raises LeaseHeld when a different holder's lease
    is still live.
    """
    now = time.time()
    expires = now + ttl_seconds
    row = (
        await db.execute(
            select(GatewayWorkspaceLease).where(
                GatewayWorkspaceLease.project_id == project_id,
                GatewayWorkspaceLease.branch == branch,
            )
        )
    ).scalars().first()

    if row is None:
        db.add(
            GatewayWorkspaceLease(
                org_id=org_id,
                project_id=project_id,
                branch=branch,
                holder=holder,
                session_id=session_id,
                expires_at=expires,
            )
        )
        try:
            await db.commit()
        except IntegrityError:
            # Lost the insert race — recurse once onto the update path.
            await db.rollback()
            return await acquire_lease(
                db,
                org_id=org_id,
                project_id=project_id,
                branch=branch,
                holder=holder,
                session_id=session_id,
                ttl_seconds=ttl_seconds,
            )
        return expires

    if row.holder != holder and row.expires_at > now:
        raise LeaseHeld(row.holder, row.expires_at)

    row.holder = holder
    row.session_id = session_id
    row.expires_at = expires
    await db.commit()
    return expires


async def renew_lease(
    db: AsyncSession,
    *,
    org_id: str,
    project_id: str,
    branch: str,
    holder: str,
    ttl_seconds: float = LEASE_TTL_SECONDS,
) -> float:
    """Renew as the current holder. Same semantics as acquire (an expired own
    lease is simply re-taken)."""
    return await acquire_lease(
        db,
        org_id=org_id,
        project_id=project_id,
        branch=branch,
        holder=holder,
        ttl_seconds=ttl_seconds,
    )


async def release_lease(
    db: AsyncSession, *, project_id: str, branch: str, holder: str
) -> bool:
    result = await db.execute(
        sa_delete(GatewayWorkspaceLease).where(
            GatewayWorkspaceLease.project_id == project_id,
            GatewayWorkspaceLease.branch == branch,
            GatewayWorkspaceLease.holder == holder,
        )
    )
    await db.commit()
    return bool(result.rowcount)
