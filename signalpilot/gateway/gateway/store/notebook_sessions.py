"""Notebook session CRUD operations."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import GatewayNotebookSession
from ..models.notebook_sessions import NotebookSessionInfo


@dataclass(frozen=True)
class NotebookSessionInternal:
    """Internal-only session view that includes the real access_token.

    NEVER serialize this to JSON or include in any API response.
    Used only by the gateway proxy for cookie comparison and upstream routing.
    Two distinct read paths off the same DB row:
    - _to_info() -> NotebookSessionInfo  (FE-facing, access_token=None)
    - get_session_internal() -> NotebookSessionInternal  (proxy-only, real token)
    """

    session_id: str
    org_id: str
    user_id: str
    status: str
    pod_ip_internal: str | None
    access_token: str | None


async def get_session_by_id(
    session: AsyncSession, *, session_id: str, org_id: str
) -> NotebookSessionInfo | None:
    """Look up a session by id, scoped to org_id.

    Returns None if the session does not exist OR belongs to a different org
    (404-semantics: no existence oracle for cross-org callers).
    """
    q = select(GatewayNotebookSession).where(
        GatewayNotebookSession.id == session_id,
        GatewayNotebookSession.org_id == org_id,
    )
    row = (await session.execute(q)).scalar_one_or_none()
    return _to_info(row) if row else None


async def get_session_internal(
    session: AsyncSession, *, session_id: str, org_id: str
) -> NotebookSessionInternal | None:
    """Return the internal session view including the real access_token.

    Used ONLY by the gateway proxy (resolve_proxy_session) to compare the
    inbound cookie and determine the upstream address. Never expose to the FE.
    """
    q = select(GatewayNotebookSession).where(
        GatewayNotebookSession.id == session_id,
        GatewayNotebookSession.org_id == org_id,
    )
    row = (await session.execute(q)).scalar_one_or_none()
    if row is None:
        return None
    return NotebookSessionInternal(
        session_id=row.id,
        org_id=row.org_id,
        user_id=row.user_id,
        status=row.status,
        pod_ip_internal=row.pod_ip_internal,
        access_token=row.access_token,
    )


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
        pod_ip_internal=None,
        access_token=token,
        status="creating",
        last_ping=now,
        created_at=now,
    )
    session.add(row)
    await session.commit()
    return _to_info(row)


async def update_session_status(
    session: AsyncSession,
    *,
    session_id: str,
    status: str,
    pod_ip: str | None = None,
    pod_ip_internal: str | None = None,
) -> None:
    values: dict = {"status": status}
    if pod_ip is not None:
        values["pod_ip"] = pod_ip
    if pod_ip_internal is not None:
        values["pod_ip_internal"] = pod_ip_internal
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


async def ping_session_by_id(
    session: AsyncSession, *, session_id: str, org_id: str
) -> NotebookSessionInfo | None:
    """Ping a specific session by id, scoped to org_id."""
    q = select(GatewayNotebookSession).where(
        GatewayNotebookSession.id == session_id,
        GatewayNotebookSession.org_id == org_id,
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
    """FE-facing view of a session row.

    access_token is always None here — the secret never leaves the server.
    notebook_url is the path-only proxy init URL (no token, no host, no port).
    Two distinct read paths off the same row:
    - _to_info()            -> NotebookSessionInfo  (FE-facing, access_token=None)
    - get_session_internal() -> NotebookSessionInternal  (proxy-only, real token)
    """
    notebook_url = None
    if row.status == "running" and row.pod_ip:
        notebook_url = f"/notebook/{row.id}/_init"
    return NotebookSessionInfo(
        id=row.id,
        org_id=row.org_id,
        user_id=row.user_id,
        project_id=row.project_id,
        branch=row.branch,
        pod_name=row.pod_name,
        pod_ip=row.pod_ip,
        # access_token is intentionally None in all FE-facing responses.
        # The real token is only accessible via get_session_internal().
        access_token=None,
        status=row.status,
        notebook_url=notebook_url,
        last_ping=row.last_ping,
        created_at=row.created_at,
    )
