"""Notebook session CRUD operations (Runtime v2)."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import GatewayNotebookSession
from ..models.notebook_sessions import NotebookSessionInfo
from .crypto import _decrypt_with_migration, _encrypt

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = ("creating", "running", "snapshotted")


@dataclass(frozen=True)
class NotebookSessionInternal:
    """Internal-only session view that includes the real access_token.

    Do not serialize this object to JSON or include it in an API response.
    Only the gateway proxy and the lifecycle loop use it — the DB row has two
    read paths:
    - _to_info() -> NotebookSessionInfo  (FE-facing, no credentials)
    - get_session_internal() -> NotebookSessionInternal  (server-only)
    """

    session_id: str
    org_id: str
    user_id: str
    status: str
    backend: str
    runtime_handle: str | None
    upstream_url: str | None
    snapshot_id: str | None
    access_token: str | None
    project_id: str | None = None
    branch: str = "main"
    last_ping: float | None = None
    last_extend_at: float | None = None


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
    session: AsyncSession, *, session_id: str, org_id: str | None = None
) -> NotebookSessionInternal | None:
    q = select(GatewayNotebookSession).where(
        GatewayNotebookSession.id == session_id,
    )
    if org_id is not None:
        q = q.where(GatewayNotebookSession.org_id == org_id)
    row = (await session.execute(q)).scalar_one_or_none()
    if row is None:
        return None
    access_token = await _get_internal_access_token(session, row)
    return _to_internal(row, access_token)


async def get_active_session(
    session: AsyncSession, *, org_id: str, user_id: str
) -> NotebookSessionInfo | None:
    q = select(GatewayNotebookSession).where(
        GatewayNotebookSession.org_id == org_id,
        GatewayNotebookSession.user_id == user_id,
        GatewayNotebookSession.status.in_(ACTIVE_STATUSES),
    )
    row = (await session.execute(q)).scalar_one_or_none()
    return _to_info(row) if row else None


async def list_active_sessions_for_org(
    session: AsyncSession, *, org_id: str
) -> list[NotebookSessionInfo]:
    q = select(GatewayNotebookSession).where(
        GatewayNotebookSession.org_id == org_id,
        GatewayNotebookSession.status.in_(ACTIVE_STATUSES),
    )
    rows = (await session.execute(q)).scalars().all()
    return [_to_info(row) for row in rows]


async def count_running_for_org(session: AsyncSession, *, org_id: str) -> int:
    from sqlalchemy import func

    q = select(func.count()).select_from(GatewayNotebookSession).where(
        GatewayNotebookSession.org_id == org_id,
        GatewayNotebookSession.status.in_(("creating", "running")),
    )
    return int((await session.execute(q)).scalar_one())


async def create_session(
    session: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    project_id: str | None,
    branch: str,
    backend: str,
) -> NotebookSessionInfo:
    import secrets

    now = time.time()
    # The notebook server's own auth token for this session's compute:
    # injected at launch and presented upstream by the proxy. 32 bytes.
    token = secrets.token_urlsafe(32)
    row = GatewayNotebookSession(
        id=str(uuid.uuid4()),
        org_id=org_id,
        user_id=user_id,
        project_id=project_id,
        branch=branch,
        backend=backend,
        access_token_enc=_encrypt(token),
        status="creating",
        last_ping=now,
        created_at=now,
    )
    session.add(row)
    await session.commit()
    return _to_info(row)


async def update_session_runtime(
    session: AsyncSession,
    *,
    session_id: str,
    org_id: str,
    status: str | None = None,
    runtime_handle: str | None = None,
    upstream_url: str | None = None,
    snapshot_id: str | None = None,
    clear_upstream: bool = False,
    last_extend_at: float | None = None,
) -> None:
    values: dict = {}
    if status is not None:
        values["status"] = status
    if runtime_handle is not None:
        values["runtime_handle"] = runtime_handle
    if upstream_url is not None:
        values["upstream_url"] = upstream_url
    if snapshot_id is not None:
        values["snapshot_id"] = snapshot_id
    if clear_upstream:
        values["upstream_url"] = None
    if last_extend_at is not None:
        values["last_extend_at"] = last_extend_at
    if not values:
        return
    stmt = (
        update(GatewayNotebookSession)
        .where(
            GatewayNotebookSession.id == session_id,
            GatewayNotebookSession.org_id == org_id,
        )
        .values(**values)
    )
    await _execute_and_commit_with_closed_connection_retry(session, stmt, "update notebook session runtime")


async def ping_session_by_id(
    session: AsyncSession, *, session_id: str, org_id: str
) -> NotebookSessionInfo | None:
    q = select(GatewayNotebookSession).where(
        GatewayNotebookSession.id == session_id,
        GatewayNotebookSession.org_id == org_id,
        GatewayNotebookSession.status.in_(("running", "snapshotted")),
    )
    row = (await session.execute(q)).scalar_one_or_none()
    if not row:
        return None
    row.last_ping = time.time()
    await session.commit()
    return _to_info(row)


async def mark_stopped(session: AsyncSession, *, session_id: str, org_id: str) -> None:
    stmt = (
        update(GatewayNotebookSession)
        .where(
            GatewayNotebookSession.id == session_id,
            GatewayNotebookSession.org_id == org_id,
        )
        .values(status="stopped")
    )
    await _execute_and_commit_with_closed_connection_retry(session, stmt, "mark notebook session stopped")


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


async def list_running_internal(session: AsyncSession) -> list[NotebookSessionInternal]:
    """Every running session, with handles — the lifecycle loop's read."""
    q = select(GatewayNotebookSession).where(GatewayNotebookSession.status == "running")
    rows = (await session.execute(q)).scalars().all()
    return [_to_internal(row, None) for row in rows]


async def list_stale_sessions(
    session: AsyncSession, *, max_idle_seconds: int = 900, statuses: tuple[str, ...] = ("running",)
) -> list[NotebookSessionInternal]:
    cutoff = time.time() - max_idle_seconds
    q = select(GatewayNotebookSession).where(
        GatewayNotebookSession.status.in_(statuses),
        GatewayNotebookSession.last_ping < cutoff,
    )
    rows = (await session.execute(q)).scalars().all()
    return [_to_internal(row, None) for row in rows]


async def live_runtime_handles(session: AsyncSession) -> set[str]:
    """Handles owned by any non-terminal session — the reaper's keep-set."""
    q = select(GatewayNotebookSession.runtime_handle).where(
        GatewayNotebookSession.status.in_(ACTIVE_STATUSES),
        GatewayNotebookSession.runtime_handle.is_not(None),
    )
    return {handle for handle in (await session.execute(q)).scalars() if handle}


async def _execute_and_commit_with_closed_connection_retry(
    session: AsyncSession,
    statement,
    operation: str,
) -> None:
    try:
        await session.execute(statement)
        await session.commit()
    except (InterfaceError, OperationalError, DBAPIError) as exc:
        if not _looks_like_closed_connection(exc):
            raise
        logger.warning("Stale DB connection during %s; retrying once", operation, exc_info=True)
        try:
            await session.rollback()
        except Exception:
            logger.debug("Rollback after stale DB connection failed", exc_info=True)
        await session.execute(statement)
        await session.commit()


def _looks_like_closed_connection(exc: BaseException) -> bool:
    if isinstance(exc, DBAPIError) and getattr(exc, "connection_invalidated", False):
        return True
    message = str(exc).lower()
    return (
        "connection is closed" in message
        or "connection was closed" in message
        or "connection has been closed" in message
    )


async def _get_internal_access_token(
    session: AsyncSession,
    row: GatewayNotebookSession,
) -> str | None:
    """Return the plaintext token from encrypted storage, rotating ciphertext
    written under a retired key."""
    encrypted = getattr(row, "access_token_enc", None)
    if not encrypted:
        return None
    token, needs_migration = _decrypt_with_migration(encrypted)
    if needs_migration:
        row.access_token_enc = _encrypt(token)
        await session.commit()
    return token


def _to_internal(row: GatewayNotebookSession, access_token: str | None) -> NotebookSessionInternal:
    return NotebookSessionInternal(
        session_id=row.id,
        org_id=row.org_id,
        user_id=row.user_id,
        status=row.status,
        backend=row.backend,
        runtime_handle=row.runtime_handle,
        upstream_url=row.upstream_url,
        snapshot_id=row.snapshot_id,
        access_token=access_token,
        project_id=row.project_id,
        branch=row.branch,
        last_ping=row.last_ping,
        last_extend_at=row.last_extend_at,
    )


def _to_info(row: GatewayNotebookSession) -> NotebookSessionInfo:
    """FE-facing view of a session row. No credentials, no upstream URL:
    the browser only ever sees the proxy path."""
    notebook_url = f"/notebook/{row.id}/" if row.status in ("running", "snapshotted") else None
    return NotebookSessionInfo(
        id=row.id,
        org_id=row.org_id,
        user_id=row.user_id,
        project_id=row.project_id,
        branch=row.branch,
        backend=row.backend,
        status=row.status,
        notebook_url=notebook_url,
        last_ping=row.last_ping,
        created_at=row.created_at,
    )
