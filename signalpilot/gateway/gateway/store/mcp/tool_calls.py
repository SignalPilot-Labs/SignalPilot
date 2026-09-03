"""Audit rows for proxied tool calls (R5)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import GatewayMcpConnector, GatewayMcpToolCall
from gateway.store.mcp._common import iso, utcnow

_MAX_ERROR = 500


async def record_call(
    session: AsyncSession,
    *,
    org_id: str,
    connector_id: str,
    user_id: str,
    tool: str,
    outcome: str,
    duration_ms: int,
    run_id: str | None,
    conversation_id: str | None,
    error: str | None,
) -> GatewayMcpToolCall:
    row = GatewayMcpToolCall(
        org_id=org_id,
        connector_id=connector_id,
        user_id=user_id,
        run_id=run_id,
        conversation_id=conversation_id,
        tool=tool[:128],
        outcome=outcome,
        duration_ms=max(0, int(duration_ms)),
        error=(error or None) and str(error)[:_MAX_ERROR],
        called_at=utcnow(),
    )
    session.add(row)
    await session.commit()
    return row


async def list_calls(
    session: AsyncSession,
    *,
    org_id: str,
    connector_id: str | None = None,
    limit: int = 50,
) -> list[dict]:
    stmt = (
        select(GatewayMcpToolCall, GatewayMcpConnector.name)
        .join(GatewayMcpConnector, GatewayMcpConnector.id == GatewayMcpToolCall.connector_id, isouter=True)
        .where(GatewayMcpToolCall.org_id == org_id)
        .order_by(GatewayMcpToolCall.called_at.desc())
        .limit(max(1, min(limit, 500)))
    )
    if connector_id is not None:
        stmt = stmt.where(GatewayMcpToolCall.connector_id == connector_id)
    rows = (await session.execute(stmt)).all()
    return [call_to_dict(row, name) for row, name in rows]


def user_label_for(user_id: str | None) -> str | None:
    """Display name/email for ``user_id`` when the gateway can resolve one.

    The gateway keeps no user directory: identities are Clerk user ids (cloud)
    or the fixed ``local`` user, and no table stores names or emails. Until a
    directory exists this is always None; the contract field is reserved so
    the web app renders it once it is populated.
    """
    return None


def call_to_dict(row: GatewayMcpToolCall, connector_name: str | None) -> dict:
    return {
        "id": row.id,
        "connector_id": row.connector_id,
        "connector_name": connector_name or "",
        "user_id": row.user_id,
        "user_label": user_label_for(row.user_id),
        "run_id": row.run_id,
        "conversation_id": row.conversation_id,
        "tool": row.tool,
        "outcome": row.outcome,
        "duration_ms": int(row.duration_ms or 0),
        "error": row.error,
        "called_at": iso(row.called_at),
    }
