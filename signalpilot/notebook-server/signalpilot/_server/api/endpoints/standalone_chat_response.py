"""Streaming response configuration for chat event delivery."""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.responses import StreamingResponse

if TYPE_CHECKING:
    from collections.abc import AsyncIterable


def stream_response(events: AsyncIterable[bytes]) -> StreamingResponse:
    """Prevent intermediary proxies from buffering newline-delimited events."""
    return StreamingResponse(
        events,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
