"""Authentication dependency for the notebook proxy.

Routes under /notebook/* use resolve_proxy_session instead of RequireScope.
This is the ONLY sanctioned bypass of scope_guard.py — documented here and
mirrored in scope_guard.py's docstring and routes.py's header comment.

Auth chain (runs on every HTTP and WS request, before ws.accept()):
1. Validate session_id against SESSION_ID_PATTERN — 404 otherwise.
2. Cloud mode: unconditionally reject any request carrying access_token/token
   query params, regardless of whether cookie/header/subprotocol auth also succeeds.
3. Token extraction order:
   a. Cookie sp_nb_{session_id} (primary).
   b. Authorization: Bearer <token>.
   c. Sec-WebSocket-Protocol: two-token form ["signalpilot.auth", "<token>"].
   d. ?access_token= query param — LOCAL MODE ONLY. Cloud mode already rejected above.
4. store.get_session_internal(session_id) — 404 on miss.
5. constant-time cookie comparison against DB-stored access_token.
6. session.status == "running" and pod_ip_internal set — 409 otherwise.

Re-exports: resolve_user_id, resolve_org_id are re-exported from auth.user for
backwards compatibility with tests and callers.

Non-browser-client scope: the MCP server and CLI tooling do NOT connect to
/notebook/{session_id}/ws — they use HTTP with Authorization: Bearer.
The only WS clients are browser-side; all auth flows through cookie or
Sec-WebSocket-Protocol. See F-8 spec for rationale.
"""

from __future__ import annotations

import logging
import os
import re
import secrets
from dataclasses import dataclass

from fastapi import HTTPException
from starlette.requests import HTTPConnection

from ..auth.user import resolve_org_id, resolve_user_id  # noqa: F401  # re-exported for tests/back-compat
from ..runtime.mode import is_cloud_mode
from ..store import notebook_sessions as ns
from .constants import POD_PORT, SESSION_ID_PATTERN_STR
from .cookies import cookie_name

SESSION_ID_PATTERN = re.compile(SESSION_ID_PATTERN_STR)

# Pattern for valid URL-safe tokens (no whitespace or control chars).
# Subprotocol tokens must be URL-safe: alphanumeric + [-._~] only.
_URLSAFE_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9\-._~]+$")

_log = logging.getLogger("notebook_proxy.auth")


def _extract_subprotocol_token(connection: HTTPConnection) -> str | None:
    """Extract bearer token from Sec-WebSocket-Protocol two-token form.

    Expected form: "signalpilot.auth, <urlsafe-token>"
    Server echoes back ONLY the sentinel "signalpilot.auth" (not the token)
    per RFC 6455 — never reflect the token in the response header.

    The single-token form "signalpilot.bearer.<token>" is NOT supported (S4).
    """
    header = connection.headers.get("sec-websocket-protocol", "")
    if not header:
        return None

    entries = [e.strip() for e in header.split(",")]
    try:
        sentinel_idx = entries.index("signalpilot.auth")
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
    """Resolved proxy session — returned by resolve_proxy_session.

    upstream_base: full base URL of the pod (e.g. http://10.42.0.5:2718).
    proxy_cookie_token: the opaque token from the validated cookie (never log this).
    """

    session_id: str
    user_id: str
    org_id: str
    upstream_base: str
    proxy_cookie_token: str


async def resolve_proxy_session(
    session_id: str,
    connection: HTTPConnection,
) -> ProxySession:
    """FastAPI dependency: authenticate and resolve a notebook proxy request.

    Uses HTTPConnection (not Request) so this dependency works for both HTTP
    routes and WebSocket routes.

    Auth: validates the session cookie (sp_nb_{session_id}) via constant-time
    comparison against the DB-stored access_token. User/org identity is derived
    from the session record — no Clerk JWT needed (the iframe doesn't have it).

    Does NOT use StoreD or RequireScope — see module docstring for rationale.

    Token extraction order:
    1. Cookie.
    2. Authorization: Bearer <token>.
    3. Sec-WebSocket-Protocol two-token form.
    4. ?access_token= query param — LOCAL MODE ONLY (rejected with 401 in cloud mode).
    """
    scope_type = getattr(connection, "scope", {}).get("type", "unknown")
    _log.info("resolve_proxy_session: session_id=%s scope=%s", session_id, scope_type)

    if not SESSION_ID_PATTERN.match(session_id):
        _log.warning("REJECT: session_id charset invalid: %s", session_id[:40])
        raise HTTPException(status_code=404, detail="Session not found")

    # Step 1: Cloud mode — unconditionally reject any request that carries a
    # token in the query string, regardless of whether cookie/header/subprotocol
    # auth also succeeds. This prevents stale or leaked tokens from surviving
    # into upstream logs even when a valid cookie is present.
    if is_cloud_mode():
        query_token = (
            connection.query_params.get("access_token")
            or connection.query_params.get("token")
        )
        if query_token is not None:
            _log.warning(
                "REJECT: access_token/token query param rejected in cloud mode for session %s",
                session_id,
            )
            raise HTTPException(
                status_code=401,
                detail="access_token query param rejected in cloud mode",
            )

    # Step 2: extract token from cookie, Authorization header, subprotocol, or query param.
    # Cookie is the primary auth mechanism (set by _init). Bearer token and
    # subprotocol are for WS clients where cookies are not available.
    # ?access_token= is only allowed in local mode (cloud mode rejected above).
    cookie_value = connection.cookies.get(cookie_name(session_id))

    if cookie_value is None:
        auth_header = connection.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            cookie_value = auth_header[7:]

    if cookie_value is None:
        cookie_value = _extract_subprotocol_token(connection)

    if cookie_value is None:
        # Query param path: local mode only (cloud mode already rejected above).
        query_token = connection.query_params.get("access_token") or connection.query_params.get("token")
        if query_token is not None:
            cookie_value = query_token

    if cookie_value is None:
        all_cookies = list(connection.cookies.keys())
        _log.warning("REJECT: no token found (cookie/header/subprotocol/query). cookies: %s", all_cookies)
        raise HTTPException(
            status_code=401,
            detail="Cookie missing; re-init session",
            headers={"WWW-Authenticate": "SP-Notebook-Init"},
        )

    # Step 2: load session from DB (no org filter — cookie is the auth gate)
    from ..db.engine import get_session_factory
    factory = get_session_factory()
    async with factory() as db_session:
        session = await ns.get_session_internal(
            db_session, session_id=session_id,
        )

    if session is None:
        _log.warning("REJECT: session not found in DB for id=%s", session_id)
        raise HTTPException(status_code=404, detail="Session not found")

    # Step 3: constant-time cookie comparison
    if not secrets.compare_digest(cookie_value, session.access_token or ""):
        _log.warning("REJECT: cookie value mismatch for session %s", session_id)
        raise HTTPException(status_code=401, detail="Session token mismatch")

    _log.info("  session authenticated: user=%s org=%s status=%s",
              session.user_id, session.org_id, session.status)

    # Step 4: readiness check + upstream URL resolution
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
        proxy_cookie_token=cookie_value,
    )
