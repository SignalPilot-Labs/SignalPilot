"""Notebook proxy routes — FastAPI router mounted at /notebook.

Auth bypass note: routes in this module use resolve_proxy_session directly
instead of RequireScope. This is the ONLY sanctioned bypass of scope_guard.py.
See scope_guard.py docstring and notebook_proxy/auth.py for rationale.

URL shape:
    GET  /notebook/{session_id}/_init           → sets HttpOnly cookie + 302 redirect
    ANY  /notebook/{session_id}/{path:path}     → proxied HTTP to pod
    WS   /notebook/{session_id}/{path:path}     → proxied WebSocket to pod

session_id is validated against SESSION_ID_PATTERN inside resolve_proxy_session
and inside init_notebook for the _init path before any cookie construction.
"""

from __future__ import annotations

import logging
import re

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.websockets import WebSocket

from ..api.deps import StoreD
from ..auth.user import resolve_org_id, resolve_user_id
from ..config.k8s import get_k8s_settings
from ..runtime.mode import is_cloud_mode
from ..store import notebook_sessions as ns
from .auth import SESSION_ID_PATTERN, ProxySession, resolve_proxy_session
from .cookies import set_proxy_cookie
from .proxy import NotebookProxy

# Safe charset for forwarded WS query strings.
# Allows URL-safe characters: alphanumeric, hyphen, underscore, dot, tilde,
# percent-encoded sequences (%XX), equals, ampersand (k=v&k=v pairs), plus.
# CR (0x0D) and LF (0x0A) are explicitly excluded to prevent HTTP response splitting.
_WS_QUERY_SAFE_PATTERN = re.compile(r"^[A-Za-z0-9\-._~%=&+]*$")

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_proxy_client(request: Request | WebSocket) -> httpx.AsyncClient:
    """Retrieve the shared httpx.AsyncClient from app state."""
    client = getattr(request.app.state, "notebook_proxy_client", None)
    if client is None:
        raise HTTPException(status_code=503, detail="Proxy client not initialized")
    return client


@router.get("/notebook/{session_id}/_init")
async def init_notebook(
    session_id: str,
    request: Request,
    token: str | None = None,
) -> Response:
    """Set the HttpOnly proxy cookie and redirect to the notebook.

    Auth chain (in order):
    1. Clerk JWT / API key → resolve_user_id (works when called from same origin)
    2. ?token= query param → session access_token (works cross-origin from web FE)

    The token param is a signed session secret embedded in notebook_url by the
    gateway when the session is created. It allows the web frontend (different
    origin, no Clerk cookie) to initialize the session cookie securely.
    """
    import secrets as _secrets

    if not SESSION_ID_PATTERN.match(session_id):
        raise HTTPException(status_code=404, detail="Session not found")

    from ..db.engine import get_session_factory
    factory = get_session_factory()
    async with factory() as db_session:
        session = await ns.get_session_internal(
            db_session, session_id=session_id,
        )

    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Auth: try Clerk/API key first, fall back to ?token= param
    authed = False
    try:
        user_id = await resolve_user_id(request)
        if session.user_id == user_id:
            authed = True
    except Exception:
        pass

    if not authed and token:
        if _secrets.compare_digest(token, session.access_token or ""):
            authed = True

    if not authed:
        raise HTTPException(status_code=401, detail="Authentication required")

    if session.status != "running" or not session.pod_ip_internal:
        raise HTTPException(status_code=409, detail="Session not ready")

    k8s_settings = get_k8s_settings()
    response = RedirectResponse(
        url=f"/notebook/{session_id}/",
        status_code=302,
    )
    set_proxy_cookie(
        response,
        session_id=session_id,
        token=session.access_token or "",
        secure=is_cloud_mode(),
        max_age=k8s_settings.sp_session_jwt_ttl_seconds,
    )
    return response


@router.api_route(
    "/notebook/{session_id}/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
async def proxy_http(
    session_id: str,
    path: str,
    request: Request,
    proxy_session: ProxySession = Depends(resolve_proxy_session),
) -> Response:
    """Proxy an HTTP request to the notebook pod.

    Auth: resolve_proxy_session (cookie-validated, org/user-scoped).
    No RequireScope — see module docstring.

    Cookie slide: after a successful proxy, re-emit the session cookie with a
    fresh Max-Age so actively-used sessions never silently expire mid-work.
    The token value is unchanged — only the expiry window is extended.
    """
    http_client = _get_proxy_client(request)
    proxy = NotebookProxy(proxy_session.upstream_base, http_client=http_client)
    response = await proxy.forward_http(request, path)
    k8s_settings = get_k8s_settings()
    set_proxy_cookie(
        response,
        session_id=proxy_session.session_id,
        token=proxy_session.proxy_cookie_token,
        secure=is_cloud_mode(),
        max_age=k8s_settings.sp_session_jwt_ttl_seconds,
    )
    return response


@router.websocket("/notebook/{session_id}/{path:path}")
async def proxy_websocket(
    session_id: str,
    path: str,
    ws: WebSocket,
    proxy_session: ProxySession = Depends(resolve_proxy_session),
) -> None:
    """Bridge a WebSocket connection to the notebook pod.

    Only one broad WS endpoint — covers /ws, LSP, iosub, and any other path
    the notebook server emits under --base-url /notebook/{session_id}.

    Auth: resolve_proxy_session validates cookie before ws.accept() is called.
    On auth failure the dependency raises HTTPException which FastAPI translates
    to a close before accept. We additionally guard with an explicit close on
    failure path in the proxy.

    No RequireScope — see module docstring.
    """
    raw_query = ws.url.query
    logger.info("WS HANDLER: session=%s path=%s query=%s upstream_base=%s",
                session_id, path, raw_query, proxy_session.upstream_base)
    # M-3: Validate query string before forwarding to upstream.
    # Reject CR/LF and any char outside the safe URL charset to prevent response-
    # splitting and notebook server session-ID abuse via querystring manipulation.
    # Since the pod runs --no-token, no secrets are at risk, but we still must
    # not forward attacker-controlled bytes into the upstream WS URL.
    if raw_query and not _WS_QUERY_SAFE_PATTERN.match(raw_query):
        logger.warning(
            "WS query string contains unsafe characters for session %s — dropping query",
            proxy_session.session_id,
        )
        raw_query = ""

    upstream_url = (
        f"ws://{proxy_session.upstream_base.removeprefix('http://')}/{path.lstrip('/')}"
    )
    if raw_query:
        upstream_url = f"{upstream_url}?{raw_query}"

    logger.info("WS UPSTREAM URL: %s", upstream_url)

    proxy = NotebookProxy(
        proxy_session.upstream_base,
        http_client=_get_proxy_client(ws),
    )
    await proxy.forward_ws(ws, upstream_url)
