"""Authentication dependency for the notebook proxy.

Routes under /notebook/* use resolve_proxy_session instead of RequireScope.
This is the ONLY sanctioned bypass of scope_guard.py — documented here and
mirrored in scope_guard.py's docstring and routes.py's header comment.

Auth chain (runs on every HTTP and WS request, before ws.accept()):
1. Validate session_id against SESSION_ID_PATTERN — 404 otherwise.
2. resolve_user_id / resolve_org_id (existing deps).
3. store.get_session_internal(session_id, org_id) — 404 on miss / cross-org.
4. session.user_id == auth.user_id — 404 otherwise.
5. session.status == "running" and pod_ip_internal set — 409 otherwise.
6. Cookie sp_nb_{session_id} present; compare to session.access_token with
   secrets.compare_digest (constant-time) — 401 otherwise.
"""

from __future__ import annotations

import os
import re
import secrets
from dataclasses import dataclass

from fastapi import HTTPException
from starlette.requests import HTTPConnection

from ..api.deps import StoreD
from ..auth.user import resolve_org_id, resolve_user_id
from ..store import notebook_sessions as ns
from .constants import POD_PORT, SESSION_ID_PATTERN_STR
from .cookies import cookie_name

SESSION_ID_PATTERN = re.compile(SESSION_ID_PATTERN_STR)


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
    """
    import logging
    _log = logging.getLogger("notebook_proxy.auth")

    scope_type = getattr(connection, "scope", {}).get("type", "unknown")
    _log.info("resolve_proxy_session: session_id=%s scope=%s", session_id, scope_type)

    if not SESSION_ID_PATTERN.match(session_id):
        _log.warning("REJECT: session_id charset invalid: %s", session_id[:40])
        raise HTTPException(status_code=404, detail="Session not found")

    # Step 1: extract token from cookie, Authorization header, or query param.
    # Cookie is the primary auth mechanism (set by _init). Bearer token and
    # access_token query param are fallbacks for embedded notebook components
    # where cross-origin cookies are not available (e.g. WebSocket upgrades
    # through a frontend proxy that can't forward cookies).
    cookie_value = connection.cookies.get(cookie_name(session_id))
    if cookie_value is None:
        auth_header = connection.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            cookie_value = auth_header[7:]
        else:
            cookie_value = connection.query_params.get("access_token")
    if cookie_value is None:
        all_cookies = list(connection.cookies.keys())
        _log.warning("REJECT: no token found (cookie/header/query). cookies: %s", all_cookies)
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
        upstream_base = f"{direct_url.rstrip('/')}/notebook/{session_id}"
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
