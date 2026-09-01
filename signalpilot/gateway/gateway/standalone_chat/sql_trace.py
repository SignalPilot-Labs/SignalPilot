"""Read-side SQL trace projection for one conversation.

No new table. Each row projects one governed query execution joined to its
query plan for the normalized SQL text. The route serializes datetimes.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import GatewayGovernedQueryExecution, GatewayQueryPlan


async def list_sql_trace(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    conversation_id: str,
) -> list[dict]:
    """Return the conversation's governed executions in creation order. One query."""
    rows = (
        await db.execute(
            select(GatewayGovernedQueryExecution, GatewayQueryPlan.normalized_sql)
            .outerjoin(
                GatewayQueryPlan,
                GatewayQueryPlan.id == GatewayGovernedQueryExecution.plan_id,
            )
            .where(
                GatewayGovernedQueryExecution.org_id == org_id,
                GatewayGovernedQueryExecution.user_id == user_id,
                GatewayGovernedQueryExecution.conversation_id == conversation_id,
            )
            .order_by(GatewayGovernedQueryExecution.created_at.asc())
        )
    ).all()
    return [
        {
            "execution_id": execution.id,
            "run_id": execution.run_id,
            "connection_name": execution.connection_name,
            "sql": normalized_sql,
            "sql_hash": execution.sql_hash,
            "status": execution.status,
            "query_path": execution.query_path,
            "estimated_cost_usd": execution.estimated_cost_usd,
            "actual_cost_usd": execution.actual_cost_usd,
            "actual_scan_bytes": execution.actual_scan_bytes,
            "execution_ms": execution.execution_ms,
            "row_count": execution.row_count,
            "completeness": execution.completeness,
            "public_error_code": execution.public_error_code,
            "created_at": execution.created_at,
            "started_at": execution.started_at,
            "terminal_at": execution.terminal_at,
        }
        for execution, normalized_sql in rows
    ]
