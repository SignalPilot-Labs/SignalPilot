"""Atomic live-request allowance for personal demo workspaces."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import GatewayChatConversation, GatewayChatRun, GatewayConnection
from gateway.standalone_chat.demo_policy import DEMO_REQUEST_LIMIT, DEMO_TAG


class DemoRequestLimitError(HTTPException):
    def __init__(self, *, limit: int, used: int) -> None:
        super().__init__(
            status_code=429,
            detail={"code": "demo_request_limit", "limit": limit, "used": used},
        )


async def demo_request_usage(
    db: AsyncSession, *, org_id: str, lock: bool = False
) -> tuple[int, int] | None:
    """Return the demo allowance and usage, optionally locking its marker row."""
    statement = select(GatewayConnection).where(GatewayConnection.org_id == org_id)
    if lock:
        statement = statement.with_for_update()
    connections = list(
        (await db.execute(statement)).scalars()
    )
    demo_connection = next((row for row in connections if DEMO_TAG in (row.tags or [])), None)
    if demo_connection is None:
        return None

    used = int(
        await db.scalar(
            select(func.count(GatewayChatRun.id))
            .join(GatewayChatConversation, GatewayChatConversation.id == GatewayChatRun.conversation_id)
            .where(
                GatewayChatRun.org_id == org_id,
                GatewayChatConversation.origin != "demo_replay",
            )
        )
        or 0
    )
    return DEMO_REQUEST_LIMIT, used


async def enforce_demo_request_limit(db: AsyncSession, *, org_id: str) -> None:
    """Lock the demo marker before counting so concurrent tabs cannot admit request six."""
    usage = await demo_request_usage(db, org_id=org_id, lock=True)
    if usage is None:
        return
    limit, used = usage
    if used >= limit:
        raise DemoRequestLimitError(limit=limit, used=used)
