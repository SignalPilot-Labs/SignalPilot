"""Short-lived OAuth state rows (Notion pattern: tenant context comes from the row)."""

from __future__ import annotations

import secrets
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import GatewayMcpOAuthState
from gateway.store.mcp._common import as_aware_utc, utcnow

STATE_TTL_SECONDS = 600


async def create_state(
    session: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    connector_id: str,
    code_verifier: str,
    redirect_after: str | None,
) -> str:
    state = secrets.token_urlsafe(32)
    session.add(
        GatewayMcpOAuthState(
            id=state,
            org_id=org_id,
            user_id=user_id,
            connector_id=connector_id,
            code_verifier=code_verifier,
            redirect_after=redirect_after,
            created_at=utcnow(),
        )
    )
    await session.commit()
    return state


async def consume_state(session: AsyncSession, state: str) -> GatewayMcpOAuthState | None:
    """Return and mark a valid, unused state; None when unknown, used or expired."""
    row = (
        await session.execute(select(GatewayMcpOAuthState).where(GatewayMcpOAuthState.id == state))
    ).scalar_one_or_none()
    if row is None or row.consumed_at is not None:
        return None
    created = as_aware_utc(row.created_at) or utcnow()
    row.consumed_at = utcnow()
    await session.commit()
    if created + timedelta(seconds=STATE_TTL_SECONDS) < utcnow():
        return None
    return row


async def purge_expired(session: AsyncSession) -> int:
    cutoff = utcnow() - timedelta(seconds=STATE_TTL_SECONDS * 2)
    result = await session.execute(delete(GatewayMcpOAuthState).where(GatewayMcpOAuthState.created_at < cutoff))
    await session.commit()
    return int(result.rowcount or 0)
