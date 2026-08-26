"""Agent run CRUD operations."""

from __future__ import annotations

import time
import uuid

from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import GatewayAgentRun
from ..models.workspace import AgentRunInfo


async def create_run(
    session: AsyncSession,
    *,
    org_id: str,
    user_id: str | None,
    project_id: str | None = None,
    conversation_id: str | None = None,
    agent_type: str,
    input_json: dict | None = None,
    metadata_json: dict | None = None,
) -> AgentRunInfo:
    now = time.time()
    row = GatewayAgentRun(
        id=str(uuid.uuid4()),
        org_id=org_id,
        user_id=user_id,
        project_id=project_id,
        conversation_id=conversation_id,
        agent_type=agent_type,
        status="pending",
        input_json=input_json,
        metadata_json=metadata_json,
        started_at=now,
        created_at=now,
    )
    session.add(row)
    await session.commit()
    return _to_info(row)


async def list_runs(
    session: AsyncSession,
    *,
    org_id: str,
    project_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AgentRunInfo], int]:
    base = select(GatewayAgentRun).where(GatewayAgentRun.org_id == org_id)
    if project_id:
        base = base.where(GatewayAgentRun.project_id == project_id)
    if status:
        base = base.where(GatewayAgentRun.status == status)

    total = (await session.execute(select(sa_func.count()).select_from(base.subquery()))).scalar() or 0
    q = base.order_by(GatewayAgentRun.created_at.desc()).offset(offset).limit(limit)
    result = await session.execute(q)
    return [_to_info(r) for r in result.scalars()], total


async def get_run(
    session: AsyncSession, *, org_id: str, run_id: str
) -> AgentRunInfo | None:
    q = select(GatewayAgentRun).where(
        GatewayAgentRun.org_id == org_id,
        GatewayAgentRun.id == run_id,
    )
    row = (await session.execute(q)).scalar_one_or_none()
    return _to_info(row) if row else None


async def update_run(
    session: AsyncSession,
    *,
    org_id: str,
    run_id: str,
    updates: dict,
) -> AgentRunInfo | None:
    q = select(GatewayAgentRun).where(
        GatewayAgentRun.org_id == org_id,
        GatewayAgentRun.id == run_id,
    )
    row = (await session.execute(q)).scalar_one_or_none()
    if not row:
        return None
    for k, v in updates.items():
        if v is not None and hasattr(row, k):
            setattr(row, k, v)
    if updates.get("status") in ("completed", "failed") and row.started_at and not row.duration_ms:
        row.duration_ms = (time.time() - row.started_at) * 1000
    if updates.get("status") in ("completed", "failed") and not row.completed_at:
        row.completed_at = time.time()
    await session.commit()
    return _to_info(row)


def _to_info(row: GatewayAgentRun) -> AgentRunInfo:
    return AgentRunInfo(
        id=row.id,
        org_id=row.org_id,
        user_id=row.user_id,
        project_id=row.project_id,
        conversation_id=row.conversation_id,
        agent_type=row.agent_type,
        status=row.status,
        input_json=row.input_json,
        output_json=row.output_json,
        error_message=row.error_message,
        started_at=row.started_at,
        completed_at=row.completed_at,
        duration_ms=row.duration_ms,
        total_tokens=row.total_tokens,
        cost_usd=row.cost_usd,
        metadata_json=row.metadata_json,
        created_at=row.created_at,
    )
