"""Audit-log persistence: append and read audit entries, scoped by org_id."""

from __future__ import annotations

import uuid

from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import GatewayAuditLog
from gateway.engine import redact_sql_literals
from gateway.models import AuditEntry


async def append_audit(
    session: AsyncSession,
    *,
    org_id: str,
    user_id: str | None,
    entry: AuditEntry,
) -> None:
    redacted_sql = redact_sql_literals(entry.sql) if entry.sql else None
    session.add(
        GatewayAuditLog(
            id=entry.id or str(uuid.uuid4()),
            org_id=org_id,
            user_id=user_id,
            timestamp=entry.timestamp,
            event_type=entry.event_type,
            connection_name=entry.connection_name,
            sandbox_id=entry.sandbox_id,
            sql_text=redacted_sql,
            tables=entry.tables,
            rows_returned=entry.rows_returned,
            cost_usd=entry.cost_usd,
            blocked=entry.blocked or False,
            block_reason=entry.block_reason,
            duration_ms=entry.duration_ms,
            agent_id=entry.agent_id,
            parent_id=entry.parent_id,
            metadata_json=entry.metadata,
            client_ip=entry.client_ip,
            user_agent=entry.user_agent,
        )
    )
    await session.commit()


async def read_audit(
    session: AsyncSession,
    *,
    org_id: str,
    limit: int = 200,
    offset: int = 0,
    connection_name: str | None = None,
    event_type: str | None = None,
    return_total: bool = False,
) -> list[AuditEntry] | tuple[list[AuditEntry], int]:
    base = select(GatewayAuditLog).where(GatewayAuditLog.org_id == org_id)
    if connection_name:
        base = base.where(GatewayAuditLog.connection_name == connection_name)
    if event_type:
        base = base.where(GatewayAuditLog.event_type == event_type)

    total = 0
    if return_total:
        count_q = select(sa_func.count()).select_from(base.subquery())
        total = (await session.execute(count_q)).scalar() or 0

    q = base.order_by(GatewayAuditLog.timestamp.desc()).offset(offset).limit(limit)
    result = await session.execute(q)
    entries = []
    for row in result.scalars():
        entries.append(
            AuditEntry(
                id=row.id,
                timestamp=row.timestamp,
                event_type=row.event_type,
                connection_name=row.connection_name,
                sandbox_id=row.sandbox_id,
                sql=row.sql_text,
                tables=row.tables or [],
                rows_returned=row.rows_returned,
                cost_usd=row.cost_usd,
                blocked=row.blocked,
                block_reason=row.block_reason,
                duration_ms=row.duration_ms,
                agent_id=row.agent_id,
                parent_id=getattr(row, "parent_id", None),
                metadata=row.metadata_json or {},
                client_ip=getattr(row, "client_ip", None),
                user_agent=getattr(row, "user_agent", None),
            )
        )
    if return_total:
        return entries, total
    return entries
