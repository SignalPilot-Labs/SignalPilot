"""In-process async event bus — per-run asyncio.Queue registry.

Subscribers receive RunEventOut objects published after DB commit. In-memory only;
replaced by Redis/Postgres LISTEN in a later round.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from workspaces_api.schemas import RunEventOut

import uuid

logger = logging.getLogger(__name__)

_QUEUE_MAXSIZE = 256


class EventBus:
    """Per-run asyncio.Queue registry for SSE fan-out."""

    def __init__(self) -> None:
        self._queues: dict[uuid.UUID, list[asyncio.Queue[RunEventOut]]] = defaultdict(
            list
        )

    async def publish(self, run_id: uuid.UUID, event: RunEventOut) -> None:
        """Publish an event to all active subscribers for run_id."""
        queues = self._queues.get(run_id, [])
        for queue in queues:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(
                    "event_bus queue full for run_id=%s kind=%s — dropping frame",
                    run_id,
                    event.kind,
                )

    @asynccontextmanager
    async def subscribe(
        self, run_id: uuid.UUID
    ) -> AsyncIterator[asyncio.Queue[RunEventOut]]:
        """Context manager that registers and yields a per-run event queue."""
        queue: asyncio.Queue[RunEventOut] = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        self._queues[run_id].append(queue)
        try:
            yield queue
        finally:
            self._queues[run_id].remove(queue)
            if not self._queues[run_id]:
                del self._queues[run_id]
