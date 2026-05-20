"""Notebook session endpoints — lifecycle management for user notebook pods."""

from __future__ import annotations

import hashlib
import logging
import os
import re

from fastapi import APIRouter, HTTPException, Response

from ..auth.notebook_jwt import mint_session_jwt
from ..config.k8s import get_k8s_settings
from ..models.notebook_sessions import NotebookSessionCreate, NotebookSessionInfo
from ..notebook_proxy.constants import SESSION_ID_PATTERN_STR
from ..notebook_proxy.cookies import clear_proxy_cookie
from ..runtime.mode import is_cloud_mode
from ..security.scope_guard import RequireScope
from .deps import StoreD

# Single source of truth for session_id charset validation (shared with proxy auth).
_SESSION_ID_PATTERN = re.compile(SESSION_ID_PATTERN_STR)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notebook-sessions")


def _pod_name(org_id: str, user_id: str) -> str:
    h = hashlib.sha256(f"{org_id}:{user_id}".encode()).hexdigest()[:12]
    return f"nb-{h}"


async def _get_orchestrator():
    from ..orchestrator.kubernetes import KubernetesOrchestrator

    return KubernetesOrchestrator()


def _is_quota_exceeded_error(exc: Exception) -> bool:
    """Return True if the exception is a K8s 403 ResourceQuota exceeded error."""
    exc_str = str(exc)
    return (
        ("403" in exc_str or "Forbidden" in exc_str)
        and ("exceeded quota" in exc_str.lower() or "quota" in exc_str.lower())
    )


@router.post("", status_code=201, response_model=NotebookSessionInfo, dependencies=[RequireScope("write")])
async def create_session(body: NotebookSessionCreate, store: StoreD):
    """Create or return existing notebook session for the current user."""
    from ..store import notebook_sessions as ns

    org_id = store.org_id
    # org_id is required in all modes — no fallback namespace allowed (R3).
    if not org_id:
        raise HTTPException(status_code=400, detail="org_id required")

    if is_cloud_mode() and not store.user_id:
        raise HTTPException(status_code=401, detail="User identity required")
    user_id = store.user_id or "local"

    existing = await ns.get_active_session(store.session, org_id=org_id, user_id=user_id)
    if existing and existing.status == "running" and existing.pod_ip and existing.pod_name:
        orch = await _get_orchestrator()
        if await orch.is_pod_alive(existing.pod_name, org_id=org_id):
            return existing
        # Pod is dead — clean up stale session
        await ns.mark_stopped(store.session, session_id=existing.id)
    elif existing:
        # creating state or no pod_ip — mark stopped and recreate
        await ns.mark_stopped(store.session, session_id=existing.id)

    await ns.delete_stopped(store.session, org_id=org_id, user_id=user_id)

    pod = _pod_name(org_id, user_id)
    orch = await _get_orchestrator()

    session_info = await ns.create_session(
        store.session,
        org_id=org_id,
        user_id=user_id,
        project_id=body.project_id,
        branch=body.branch,
        pod_name=pod,
    )

    k8s_settings = get_k8s_settings()
    session_jwt = mint_session_jwt(
        user_id=user_id,
        org_id=org_id,
        session_id=session_info.id,
        project_id=body.project_id,
        branch=body.branch,
        ttl=k8s_settings.sp_session_jwt_ttl_seconds,
    )

    # Use the config-supplied gateway URL — never derive it from the request Host header
    # because that header is attacker-controlled and would let a user redirect the pod's
    # JWT callback to an arbitrary origin.
    gateway_url = k8s_settings.sp_public_gateway_url

    try:
        # access_token is no longer passed to the pod env or CLI (R2: --no-token).
        # It is stored on the DB row only as the gateway proxy cookie value.
        await orch.create_pod(
            pod_name=pod,
            user_id=user_id,
            org_id=org_id,
            project_id=body.project_id,
            branch=body.branch,
            image=os.getenv("SP_NOTEBOOK_IMAGE", "signalpilot-notebook:latest"),
            gateway_url=gateway_url,
            session_jwt=session_jwt,
            session_id=session_info.id,
            access_token=session_info.access_token,
        )
        pod_info = await orch.wait_for_ready(pod, org_id=org_id, timeout=90)
        await ns.update_session_status(
            store.session,
            session_id=session_info.id,
            status="running",
            pod_ip=pod_info.ip,
            pod_ip_internal=pod_info.internal_ip,
        )
        session_info.status = "running"
        session_info.pod_ip = pod_info.ip
        # Proxy-based URL — relative path, no token, no host, no port.
        session_info.notebook_url = f"/notebook/{session_info.id}/_init"
    except ValueError as e:
        logger.warning("Invalid org_id for notebook session: %s", e)
        await ns.update_session_status(store.session, session_id=session_info.id, status="error")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        if _is_quota_exceeded_error(e):
            logger.warning("Org quota exhausted for org %s: %s", org_id, e)
            await ns.update_session_status(store.session, session_id=session_info.id, status="error")
            raise HTTPException(status_code=429, detail="Org quota exhausted")
        logger.error("Failed to create notebook pod %s: %s", pod, e)
        await ns.update_session_status(store.session, session_id=session_info.id, status="error")
        raise HTTPException(status_code=503, detail=f"Failed to start notebook: {e}")

    return session_info


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
async def delete_session(store: StoreD, response: Response):
    """Kill current user's notebook session."""
    from ..store import notebook_sessions as ns

    org_id = store.org_id
    user_id = store.user_id or "local"

    session = await ns.get_active_session(store.session, org_id=org_id, user_id=user_id)
    if not session:
        raise HTTPException(status_code=404, detail="No active session")

    orch = await _get_orchestrator()
    if session.pod_name:
        await orch.delete_pod(session.pod_name, org_id=org_id or "")
    await ns.mark_stopped(store.session, session_id=session.id)

    # Clear the proxy cookie. Path MUST be /notebook/{sid} to match the original
    # cookie's Path= attribute — browsers ignore clear-headers with a mismatched path.
    clear_proxy_cookie(response, session_id=session.id, secure=is_cloud_mode())


@router.delete("/{session_id}", status_code=204, response_model=None, dependencies=[RequireScope("write")])
async def delete_session_by_id(session_id: str, store: StoreD, response: Response):
    """Delete a specific session by id, scoped to the caller's org and user.

    Returns 404 on missing, cross-org, OR cross-user (same-org peers cannot
    delete each other's sessions).
    """
    from ..store import notebook_sessions as ns

    # M-4: Validate session_id charset BEFORE any cookie/header construction.
    # This is defense in depth — clear_proxy_cookie interpolates session_id into
    # a Set-Cookie Path= attribute, so CR/LF/semicolons must never reach it.
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
    await ns.mark_stopped(store.session, session_id=session.id)

    # Clear the proxy cookie with the correct path.
    clear_proxy_cookie(response, session_id=session_id, secure=is_cloud_mode())


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
