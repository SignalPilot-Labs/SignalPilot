"""Notebook session endpoints — lifecycle + reverse proxy to user pods."""

from __future__ import annotations

import hashlib
import logging

import httpx
from fastapi import APIRouter, HTTPException, Request, WebSocket
from fastapi.responses import Response, StreamingResponse

from ..models.notebook_sessions import NotebookSessionCreate, NotebookSessionInfo
from ..security.scope_guard import RequireScope
from .deps import StoreD

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notebook-sessions")

_proxy_client: httpx.AsyncClient | None = None


def _get_proxy_client() -> httpx.AsyncClient:
    global _proxy_client
    if _proxy_client is None:
        _proxy_client = httpx.AsyncClient(timeout=httpx.Timeout(60, connect=10))
    return _proxy_client


def _pod_name(org_id: str, user_id: str) -> str:
    h = hashlib.sha256(f"{org_id}:{user_id}".encode()).hexdigest()[:12]
    return f"nb-{h}"


async def _get_orchestrator():
    from ..orchestrator.kubernetes import KubernetesOrchestrator

    return KubernetesOrchestrator()


# ─── Session CRUD ────────────────────────────────────────────────────────────


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

    import os

    try:
        # Pass the user's API key to the pod so it can call back to the gateway
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
            gateway_url=os.getenv("SP_GATEWAY_URL", "http://gateway:3300"),
            api_key=user_api_key,
            access_token=session_info.access_token,
        )
        pod_info = await orch.wait_for_ready(pod, timeout=90)
        await ns.update_session_status(
            store.session, session_id=session_info.id, status="running", pod_ip=pod_info.ip
        )
        session_info.status = "running"
        session_info.pod_ip = pod_info.ip
        session_info.proxy_base = "/api/notebook-sessions/proxy"
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


# ─── Reverse Proxy ───────────────────────────────────────────────────────────


async def _resolve_pod_url_from_store(store: StoreD) -> str:
    from ..store import notebook_sessions as ns

    session = await ns.get_active_session(store.session, org_id=store.org_id, user_id=store.user_id or "local")
    if not session or session.status != "running" or not session.pod_ip:
        raise HTTPException(status_code=404, detail="No running notebook session")
    ip = session.pod_ip
    return f"http://{ip}" if ":" in ip else f"http://{ip}:2718"


async def _resolve_pod_url_from_request(request: Request) -> str:
    """Look up pod URL for the authenticated user, handling both API key and local mode."""
    from ..db.engine import get_session_factory
    from ..store import notebook_sessions as ns

    auth = getattr(request.state, "auth", {})
    org_id = auth.get("org_id", "local")
    user_id = auth.get("user_id", "local")

    factory = get_session_factory()
    async with factory() as session:
        nb_session = await ns.get_active_session(session, org_id=org_id, user_id=user_id)
    if not nb_session or nb_session.status != "running" or not nb_session.pod_ip:
        raise HTTPException(status_code=404, detail="No running notebook session")
    ip = nb_session.pod_ip
    return f"http://{ip}" if ":" in ip else f"http://{ip}:2718"


@router.api_route("/proxy", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
@router.api_route("/proxy/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_http(request: Request, path: str = ""):
    """Reverse proxy HTTP requests to the user's notebook pod."""
    pod_url = await _resolve_pod_url_from_request(request)
    target = f"{pod_url}/{path}"
    if request.url.query:
        target += f"?{request.url.query}"

    client = _get_proxy_client()
    body = await request.body()

    headers = dict(request.headers)
    for h in ["host", "content-length", "transfer-encoding"]:
        headers.pop(h, None)

    try:
        resp = await client.request(
            method=request.method,
            url=target,
            headers=headers,
            content=body if body else None,
            follow_redirects=False,
        )
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail="Notebook pod not reachable")

    resp_headers = dict(resp.headers)
    # Rewrite Location headers so redirects stay within the proxy path
    if "location" in resp_headers:
        loc = resp_headers["location"]
        if loc.startswith("/"):
            resp_headers["location"] = f"/api/notebook-sessions/proxy{loc}"
    # Strip frame-blocking headers from proxied responses
    resp_headers.pop("x-frame-options", None)
    resp_headers.pop("content-security-policy", None)

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=resp_headers,
        media_type=resp.headers.get("content-type"),
    )


@router.websocket("/proxy/ws")
async def proxy_websocket(ws: WebSocket):
    """Reverse proxy WebSocket to the user's notebook pod."""
    import asyncio
    import websockets

    # For WebSocket, auth state is set by the middleware on the initial HTTP upgrade
    auth = getattr(ws.state, "auth", {})
    org_id = auth.get("org_id", "local")
    user_id = auth.get("user_id", "local")

    from ..db.engine import get_session_factory
    from ..store import notebook_sessions as ns

    factory = get_session_factory()
    async with factory() as session:
        nb_session = await ns.get_active_session(session, org_id=org_id, user_id=user_id)
    if not nb_session or not nb_session.pod_ip:
        await ws.close(code=4004, reason="No running notebook session")
        return
    ip = nb_session.pod_ip
    pod_url = f"http://{ip}" if ":" in ip else f"http://{ip}:2718"
    ws_url = pod_url.replace("http://", "ws://") + "/ws"

    await ws.accept()

    try:
        async with websockets.connect(ws_url) as pod_ws:

            async def client_to_pod():
                try:
                    while True:
                        data = await ws.receive_text()
                        await pod_ws.send(data)
                except Exception:
                    pass

            async def pod_to_client():
                try:
                    async for msg in pod_ws:
                        if isinstance(msg, str):
                            await ws.send_text(msg)
                        else:
                            await ws.send_bytes(msg)
                except Exception:
                    pass

            await asyncio.gather(client_to_pod(), pod_to_client())
    except Exception as e:
        logger.warning("WebSocket proxy error: %s", e)
    finally:
        try:
            await ws.close()
        except Exception:
            pass
