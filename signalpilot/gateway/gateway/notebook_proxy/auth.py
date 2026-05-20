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
    store: StoreD,
) -> ProxySession:
    """FastAPI dependency: authenticate and resolve a notebook proxy request.

    Uses HTTPConnection (not Request) so this dependency works for both HTTP
    routes and WebSocket routes — WebSocket is an HTTPConnection subclass but
    NOT a Request. FastAPI will not inject a Request into a WS handler dependency.

    Does NOT use RequireScope — see module docstring for rationale.
    """
    # Step 1: charset validation before session_id reaches any cookie/header construction.
    if not SESSION_ID_PATTERN.match(session_id):
        raise HTTPException(status_code=404, detail="Session not found")

    # Steps 2–3: existing auth deps give us user_id and org_id.
    user_id = await resolve_user_id(connection)
    org_id = await resolve_org_id(connection, user_id)

    # Step 3: load internal session (includes real access_token).
    session = await ns.get_session_internal(
        store.session, session_id=session_id, org_id=org_id
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Step 4: ownership check — 404 to avoid existence oracle for same-org non-owners.
    if session.user_id != user_id:
        raise HTTPException(status_code=404, detail="Session not found")

    # Step 5: readiness check.
    if session.status != "running" or not session.pod_ip_internal:
        raise HTTPException(status_code=409, detail="Session not ready")

    # Step 6: cookie presence and constant-time comparison.
    cookie_value = connection.cookies.get(cookie_name(session_id))
    if cookie_value is None:
        raise HTTPException(
            status_code=401,
            detail="Cookie missing; re-init session",
            headers={"WWW-Authenticate": "SP-Notebook-Init"},
        )
    if not secrets.compare_digest(cookie_value, session.access_token or ""):
        raise HTTPException(status_code=401, detail="Session token mismatch")

    upstream_base = f"http://{session.pod_ip_internal}:{POD_PORT}"
    return ProxySession(
        session_id=session_id,
        user_id=user_id,
        org_id=org_id,
        upstream_base=upstream_base,
        proxy_cookie_token=cookie_value,
    )
