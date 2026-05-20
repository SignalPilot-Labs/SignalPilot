"""Notebook session endpoints — lifecycle management for user notebook pods."""

from __future__ import annotations

import hashlib
import logging
import os

from fastapi import APIRouter, HTTPException

from ..auth.notebook_jwt import mint_session_jwt
from ..config.k8s import get_k8s_settings
from ..models.notebook_sessions import NotebookSessionCreate, NotebookSessionInfo
from ..runtime.mode import is_cloud_mode
from ..security.scope_guard import RequireScope
from .deps import StoreD

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notebook-sessions")


def _pod_name(org_id: str, user_id: str) -> str:
    h = hashlib.sha256(f"{org_id}:{user_id}".encode()).hexdigest()[:12]
    return f"nb-{h}"


async def _get_orchestrator():
    from ..orchestrator.kubernetes import KubernetesOrchestrator

    return KubernetesOrchestrator()


@router.post("", status_code=201, response_model=NotebookSessionInfo, dependencies=[RequireScope("write")])
async def create_session(body: NotebookSessionCreate, store: StoreD):
    """Create or return existing notebook session for the current user."""
    from ..store import notebook_sessions as ns

    org_id = store.org_id
    if is_cloud_mode() and not store.user_id:
        raise HTTPException(status_code=401, detail="User identity required")
    user_id = store.user_id or "local"

    existing = await ns.get_active_session(store.session, org_id=org_id, user_id=user_id)
    if existing and existing.status == "running" and existing.pod_ip and existing.pod_name:
        orch = await _get_orchestrator()
        if await orch.is_pod_alive(existing.pod_name):
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
    # JWT callback (SP_SESSION_JWT + SP_ACCESS_TOKEN) to an arbitrary origin.
    gateway_url = k8s_settings.sp_public_gateway_url

    try:
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
        pod_info = await orch.wait_for_ready(pod, timeout=90)
        await ns.update_session_status(
            store.session, session_id=session_info.id, status="running", pod_ip=pod_info.ip
        )
        session_info.status = "running"
        session_info.pod_ip = pod_info.ip
        # Build the direct notebook URL for the frontend iframe
        session_info.notebook_url = f"http://{pod_info.ip}?access_token={session_info.access_token}"
    except Exception as e:
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
    """Get a specific session by id, scoped to the caller's org. Returns 404 on missing or cross-org."""
    from ..store import notebook_sessions as ns

    org_id = store.org_id or ""
    session = await ns.get_session_by_id(store.session, session_id=session_id, org_id=org_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.delete("", status_code=204, response_model=None, dependencies=[RequireScope("write")])
async def delete_session(store: StoreD):
    """Kill current user's notebook session."""
    from ..store import notebook_sessions as ns

    org_id = store.org_id
    user_id = store.user_id or "local"

    session = await ns.get_active_session(store.session, org_id=org_id, user_id=user_id)
    if not session:
        raise HTTPException(status_code=404, detail="No active session")

    orch = await _get_orchestrator()
    if session.pod_name:
        await orch.delete_pod(session.pod_name)
    await ns.mark_stopped(store.session, session_id=session.id)


@router.delete("/{session_id}", status_code=204, response_model=None, dependencies=[RequireScope("write")])
async def delete_session_by_id(session_id: str, store: StoreD):
    """Delete a specific session by id, scoped to the caller's org. Returns 404 on missing or cross-org."""
    from ..store import notebook_sessions as ns

    org_id = store.org_id or ""
    session = await ns.get_session_by_id(store.session, session_id=session_id, org_id=org_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    orch = await _get_orchestrator()
    if session.pod_name:
        await orch.delete_pod(session.pod_name)
    await ns.mark_stopped(store.session, session_id=session.id)


@router.post("/ping", response_model=NotebookSessionInfo | None, dependencies=[RequireScope("read")])
async def ping_session(store: StoreD):
    """Keep session alive. Call every 60 seconds."""
    from ..store import notebook_sessions as ns

    org_id = store.org_id or ""
    # Use collection-style ping by org+user; org scoping is implicit via the where clause.
    return await ns.ping_session(store.session, org_id=org_id, user_id=store.user_id or "local")
