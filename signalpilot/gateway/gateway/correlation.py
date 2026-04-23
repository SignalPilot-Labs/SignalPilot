"""
Request Correlation ID middleware — raw ASGI, matches RequestBodySizeLimitMiddleware pattern.

On every HTTP request:
  - Checks for X-Request-ID header.
  - If present and valid (1-64 chars, alphanumeric + hyphens), uses it.
  - Otherwise generates a new uuid4.
  - Stores correlation ID on scope["state"]["request_id"] for downstream access.
  - Injects X-Request-ID into the response via wrapped send callable.
"""

from __future__ import annotations

import re
import time
import uuid
from fastapi import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_REQUEST_ID_PATTERN = re.compile(r"[a-zA-Z0-9\-]{1,64}")


def _validate_request_id(value: str) -> bool:
    """Return True if value matches the strict request ID format."""
    return bool(_REQUEST_ID_PATTERN.fullmatch(value))


def _generate_request_id() -> str:
    """Generate a new UUID4 request ID. Falls back to timestamp on failure."""
    try:
        return str(uuid.uuid4())
    except Exception:
        return f"unknown-{int(time.time())}"


def get_request_id(request: Request) -> str | None:
    """Extract the correlation ID from request.state, or None if not set."""
    return getattr(request.state, "request_id", None)


class RequestCorrelationMiddleware:
    """Raw ASGI middleware that assigns a correlation ID to every HTTP request.

    Accepts a client-provided X-Request-ID only if it passes strict format
    validation (1-64 chars, alphanumeric + hyphens). Rejects anything else
    to prevent header injection. Generates a new UUID4 when not provided or
    when the client-supplied value is invalid.

    The ID is stored on scope["state"]["request_id"] and echoed back in the
    X-Request-ID response header.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers: dict[bytes, bytes] = dict(scope.get("headers", []))
        raw_id = headers.get(b"x-request-id", b"").decode("latin-1", errors="replace").strip()

        if raw_id and _validate_request_id(raw_id):
            correlation_id = raw_id
        else:
            correlation_id = _generate_request_id()

        # Ensure state dict exists on scope before storing
        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["request_id"] = correlation_id

        encoded_id = correlation_id.encode("latin-1")

        async def sending_with_id(message: Message) -> None:
            if message.get("type") == "http.response.start":
                existing_headers: list[tuple[bytes, bytes]] = list(message.get("headers", []))
                # Only inject if not already present (downstream may have set it)
                has_id = any(k.lower() == b"x-request-id" for k, _ in existing_headers)
                if not has_id:
                    existing_headers.append((b"x-request-id", encoded_id))
                message = dict(message)
                message["headers"] = existing_headers
            await send(message)

        await self.app(scope, receive, sending_with_id)
