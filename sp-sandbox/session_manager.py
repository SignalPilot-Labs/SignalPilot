"""KernelSessionManager — pool of kernel sessions with idle reaper."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import time
import uuid
from pathlib import Path

from constants import KERNEL_IDLE_TIMEOUT, MAX_SESSIONS
from kernel_session import KernelSession
from models import SessionInfo

logger = logging.getLogger(__name__)


class KernelSessionManager:
    """Manages a pool of stateful kernel sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, KernelSession] = {}
        self._reaper_task: asyncio.Task | None = None

    async def start(self) -> None:
        self._reaper_task = asyncio.create_task(self._idle_reaper())
        logger.info(
            "session manager started (max=%d, idle_timeout=%ds)",
            MAX_SESSIONS, KERNEL_IDLE_TIMEOUT,
        )

    async def create_session(
        self,
        session_id: str | None = None,
        session_token: str | None = None,
        gateway_url: str | None = None,
    ) -> KernelSession:
        if len(self._sessions) >= MAX_SESSIONS:
            raise RuntimeError(f"Max sessions ({MAX_SESSIONS}) reached")

        if session_id is None:
            session_id = str(uuid.uuid4())

        workdir = Path(tempfile.mkdtemp(prefix=f"sp-kernel-{session_id[:8]}-"))
        try:
            os.chown(workdir, 65534, 65534)
        except (PermissionError, OSError):
            pass

        session = KernelSession(session_id, workdir)
        await session.start()

        gw = gateway_url or os.environ.get("SP_GATEWAY_URL")
        if session_token and gw:
            bootstrap = (
                f"import sp\n"
                f"sp.init(gateway_url={gw!r}, session_token={session_token!r})\n"
                f"get_ipython().run_line_magic('matplotlib', 'inline')"
            )
            try:
                await session.inject_bootstrap(bootstrap)
            except RuntimeError:
                logger.warning("sp helper injection failed for session %s", session_id[:8])

        self._sessions[session_id] = session
        logger.info("session %s created (%d/%d)", session_id[:8], len(self._sessions), MAX_SESSIONS)
        return session

    def get_session(self, session_id: str) -> KernelSession | None:
        return self._sessions.get(session_id)

    def list_sessions(self) -> list[SessionInfo]:
        return [
            SessionInfo(
                id=s.id,
                status=s.status,
                created_at=s.created_at,
                last_active=s.last_active,
                cell_count=s.cell_count,
            )
            for s in self._sessions.values()
        ]

    async def delete_session(self, session_id: str) -> bool:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return False
        await session.kill()
        logger.info("session %s deleted (%d/%d)", session_id[:8], len(self._sessions), MAX_SESSIONS)
        return True

    async def restart_session(
        self,
        session_id: str,
        session_token: str | None = None,
        gateway_url: str | None = None,
    ) -> KernelSession:
        old = self._sessions.pop(session_id, None)
        if old:
            await old.kill()
        return await self.create_session(
            session_id=session_id,
            session_token=session_token,
            gateway_url=gateway_url,
        )

    async def _idle_reaper(self) -> None:
        while True:
            await asyncio.sleep(60)
            now = time.time()
            to_kill = [
                sid for sid, s in self._sessions.items()
                if now - s.last_active > KERNEL_IDLE_TIMEOUT
                and s.status in ("idle", "dead")
            ]
            for sid in to_kill:
                logger.info("reaping idle session %s", sid[:8])
                await self.delete_session(sid)

    async def cleanup(self) -> None:
        if self._reaper_task:
            self._reaper_task.cancel()
        for sid in list(self._sessions):
            await self.delete_session(sid)
