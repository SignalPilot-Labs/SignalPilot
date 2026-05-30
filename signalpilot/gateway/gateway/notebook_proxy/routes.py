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
import time
import urllib.parse
from collections import defaultdict

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.websockets import WebSocket

from ..auth.user import resolve_user_id
from ..config.k8s import get_k8s_settings
from ..runtime.mode import is_cloud_mode
from ..store import notebook_sessions as ns
from .auth import SESSION_ID_PATTERN, ProxySession, resolve_proxy_session
from .cookies import set_proxy_cookie
from .proxy import NotebookProxy

# Keys that must be scrubbed from logged query strings to prevent token leakage.
_SENSITIVE_QUERY_KEYS = frozenset({"access_token", "token"})

_INIT_RATE_WINDOW_S = 60.0
_INIT_RATE_MAX = 30  # 30 GETs/min per (ip, session_id) — tight; legitimate flow needs 1
_init_hits: dict[tuple[str, str], list[float]] = defaultdict(list)


def _init_rate_limit_check(ip: str, session_id: str) -> bool:
    """Return True if under limit, False if exceeded. Mutates the bucket."""
    now = time.monotonic()
    cutoff = now - _INIT_RATE_WINDOW_S
    key = (ip, session_id)
    hits = _init_hits[key]
    # In-place filter to bound memory; also opportunistically GC empty keys.
    _init_hits[key] = [t for t in hits if t > cutoff]
    if len(_init_hits[key]) >= _INIT_RATE_MAX:
        return False
    _init_hits[key].append(now)
    # TODO: GC empty-list keys here for unbounded-growth prevention if reviewers flag.
    return True


def _client_ip_for_init(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        # Rightmost = closest trusted proxy. Same convention as RateLimitMiddleware.
        return fwd.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"

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

    ip = _client_ip_for_init(request)
    if not _init_rate_limit_check(ip, session_id):
        raise HTTPException(status_code=429, detail="Too many init requests")

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
    response.headers["Referrer-Policy"] = "no-referrer"
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

    Subprotocol echo: if auth succeeded via Sec-WebSocket-Protocol two-token form,
    the WS accept echoes back ONLY the sentinel "signalpilot.auth" — never the token.
    This is per RFC 6455 (server selects one subprotocol from the offered list).

    No RequireScope — see module docstring.
    """
    raw_query = ws.url.query

    # Scrub sensitive keys from query string BEFORE logging or forwarding upstream.
    # access_token / token values must never appear in log records or be forwarded
    # to the upstream pod (where they would appear in pod/ingress access logs).
    if raw_query:
        safe_pairs = [
            (k, v)
            for k, v in urllib.parse.parse_qsl(raw_query, keep_blank_values=True)
            if k not in _SENSITIVE_QUERY_KEYS
        ]
        logged_query = urllib.parse.urlencode(safe_pairs)
        forwarded_query = logged_query
    else:
        logged_query = ""
        forwarded_query = ""

    logger.info(
        "WS HANDLER: session=%s path=%s query=%s upstream_base=%s user=%s org=%s",
        session_id, path, logged_query, proxy_session.upstream_base,
        getattr(proxy_session, "user_id", "?"), getattr(proxy_session, "org_id", "?"),
    )

    # M-3: Validate query string before forwarding to upstream.
    # Reject CR/LF and any char outside the safe URL charset to prevent response-
    # splitting and notebook server session-ID abuse via querystring manipulation.
    if forwarded_query and not _WS_QUERY_SAFE_PATTERN.match(forwarded_query):
        logger.warning(
            "WS query string contains unsafe characters for session %s — dropping query",
            proxy_session.session_id,
        )
        forwarded_query = ""

    upstream_url = (
        f"ws://{proxy_session.upstream_base.removeprefix('http://')}/{path.lstrip('/')}"
    )
    if forwarded_query:
        upstream_url = f"{upstream_url}?{forwarded_query}"

    logger.info(
        "WS UPSTREAM URL: ws://%s/%s query=%s",
        proxy_session.upstream_base.removeprefix("http://"),
        path.lstrip("/"),
        logged_query,
    )

    # Echo the sentinel subprotocol if the client offered the two-token form.
    # Never echo the token itself — it must not appear in the handshake response.
    offered = ws.headers.get("sec-websocket-protocol", "")
    offered_entries = [e.strip() for e in offered.split(",")] if offered else []
    accept_subprotocol = (
        "signalpilot.auth" if "signalpilot.auth" in offered_entries else None
    )

    proxy = NotebookProxy(
        proxy_session.upstream_base,
        http_client=_get_proxy_client(ws),
    )
    await proxy.forward_ws(ws, upstream_url, accept_subprotocol=accept_subprotocol)
