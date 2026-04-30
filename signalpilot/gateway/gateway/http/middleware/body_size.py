"""
Request body size limiting middleware.
"""

from __future__ import annotations

import json
from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

_MAX_BODY_BYTES_DEFAULT = 2_097_152  # 2MB


class RequestBodySizeLimitMiddleware:
    """Reject requests whose body exceeds max_body_bytes with HTTP 413.

    This is implemented as a raw ASGI middleware (not BaseHTTPMiddleware)
    because BaseHTTPMiddleware buffers the entire request body into memory
    when calling call_next(), which defeats the purpose of streaming byte
    counting for chunked transfers. Raw ASGI lets us wrap the receive callable
    to count bytes incrementally and abort before the app reads the body.

    For requests with Content-Length present: reject immediately with 413
    without reading any body bytes.
    For chunked/streaming bodies without Content-Length: wrap the receive
    callable and count cumulative body bytes, rejecting when the limit is hit.
    """

    def __init__(self, app: ASGIApp, max_body_bytes: int = _MAX_BODY_BYTES_DEFAULT) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")
        if method in ("GET", "OPTIONS", "HEAD"):
            await self.app(scope, receive, send)
            return

        # Check Content-Length header for early rejection
        headers: dict[bytes, bytes] = dict(scope.get("headers", []))
        content_length_raw = headers.get(b"content-length")
        if content_length_raw is not None:
            try:
                content_length = int(content_length_raw)
            except ValueError:
                # Unparseable Content-Length — reject as malformed
                await self._send_413(send)
                return
            if content_length > self.max_body_bytes:
                await self._send_413(send)
                return

        # Wrap receive to count bytes for chunked/streaming bodies.
        # Track whether the app has started sending a response — if it has,
        # we cannot send a 413 (ASGI protocol violation: duplicate response.start).
        bytes_received: list[int] = [0]
        response_started: list[bool] = [False]

        async def counting_receive() -> Any:
            message = await receive()
            if message.get("type") == "http.request":
                chunk = message.get("body", b"")
                bytes_received[0] += len(chunk)
                if bytes_received[0] > self.max_body_bytes and not response_started[0]:
                    await self._send_413(send)
                    return {"type": "http.disconnect"}
            return message

        async def tracking_send(message: dict) -> None:
            if message.get("type") == "http.response.start":
                response_started[0] = True
            await send(message)

        await self.app(scope, counting_receive, tracking_send)

    async def _send_413(self, send: Send) -> None:
        body = json.dumps({"detail": "Request body too large."}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": body,
                "more_body": False,
            }
        )
