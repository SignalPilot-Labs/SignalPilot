"""Authentication dependency for the notebook proxy.

Routes under /notebook/* use resolve_proxy_session instead of RequireScope.
This is the ONLY sanctioned bypass of scope_guard.py — documented here and
mirrored in scope_guard.py's docstring and routes.py's header comment.

Auth model (the notebook proxy is hit by exactly two clients):
- A browser user on the web app → Clerk JWT (cloud) or no auth (local dev).
- (MCP/CLI never hit this proxy — run_notebook execs in the pod via the
  gateway's k8s client, not /notebook HTTP.)

Auth chain (runs on every HTTP and WS request, before ws.accept()):
1. Validate session_id against SESSION_ID_PATTERN — 404 otherwise.
2. Resolve the caller identity with the SAME verifier as /api routes
   (auth/user.resolve_user_id): Clerk JWT in cloud, synthetic "local" in local.
   - HTTP: the token rides the Authorization: Bearer header (set by the embed
     client / boot fetches).
   - WS: browsers cannot set Authorization on a WebSocket, so the token rides
     the Sec-WebSocket-Protocol two-token form ["signalpilot.auth", "<jwt>"];
     we verify it via auth/user.verify_jwt_token.
3. Load the session (no org filter — ownership is the gate).
4. Ownership: session.user_id == caller user_id (same-user only). 404 otherwise
   (404 not 403 so we don't reveal that a session id exists for another user).
5. session.status == "running" and pod_ip_internal set — 409 otherwise.

resolve_user_id / resolve_org_id are re-exported for tests/back-compat.
"""

from __future__ import annotations

import hmac
import logging
import os
import re
from dataclasses import dataclass

from fastapi import HTTPException
from starlette.requests import HTTPConnection

from ..auth.user import resolve_org_id, resolve_user_id, verify_jwt_token  # noqa: F401  # re-exported
from ..runtime.mode import is_cloud_mode
from ..store import get_local_api_key
from ..store import notebook_sessions as ns
from .constants import POD_PORT, SESSION_ID_PATTERN_STR

SESSION_ID_PATTERN = re.compile(SESSION_ID_PATTERN_STR)

# Sentinel the client offers as the first WS subprotocol; the JWT is the second.
# Server echoes ONLY the sentinel back, never the token (RFC 6455).
_WS_AUTH_SENTINEL = "signalpilot.auth"
# Subprotocol tokens must be URL-safe (no whitespace/control chars). A JWT is
# base64url segments joined by dots, so this charset covers it.
_URLSAFE_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9\-._~]+$")

_log = logging.getLogger("notebook_proxy.auth")


def _extract_subprotocol_token(connection: HTTPConnection) -> str | None:
    """Extract the JWT from the Sec-WebSocket-Protocol two-token form.

    Expected: "signalpilot.auth, <urlsafe-jwt>". Returns the token, or None if
    the header is absent/malformed.
    """
    header = connection.headers.get("sec-websocket-protocol", "")
    if not header:
        return None
    entries = [e.strip() for e in header.split(",")]
    try:
        sentinel_idx = entries.index(_WS_AUTH_SENTINEL)
    except ValueError:
        return None
    token_idx = sentinel_idx + 1
    if token_idx >= len(entries):
        return None
    token = entries[token_idx]
    if not token or not _URLSAFE_TOKEN_PATTERN.match(token):
        _log.warning("Subprotocol token rejected: invalid character set")
        return None
    return token


@dataclass(frozen=True)
class ProxySession:
    session_id: str
    user_id: str
    org_id: str
    upstream_base: str


def _is_websocket(connection: HTTPConnection) -> bool:
    return getattr(connection, "scope", {}).get("type") == "websocket"


def _extract_bearer_token(connection: HTTPConnection) -> str | None:
    auth_header = connection.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:].strip()
    return None


def _resolve_local_proxy_auth(connection: HTTPConnection) -> str | None:
    if is_cloud_mode():
        return None
    bearer = _extract_bearer_token(connection)
    if bearer is None:
        return None
    local_key = get_local_api_key()
    if local_key and hmac.compare_digest(bearer, local_key):
        connection.state.auth = {
            "user_id": "local",
            "org_id": "local",
            "auth_method": "local_key",
        }
        connection.state._jwt_claims = {"sub": "local", "org_id": "local"}
        return "local"
    if bearer.startswith("sp_"):
        _log.warning("REJECT: invalid local proxy API key for session request")
        raise HTTPException(status_code=401, detail="Invalid local API key")
    return None


async def resolve_proxy_session(
    connection: HTTPConnection,
    session_id: str,
) -> ProxySession:
    """Authenticate the caller, verify session ownership, resolve the upstream pod.

    See module docstring for the full chain. Used as a FastAPI dependency for both
    the HTTP and WebSocket proxy routes.
    """
    scope_type = getattr(connection, "scope", {}).get("type", "unknown")
    _log.info("resolve_proxy_session: session_id=%s scope=%s", session_id, scope_type)

    if not SESSION_ID_PATTERN.match(session_id):
        _log.warning("REJECT: session_id charset invalid: %s", session_id[:40])
        raise HTTPException(status_code=404, detail="Session not found")

    # Step 1: resolve caller identity (Clerk/API-key/local).
    # WebSockets can't carry Authorization, so when this is a WS and no auth state
    # was pre-set, verify the JWT from the Sec-WebSocket-Protocol subprotocol.
    local_user_id = _resolve_local_proxy_auth(connection)
    if local_user_id is not None:
        user_id = local_user_id
    elif _is_websocket(connection) and getattr(connection.state, "auth", None) is None and is_cloud_mode():
        sub_token = _extract_subprotocol_token(connection)
        if sub_token is None:
            _log.warning("REJECT: no WS subprotocol auth token for session %s", session_id)
            raise HTTPException(status_code=401, detail="Authentication required")
        user_id = await verify_jwt_token(connection, sub_token)
    else:
        user_id = await resolve_user_id(connection)
    org_id = await resolve_org_id(connection, user_id)

    # Step 2: load session (no org filter — ownership check below is the gate).
    from ..db.engine import get_session_factory
    factory = get_session_factory()
    async with factory() as db_session:
        session = await ns.get_session_internal(db_session, session_id=session_id)

    if session is None:
        _log.warning("REJECT: session not found in DB for id=%s", session_id)
        raise HTTPException(status_code=404, detail="Session not found")

    # Step 3: ownership — same user only. 404 (not 403) to avoid revealing that
    # the session exists for a different user.
    if session.user_id != user_id:
        _log.warning("REJECT: session %s owned by %s, caller %s", session_id, session.user_id, user_id)
        raise HTTPException(status_code=404, detail="Session not found")

    _log.info("  session authenticated: user=%s org=%s status=%s",
              session.user_id, session.org_id, session.status)

    # Step 4: readiness check + upstream URL resolution.
    direct_url = os.getenv("SP_NOTEBOOK_DIRECT_URL", "")
    if direct_url:
        upstream_base = direct_url.rstrip("/")
    elif session.status != "running" or not session.pod_ip_internal:
        _log.warning("REJECT: not ready status=%s pod_ip_internal=%s",
                      session.status, session.pod_ip_internal)
        raise HTTPException(status_code=409, detail="Session not ready")
    else:
        upstream_base = f"http://{session.pod_ip_internal}:{POD_PORT}/notebook/{session_id}"

    return ProxySession(
        session_id=session_id,
        user_id=session.user_id,
        org_id=session.org_id or "local",
        upstream_base=upstream_base,
    )
