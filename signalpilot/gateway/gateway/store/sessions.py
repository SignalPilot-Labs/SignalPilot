"""In-memory kernel session registry (org-scoped, ephemeral)."""

from __future__ import annotations

from gateway.models.sessions import SessionInfoResponse

_active_sessions: dict[str, SessionInfoResponse] = {}


def list_sessions(org_id: str) -> list[SessionInfoResponse]:
    return [s for s in _active_sessions.values() if s.org_id == org_id]


def get_session(session_id: str, org_id: str) -> SessionInfoResponse | None:
    s = _active_sessions.get(session_id)
    if s is None or s.org_id != org_id:
        return None
    return s


def upsert_session(session: SessionInfoResponse) -> None:
    _active_sessions[session.id] = session


def delete_session(session_id: str, org_id: str) -> bool:
    s = _active_sessions.get(session_id)
    if s is None or s.org_id != org_id:
        return False
    del _active_sessions[session_id]
    return True
