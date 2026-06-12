"""Notebook session endpoints — lifecycle management for user notebook pods."""

from __future__ import annotations

import os
import re

from fastapi import APIRouter, HTTPException, Response

from ..models.notebook_sessions import NotebookSessionCreate, NotebookSessionInfo
from ..notebooks import session_service
from ..notebook_proxy.constants import SESSION_ID_PATTERN_STR
from ..runtime.mode import is_cloud_mode
from ..security.scope_guard import RequireScope
from .deps import ProjectsGate, StoreD

# Single source of truth for session_id charset validation (shared with proxy auth).
_SESSION_ID_PATTERN = re.compile(SESSION_ID_PATTERN_STR)

# Notebook sessions are part of the paid "projects" feature. In local mode the
# tier resolves to "unlimited", so the gate is a no-op.
router = APIRouter(prefix="/api/notebook-sessions", dependencies=[ProjectsGate])


def _pod_name(org_id: str, user_id: str) -> str:
    return session_service.pod_name_for(org_id, user_id)


_get_orchestrator = session_service._get_orchestrator


def _is_quota_exceeded_error(exc: Exception) -> bool:
    return session_service._is_quota_exceeded_error(exc)


@router.post("", status_code=201, response_model=NotebookSessionInfo, dependencies=[RequireScope("write")])
async def create_session(body: NotebookSessionCreate, store: StoreD, _response: Response):
    """Create or return existing notebook session for the current user."""
    org_id = store.org_id
    # org_id is required in all modes — no fallback namespace allowed (R3).
    if not org_id:
        raise HTTPException(status_code=400, detail="org_id required")

    if is_cloud_mode() and not store.user_id:
        raise HTTPException(status_code=401, detail="User identity required")
    user_id = store.user_id or "local"
    project_id = body.project_id or None
    try:
        return await session_service.ensure_notebook_session(
            store.session,
            org_id=org_id,
            user_id=user_id,
            project_id=project_id,
            branch=body.branch,
            get_orchestrator=_get_orchestrator,
        )
    except session_service.NotebookQuotaExceededError:
        raise HTTPException(status_code=429, detail="Org quota exhausted")
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
    read each other's sessions — sharing is a future feature).
    """
    from ..store import notebook_sessions as ns

    # M-4: Validate session_id charset before interpolating into cookie paths.
    if not _SESSION_ID_PATTERN.match(session_id):
        raise HTTPException(status_code=404, detail="Session not found")

    org_id = store.org_id or ""
    session = await ns.get_session_by_id(store.session, session_id=session_id, org_id=org_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # M-1: Ownership check — same-org non-owners get 404 (not 403) to avoid
    # leaking existence information. Mirrors the proxy's resolve_proxy_session check.
    user_id = store.user_id or "local"
    if session.user_id != user_id:
        raise HTTPException(status_code=404, detail="Session not found")

    return session


@router.delete("", status_code=204, response_model=None, dependencies=[RequireScope("write")])
async def delete_session(store: StoreD, _response: Response):
    """Kill current user's notebook session."""
    from ..store import notebook_sessions as ns

    org_id = store.org_id
    user_id = store.user_id or "local"

    session = await ns.get_active_session(store.session, org_id=org_id, user_id=user_id)
    if not session:
        raise HTTPException(status_code=404, detail="No active session")

    orch = await _get_orchestrator()

    direct_url = os.getenv("SP_NOTEBOOK_DIRECT_URL", "")
    if not direct_url and session.pod_name:
        await orch.delete_pod(session.pod_name, org_id=org_id or "")
    await ns.mark_stopped(store.session, session_id=session.id, org_id=session.org_id)


@router.delete("/{session_id}", status_code=204, response_model=None, dependencies=[RequireScope("write")])
async def delete_session_by_id(session_id: str, store: StoreD):
    """Delete a specific session by id, scoped to the caller's org and user.

    Returns 404 on missing, cross-org, OR cross-user (same-org peers cannot
    delete each other's sessions).
    """
    from ..store import notebook_sessions as ns

    # M-4: Validate session_id charset at the boundary (defense in depth).
    if not _SESSION_ID_PATTERN.match(session_id):
        raise HTTPException(status_code=404, detail="Session not found")

    org_id = store.org_id or ""
    session = await ns.get_session_by_id(store.session, session_id=session_id, org_id=org_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # M-1: Ownership check — same-org peers cannot delete each other's sessions.
    user_id = store.user_id or "local"
    if session.user_id != user_id:
        raise HTTPException(status_code=404, detail="Session not found")

    orch = await _get_orchestrator()

    if session.pod_name:
        await orch.delete_pod(session.pod_name, org_id=org_id)
    await ns.mark_stopped(store.session, session_id=session.id, org_id=session.org_id)


@router.post("/{session_id}/ping", response_model=NotebookSessionInfo | None, dependencies=[RequireScope("read")])
async def ping_session_by_id(session_id: str, store: StoreD):
    """Keep a specific session alive by id. Call every 60 seconds.

    Returns 404 on missing, cross-org, OR cross-user (same-org peers cannot
    extend each other's sessions' idle timers).
    """
    from ..store import notebook_sessions as ns

    # M-4: Validate session_id charset at the boundary.
    if not _SESSION_ID_PATTERN.match(session_id):
        raise HTTPException(status_code=404, detail="Session not found")

    org_id = store.org_id or ""
    user_id = store.user_id or "local"

    # M-1: Load session to check ownership before pinging.
    session = await ns.get_session_by_id(store.session, session_id=session_id, org_id=org_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.user_id != user_id:
        raise HTTPException(status_code=404, detail="Session not found")

    return await ns.ping_session_by_id(store.session, session_id=session_id, org_id=org_id)


@router.post("/ping", response_model=NotebookSessionInfo | None, dependencies=[RequireScope("read")])
async def ping_session(store: StoreD):
    """Keep session alive. Call every 60 seconds.

    Deprecated: use POST /api/notebook-sessions/{session_id}/ping instead.
    This shim routes to the collection-style ping for backward compatibility.
    """
    from ..store import notebook_sessions as ns

    org_id = store.org_id or ""
    return await ns.ping_session(store.session, org_id=org_id, user_id=store.user_id or "local")
