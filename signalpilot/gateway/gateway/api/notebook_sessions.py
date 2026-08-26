"""Notebook session endpoints: lifecycle management for notebook compute."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Response

from ..models.notebook_sessions import NotebookSessionCreate, NotebookSessionInfo
from ..notebook_proxy.constants import SESSION_ID_PATTERN_STR
from ..notebooks import session_service
from ..runtime.mode import is_cloud_mode
from ..security.scope_guard import RequireScope
from .deps import ProjectsGate, StoreD

# Single source of truth for session_id charset validation (shared with proxy auth).
_SESSION_ID_PATTERN = re.compile(SESSION_ID_PATTERN_STR)

# Notebook sessions are part of the paid "projects" feature. In local mode the
# tier resolves to "unlimited", so the gate is a no-op.
router = APIRouter(prefix="/api/notebook-sessions", dependencies=[ProjectsGate])


@router.post("", status_code=201, response_model=NotebookSessionInfo, dependencies=[RequireScope("write")])
async def create_session(body: NotebookSessionCreate, store: StoreD, _response: Response):
    """Create, reuse, or resume the notebook session for the current user."""
    org_id = store.org_id
    if not org_id:
        raise HTTPException(status_code=400, detail="org_id required")

    if is_cloud_mode() and not store.user_id:
        raise HTTPException(status_code=401, detail="User identity required")
    user_id = store.user_id or "local"
    project_id = body.project_id or None
    if project_id and await store.get_workspace_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        return await session_service.ensure_notebook_session(
            store.session,
            org_id=org_id,
            user_id=user_id,
            project_id=project_id,
            branch=body.branch,
        )
    except session_service.NotebookQuotaExceededError:
        raise HTTPException(status_code=429, detail="Org notebook budget exhausted")
    except (session_service.NotebookOrgRequiredError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except session_service.NotebookSessionError:
        raise HTTPException(status_code=503, detail="Failed to start notebook")


@router.get("", response_model=NotebookSessionInfo | None, dependencies=[RequireScope("read")])
async def get_session(store: StoreD):
    """Get current user's active session."""
    from ..store import notebook_sessions as ns

    return await ns.get_active_session(store.session, org_id=store.org_id, user_id=store.user_id or "local")


@router.get("/{session_id}", response_model=NotebookSessionInfo, dependencies=[RequireScope("read")])
async def get_session_by_id(session_id: str, store: StoreD):
    """Get a specific session by id, scoped to the caller's org and user.

    Returns 404 on missing, cross-org, OR cross-user (same-org peers cannot
    read each other's sessions: sharing is a future feature).
    """
    session = await _owned_session_or_404(session_id, store)
    return session


@router.delete("", status_code=204, response_model=None, dependencies=[RequireScope("write")])
async def delete_session(store: StoreD, _response: Response):
    """Kill current user's notebook session."""
    from ..store import notebook_sessions as ns

    session = await ns.get_active_session(
        store.session, org_id=store.org_id, user_id=store.user_id or "local"
    )
    if not session:
        raise HTTPException(status_code=404, detail="No active session")
    await session_service.terminate_session(store.session, session_info=session)


@router.delete("/{session_id}", status_code=204, response_model=None, dependencies=[RequireScope("write")])
async def delete_session_by_id(session_id: str, store: StoreD):
    """Delete a specific session by id, scoped to the caller's org and user."""
    session = await _owned_session_or_404(session_id, store)
    await session_service.terminate_session(store.session, session_info=session)


@router.post("/{session_id}/ping", response_model=NotebookSessionInfo | None, dependencies=[RequireScope("read")])
async def ping_session_by_id(session_id: str, store: StoreD):
    """Keep a specific session alive by id. Call every 60 seconds — the
    lifecycle loop extends and idles sessions off this timestamp."""
    from ..store import notebook_sessions as ns

    await _owned_session_or_404(session_id, store)
    return await ns.ping_session_by_id(
        store.session, session_id=session_id, org_id=store.org_id or ""
    )


async def _owned_session_or_404(session_id: str, store) -> NotebookSessionInfo:
    """Charset + org + same-user ownership checks, 404 on every failure so
    existence never leaks across users or orgs."""
    from ..store import notebook_sessions as ns

    if not _SESSION_ID_PATTERN.match(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    session = await ns.get_session_by_id(
        store.session, session_id=session_id, org_id=store.org_id or ""
    )
    if not session or session.user_id != (store.user_id or "local"):
        raise HTTPException(status_code=404, detail="Session not found")
    return session
