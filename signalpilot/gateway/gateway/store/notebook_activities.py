"""Notebook activity log persistence: insert and query lifecycle events."""

from __future__ import annotations

import time
import uuid

from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import GatewayNotebookActivity
from gateway.models.notebooks import NotebookActivityInfo

NOTEBOOK_ACTION_VALUES: frozenset[str] = frozenset(
    {"upload", "analyze", "delete", "update", "download", "compare", "export_report"}
)

_MAX_LIMIT = 100


def _row_to_info(row: GatewayNotebookActivity) -> NotebookActivityInfo:
    return NotebookActivityInfo(
        id=row.id,
        notebook_id=row.notebook_id,
        action=row.action,
        details=row.details,
        created_at=row.created_at,
        user_id=row.user_id,
    )


async def log_activity(
    session: AsyncSession,
    *,
    org_id: str,
    user_id: str | None,
    notebook_id: str,
    action: str,
    details: dict | None,
) -> None:
    """Insert one activity row for a notebook lifecycle event."""
    row = GatewayNotebookActivity(
        id=str(uuid.uuid4()),
        org_id=org_id,
        user_id=user_id,
        notebook_id=notebook_id,
        action=action,
        details=details,
        created_at=time.time(),
    )
    session.add(row)
    await session.commit()


async def get_activities(
    session: AsyncSession,
    *,
    org_id: str,
    notebook_id: str,
    limit: int,
    offset: int,
    action: str | None,
) -> list[NotebookActivityInfo]:
    """Return activity rows for a notebook, newest first."""
    limit = min(limit, _MAX_LIMIT)
    offset = max(offset, 0)
    stmt = (
        select(GatewayNotebookActivity)
        .where(
            GatewayNotebookActivity.org_id == org_id,
            GatewayNotebookActivity.notebook_id == notebook_id,
        )
        .order_by(GatewayNotebookActivity.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if action is not None:
        stmt = stmt.where(GatewayNotebookActivity.action == action)
    result = await session.execute(stmt)
    return [_row_to_info(r) for r in result.scalars().all()]


async def count_activities(
    session: AsyncSession,
    *,
    org_id: str,
    notebook_id: str,
    action: str | None,
) -> int:
    """Count activity rows for pagination."""
    stmt = (
        select(sa_func.count())
        .select_from(GatewayNotebookActivity)
        .where(
            GatewayNotebookActivity.org_id == org_id,
            GatewayNotebookActivity.notebook_id == notebook_id,
        )
    )
    if action is not None:
        stmt = stmt.where(GatewayNotebookActivity.action == action)
    result = await session.execute(stmt)
    return result.scalar_one()
