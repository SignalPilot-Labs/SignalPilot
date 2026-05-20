"""Notebook session CRUD operations."""

from __future__ import annotations

import time
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import GatewayNotebookSession
from ..models.notebook_sessions import NotebookSessionInfo


async def get_active_session(
    session: AsyncSession, *, org_id: str, user_id: str
) -> NotebookSessionInfo | None:
    q = select(GatewayNotebookSession).where(
        GatewayNotebookSession.org_id == org_id,
        GatewayNotebookSession.user_id == user_id,
        GatewayNotebookSession.status.in_(["creating", "running"]),
    )
    row = (await session.execute(q)).scalar_one_or_none()
    return _to_info(row) if row else None


async def create_session(
    session: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    project_id: str | None,
    branch: str,
    pod_name: str,
) -> NotebookSessionInfo:
    import secrets

    now = time.time()
    token = secrets.token_urlsafe(24)
    row = GatewayNotebookSession(
        id=str(uuid.uuid4()),
        org_id=org_id,
        user_id=user_id,
        project_id=project_id,
        branch=branch,
        pod_name=pod_name,
        pod_ip=None,
        access_token=token,
        status="creating",
        last_ping=now,
        created_at=now,
    )
    session.add(row)
    await session.commit()
    return _to_info(row)


async def update_session_status(
    session: AsyncSession, *, session_id: str, status: str, pod_ip: str | None = None
) -> None:
    values: dict = {"status": status}
    if pod_ip is not None:
        values["pod_ip"] = pod_ip
    await session.execute(
        update(GatewayNotebookSession)
        .where(GatewayNotebookSession.id == session_id)
        .values(**values)
    )
    await session.commit()


async def ping_session(
    session: AsyncSession, *, org_id: str, user_id: str
) -> NotebookSessionInfo | None:
    q = select(GatewayNotebookSession).where(
        GatewayNotebookSession.org_id == org_id,
        GatewayNotebookSession.user_id == user_id,
        GatewayNotebookSession.status == "running",
    )
    row = (await session.execute(q)).scalar_one_or_none()
    if not row:
        return None
    row.last_ping = time.time()
    await session.commit()
    return _to_info(row)


async def mark_stopped(session: AsyncSession, *, session_id: str) -> None:
    await session.execute(
        update(GatewayNotebookSession)
        .where(GatewayNotebookSession.id == session_id)
        .values(status="stopped")
    )
    await session.commit()


async def delete_stopped(session: AsyncSession, *, org_id: str, user_id: str) -> None:
    """Remove stopped sessions so the user can create a new one."""
    q = select(GatewayNotebookSession).where(
        GatewayNotebookSession.org_id == org_id,
        GatewayNotebookSession.user_id == user_id,
        GatewayNotebookSession.status.in_(["stopped", "error"]),
    )
    rows = (await session.execute(q)).scalars().all()
    for row in rows:
        await session.delete(row)
    if rows:
        await session.commit()


async def list_stale_sessions(
    session: AsyncSession, *, max_idle_seconds: int = 7200
) -> list[NotebookSessionInfo]:
    cutoff = time.time() - max_idle_seconds
    q = select(GatewayNotebookSession).where(
        GatewayNotebookSession.status == "running",
        GatewayNotebookSession.last_ping < cutoff,
    )
    rows = (await session.execute(q)).scalars().all()
    return [_to_info(r) for r in rows]


def _to_info(row: GatewayNotebookSession) -> NotebookSessionInfo:
    notebook_url = None
    if row.status == "running" and row.pod_ip and row.access_token:
        ip = row.pod_ip
        notebook_url = f"http://{ip}?access_token={row.access_token}"
    return NotebookSessionInfo(
        id=row.id,
        org_id=row.org_id,
        user_id=row.user_id,
        project_id=row.project_id,
        branch=row.branch,
        pod_name=row.pod_name,
        pod_ip=row.pod_ip,
        access_token=row.access_token,
        status=row.status,
        notebook_url=notebook_url,
        last_ping=row.last_ping,
        created_at=row.created_at,
    )
