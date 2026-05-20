"""Notebook session endpoints — lifecycle management for user notebook pods."""

from __future__ import annotations

import hashlib
import logging
import os

from fastapi import APIRouter, HTTPException, Request

from ..models.notebook_sessions import NotebookSessionCreate, NotebookSessionInfo
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
async def create_session(body: NotebookSessionCreate, store: StoreD, request: Request):
    """Create or return existing notebook session for the current user."""
    from ..store import notebook_sessions as ns

    org_id = store.org_id
    user_id = store.user_id or "local"

    existing = await ns.get_active_session(store.session, org_id=org_id, user_id=user_id)
    if existing:
        return existing

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

    try:
        auth = getattr(request.state, "auth", {})
        user_api_key = None
        if auth.get("auth_method") == "api_key":
            user_api_key = request.headers.get("x-api-key") or (
                request.headers.get("authorization", "").removeprefix("Bearer ").strip() or None
            )

        await orch.create_pod(
            pod_name=pod,
            user_id=user_id,
            org_id=org_id,
            project_id=body.project_id,
            branch=body.branch,
            image=os.getenv("SP_NOTEBOOK_IMAGE", "signalpilot-notebook:latest"),
            gateway_url=f"{request.url.scheme}://{request.url.netloc}",
            api_key=user_api_key,
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


@router.post("/ping", response_model=NotebookSessionInfo | None, dependencies=[RequireScope("read")])
async def ping_session(store: StoreD):
    """Keep session alive. Call every 60 seconds."""
    from ..store import notebook_sessions as ns
    return await ns.ping_session(store.session, org_id=store.org_id, user_id=store.user_id or "local")
