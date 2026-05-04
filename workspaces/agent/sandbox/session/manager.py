"""SessionManager — registry for active Claude SDK sessions.

Thin coordinator that creates, looks up, and tears down Session instances.
The actual SDK lifecycle lives in session.session.Session.
"""

import asyncio
import logging
import uuid

from constants import MAX_CONCURRENT_SESSIONS
from session.session import Session

log = logging.getLogger("sandbox.session_manager")


class SessionManager:
    """Manages active Claude SDK sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def active_count(self) -> int:
        """Return the number of currently active sessions."""
        return len(self._sessions)

    async def start(self, options_dict: dict) -> str:
        """Start a new Claude SDK session. Returns session_id."""
        if len(self._sessions) >= MAX_CONCURRENT_SESSIONS:
            raise RuntimeError(f"Max sessions ({MAX_CONCURRENT_SESSIONS}) reached")
        session_id = uuid.uuid4().hex[:12]
        session = Session(session_id, options_dict)
        self._sessions[session_id] = session
        session.task = asyncio.create_task(session.run())
        log.info("Session %s started", session_id)
        return session_id

    def get_event_queue(self, session_id: str) -> asyncio.Queue:
        """Get the event queue for SSE streaming."""
        return self._get(session_id).events

    async def send_message(self, session_id: str, text: str) -> None:
        """Send a follow-up query to the session."""
        s = self._get(session_id)
        if s.client:
            await s.client.query(text)

    async def interrupt(self, session_id: str) -> None:
        """Interrupt the current response."""
        s = self._get(session_id)
        if s.client:
            await s.client.interrupt()

    async def stop(self, session_id: str) -> None:
        """Stop a session and clean up."""
        session = self._sessions.pop(session_id, None)
        if session and session.task:
            session.task.cancel()

    def unlock(self, session_id: str) -> None:
        """Force-unlock a session's time gate."""
        self._get(session_id).unlocked = True

    async def stop_all(self) -> None:
        """Stop all active sessions."""
        for sid in list(self._sessions.keys()):
            await self.stop(sid)

    def _get(self, session_id: str) -> Session:
        """Look up a session by ID."""
        session = self._sessions.get(session_id)
        if not session:
            raise RuntimeError(f"Session {session_id} not found")
        return session
