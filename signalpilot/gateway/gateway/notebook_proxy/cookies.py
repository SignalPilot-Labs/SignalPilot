"""Cookie helpers for the notebook proxy.

One cookie per session:  sp_nb_{session_id}
- HttpOnly, Secure (in cloud), SameSite=Lax
- Path=/notebook/{session_id}  — scoped tightly so the cookie is only sent on
  requests under that path prefix.
- Max-Age = JWT TTL (8 h default).

clear_proxy_cookie emits a Max-Age=0 clear-header with the SAME Path= as the
original cookie.  This is necessary even when the delete request comes from
/api/notebook-sessions/{id} (a different URL path) — browsers match the cookie
to clear using the Path= attribute value, not the response URL.
Never call Response.delete_cookie(name) without an explicit path= argument:
Starlette's default is Path=/ which will NOT match our /notebook/{sid} cookie.
"""

from __future__ import annotations

import re

from fastapi import HTTPException, Response

from .constants import COOKIE_NAME_PREFIX, SESSION_ID_PATTERN_STR

# Defense-in-depth: validate session_id in all cookie helpers.
# This is the same pattern enforced by resolve_proxy_session.
_SESSION_ID_PATTERN = re.compile(SESSION_ID_PATTERN_STR)


def _validate_session_id(session_id: str) -> None:
    """Raise 404 if session_id contains characters unsafe for cookie attributes.

    Prevents CR/LF/semicolon injection into Set-Cookie Path= values.
    session_id should already be validated by the caller (resolve_proxy_session
    or the API endpoint), but this is defense in depth.
    """
    if not _SESSION_ID_PATTERN.match(session_id):
        raise HTTPException(status_code=404, detail="Session not found")


def cookie_name(session_id: str) -> str:
    """Return the cookie name for a session.  session_id is pre-validated."""
    return f"{COOKIE_NAME_PREFIX}{session_id}"


def set_proxy_cookie(
    response: Response,
    *,
    session_id: str,
    token: str,
    secure: bool,
    max_age: int,
) -> None:
    """Set the HttpOnly proxy cookie on response.

    secure: pass is_cloud_mode() so the helper remains test-friendly without
            importing runtime.mode.
    max_age: sp_session_jwt_ttl_seconds (caller reads from K8sSettings).
    """
    _validate_session_id(session_id)
    response.set_cookie(
        key=cookie_name(session_id),
        value=token,
        httponly=True,
        secure=secure,
        samesite="lax",
        path=f"/notebook/{session_id}",
        max_age=max_age,
    )


def clear_proxy_cookie(
    response: Response,
    *,
    session_id: str,
    secure: bool,
) -> None:
    """Emit a Set-Cookie header that clears the proxy cookie.

    Path MUST be /notebook/{session_id} even when this response is served from
    /api/notebook-sessions/{id} — browsers require the clear-header's Path= to
    match the original cookie's Path= exactly.

    M-4: Validates session_id against SESSION_ID_PATTERN before interpolating
    into the Set-Cookie Path= attribute (defense in depth against header injection).
    """
    _validate_session_id(session_id)
    response.set_cookie(
        key=cookie_name(session_id),
        value="",
        httponly=True,
        secure=secure,
        samesite="lax",
        path=f"/notebook/{session_id}",
        max_age=0,
    )
