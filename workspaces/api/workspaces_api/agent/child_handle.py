"""_ChildHandle dataclass — tracks a running sandbox subprocess.

Contains the asyncio Process, background tasks, workdir, and proxy lease.
Token masking: __repr__ never reveals the lease token.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from workspaces_api.agent.proxy_token_client import ProxyTokenLease

logger = logging.getLogger(__name__)

_TERM_GRACE_SECONDS = 5


@dataclass
class _ChildHandle:
    """Mutable handle for a running sandbox subprocess.

    Fields:
        proc: The asyncio subprocess.
        run_id: UUID of the associated run.
        workdir: Path to the run's working directory root.
        lease: ProxyTokenLease if a connector was specified, else None.
        stdout_task: Asyncio task pumping stdout.
        stderr_task: Asyncio task pumping stderr.
        watcher_task: Asyncio task awaiting process exit.
        started_at: UTC datetime when spawn was called.
    """

    proc: asyncio.subprocess.Process
    run_id: uuid.UUID
    workdir: Path
    lease: ProxyTokenLease | None
    stdout_task: asyncio.Task  # type: ignore[type-arg]
    stderr_task: asyncio.Task  # type: ignore[type-arg]
    watcher_task: asyncio.Task  # type: ignore[type-arg]
    started_at: datetime

    def __repr__(self) -> str:
        lease_repr = "ProxyTokenLease(token=***)" if self.lease else "None"
        return (
            f"_ChildHandle(run_id={self.run_id!r}, "
            f"pid={self.proc.pid!r}, "
            f"lease={lease_repr}, "
            f"started_at={self.started_at!r})"
        )

    async def terminate(self, grace_seconds: int = _TERM_GRACE_SECONDS) -> None:
        """Send SIGTERM, wait up to grace_seconds, then SIGKILL if still alive."""
        if self.proc.returncode is not None:
            return

        try:
            self.proc.send_signal(signal.SIGTERM)
        except ProcessLookupError:
            return

        try:
            await asyncio.wait_for(self.proc.wait(), timeout=grace_seconds)
        except TimeoutError:
            logger.warning(
                "child_handle SIGTERM timed out after %ds run_id=%s — sending SIGKILL",
                grace_seconds,
                self.run_id,
            )
            try:
                self.proc.send_signal(signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=3)
            except TimeoutError:
                logger.error(
                    "child_handle SIGKILL did not reap process run_id=%s pid=%s",
                    self.run_id,
                    self.proc.pid,
                )
