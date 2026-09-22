"""Per-path request body caps (plan section B, gateway half).

The runtime archive upload carries base64 fields whose schema allows about
47 MB, while the global cap stays at 2 MB. The middleware's path-prefix map is
what lets one endpoint accept its own limit without widening everything.
"""

from __future__ import annotations

import asyncio
from typing import Any

from gateway.http import RequestBodySizeLimitMiddleware
from gateway.main import BODY_SIZE_PATH_OVERRIDES, _runtime_archive_body_limit, app

GLOBAL_CAP = 2_097_152


def _scope(path: str, content_length: int, method: str = "POST") -> dict:
    return {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": b"",
        "headers": [(b"content-length", str(content_length).encode())],
    }


def _await(coro) -> None:
    # A private loop: asyncio.run() unsets the default loop, which breaks the
    # get_event_loop()-based tests in test_security_hardening when run after.
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(coro)
    finally:
        loop.close()


def _run(middleware, scope) -> int:
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    sent: list[dict[str, Any]] = []

    async def send(message):
        sent.append(message)

    _await(middleware(scope, receive, send))
    return next(m for m in sent if m["type"] == "http.response.start")["status"]


def _middleware(path_max_bytes: dict[str, int]) -> RequestBodySizeLimitMiddleware:
    async def downstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok", "more_body": False})

    return RequestBodySizeLimitMiddleware(downstream, max_body_bytes=GLOBAL_CAP, path_max_bytes=path_max_bytes)


class TestPathOverrideMap:
    def test_archive_limit_is_derived_from_the_schema(self):
        from gateway.api.chat_routes.runtime_archives import RuntimeArchiveCreate

        schema_total = 0
        for field in RuntimeArchiveCreate.model_fields.values():
            schema_total += max((getattr(m, "max_length", 0) or 0) for m in field.metadata)
        assert schema_total == (3 + 14 + 3 + 27) * 1024 * 1024
        assert _runtime_archive_body_limit() == schema_total + 64 * 1024
        assert BODY_SIZE_PATH_OVERRIDES["/api/chat/runtime-archives"] == _runtime_archive_body_limit()

    def test_archive_route_accepts_its_schema_limit_and_rejects_above(self):
        middleware = _middleware(BODY_SIZE_PATH_OVERRIDES)
        limit = BODY_SIZE_PATH_OVERRIDES["/api/chat/runtime-archives"]
        assert _run(middleware, _scope("/api/chat/runtime-archives", 27 * 1024 * 1024)) == 200
        assert _run(middleware, _scope("/api/chat/runtime-archives", limit)) == 200
        assert _run(middleware, _scope("/api/chat/runtime-archives", limit + 1)) == 413

    def test_other_chat_routes_keep_the_global_cap(self):
        middleware = _middleware(BODY_SIZE_PATH_OVERRIDES)
        assert _run(middleware, _scope("/api/chat/runs", GLOBAL_CAP + 1)) == 413
        assert _run(middleware, _scope("/api/chat/runtime-archive", GLOBAL_CAP + 1)) == 413
        assert _run(middleware, _scope("/api/query", GLOBAL_CAP)) == 200

    def test_chunked_body_uses_the_path_limit(self):
        middleware = _middleware({"/big": 10})

        async def downstream(scope, receive, send):
            while True:
                message = await receive()
                if message.get("type") == "http.disconnect" or not message.get("more_body", False):
                    break
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok", "more_body": False})

        middleware.app = downstream
        chunks = [b"x" * 6, b"x" * 6]

        async def receive():
            more = len(chunks) > 1
            return {"type": "http.request", "body": chunks.pop(0), "more_body": more}

        sent: list[dict[str, Any]] = []

        async def send(message):
            sent.append(message)

        scope = {"type": "http", "method": "POST", "path": "/big", "query_string": b"", "headers": []}
        _await(middleware(scope, receive, send))
        assert next(m for m in sent if m["type"] == "http.response.start")["status"] == 413


class TestAppWiring:
    def test_app_registers_the_override_map(self):
        entry = next(m for m in app.user_middleware if m.cls is RequestBodySizeLimitMiddleware)
        assert entry.kwargs["max_body_bytes"] == GLOBAL_CAP
        assert entry.kwargs["path_max_bytes"] is BODY_SIZE_PATH_OVERRIDES
