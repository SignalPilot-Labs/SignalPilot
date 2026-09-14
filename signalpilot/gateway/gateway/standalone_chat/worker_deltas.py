"""Coalesce streamed text and thinking deltas before they reach the database.

The model streams a chunk of a few characters at a time. Persisting every
chunk as its own run event costs a round trip set per chunk, which on a
remote database made the answer arrive at about one chunk per second. The
batcher merges consecutive deltas of the same type and parent into one event
and flushes it after a short window, when the buffer grows large, or before
any other event so ordering in the transcript is unchanged.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

DELTA_EVENT_TYPES = frozenset({"text_delta", "thinking_delta"})
FLUSH_INTERVAL_SECONDS = 0.15
FLUSH_MAX_CHARS = 2_000

Writer = Callable[[str, dict[str, Any]], Awaitable[None]]


class DeltaBatcher:
    """Buffers delta events for one run and writes them through ``writer``."""

    def __init__(self, writer: Writer) -> None:
        self._writer = writer
        self._pending_type: str | None = None
        self._pending_parent: str | None = None
        self._pending_text: list[str] = []
        self._pending_chars = 0
        self._timer: asyncio.Task[None] | None = None
        # _lock guards the buffer; _write_lock serializes writes so events
        # reach the store in order while intake continues during a write.
        self._lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()

    async def add(self, event_type: str, payload: dict[str, Any]) -> None:
        """Buffer one delta. A change of type or parent flushes the old run first."""
        delta = str(payload.get("delta") or "")
        parent = payload.get("parent_tool_call_id") or None
        if not delta:
            return
        if self._pending_type is not None and (
            event_type != self._pending_type or parent != self._pending_parent
        ):
            await self.flush()
        async with self._lock:
            self._pending_type = event_type
            self._pending_parent = parent
            self._pending_text.append(delta)
            self._pending_chars += len(delta)
            overflow = self._pending_chars >= FLUSH_MAX_CHARS
            if not overflow and (self._timer is None or self._timer.done()):
                self._timer = asyncio.create_task(self._flush_after_interval())
        if overflow:
            await self.flush()

    async def flush(self) -> None:
        """Write whatever is buffered. Call before any non-delta event.

        The buffer is swapped out under the buffer lock and written under
        the write lock, so new deltas keep accumulating while a write is in
        flight and writes still land in order.
        """
        async with self._write_lock:
            async with self._lock:
                staged = self._take_locked()
            if staged is not None:
                await self._writer(*staged)

    async def close(self) -> None:
        """Flush and stop the timer. The batcher must not be used afterwards."""
        await self.flush()
        if self._timer is not None and not self._timer.done():
            self._timer.cancel()
            try:
                await self._timer
            except asyncio.CancelledError:
                pass

    async def _flush_after_interval(self) -> None:
        """Timer flush. A write failure here has no caller to raise into, so
        it is logged; the chunk is dropped, and the run's final message still
        carries the full answer. Explicit ``flush`` calls raise as before."""
        await asyncio.sleep(FLUSH_INTERVAL_SECONDS)
        try:
            await self.flush()
        except Exception:
            logger.warning("Timed flush of streamed deltas failed", exc_info=True)

    def _take_locked(self) -> tuple[str, dict[str, Any]] | None:
        if self._pending_type is None:
            return None
        event_type = self._pending_type
        payload: dict[str, Any] = {"delta": "".join(self._pending_text)}
        if self._pending_parent:
            payload["parent_tool_call_id"] = self._pending_parent
        self._pending_type = None
        self._pending_parent = None
        self._pending_text = []
        self._pending_chars = 0
        return event_type, payload
