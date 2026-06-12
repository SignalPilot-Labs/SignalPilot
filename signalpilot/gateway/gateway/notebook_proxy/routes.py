"""Notebook proxy routes — FastAPI router mounted at /notebook.

Auth bypass note: routes in this module use resolve_proxy_session directly
instead of RequireScope. This is the ONLY sanctioned bypass of scope_guard.py.
See scope_guard.py docstring and notebook_proxy/auth.py for rationale.

URL shape:
    ANY  /notebook/{session_id}/{path:path}     → proxied HTTP to pod
    WS   /notebook/{session_id}/{path:path}     → proxied WebSocket to pod

Auth (resolve_proxy_session): Clerk JWT (cloud) / no-auth (local) + same-user
session ownership. There is no /_init, no cookie, no handshake token — the
browser sends the Clerk JWT directly (Authorization header for HTTP, the
Sec-WebSocket-Protocol two-token form for WS).
"""

from __future__ import annotations

import logging
import re

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from fastapi.websockets import WebSocket

from .auth import ProxySession, resolve_proxy_session
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

    Auth: resolve_proxy_session (Clerk/API-key/local + same-user ownership).
    No RequireScope — see module docstring.
    """
    http_client = _get_proxy_client(request)
    proxy = NotebookProxy(proxy_session.upstream_base, http_client=http_client)
    return await proxy.forward_http(request, path)


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

    Auth: resolve_proxy_session verifies the JWT (from the Sec-WebSocket-Protocol
    two-token form in cloud) before ws.accept() is called.

    Subprotocol echo: if the client offered the two-token form, the WS accept
    echoes back ONLY the sentinel "signalpilot.auth" — never the token
    (RFC 6455: the server selects one subprotocol from the offered list).

    No RequireScope — see module docstring.
    """
    raw_query = ws.url.query

    logger.info(
        "WS HANDLER: session=%s path=%s query=%s upstream_base=%s user=%s org=%s",
        session_id, path, raw_query, proxy_session.upstream_base,
        getattr(proxy_session, "user_id", "?"), getattr(proxy_session, "org_id", "?"),
    )

    # M-3: Validate query string before forwarding to upstream.
    # Reject CR/LF and any char outside the safe URL charset to prevent response-
    # splitting and notebook server session-ID abuse via querystring manipulation.
    forwarded_query = raw_query
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
