"""MCP server API key authentication.

Provides:
- FIFO+TTL cache for validated API key results
- Async validate function using a shared httpx client
- Pure ASGI middleware for MCP streamable-http auth

Local/dev mode: if SP_BACKEND_URL is not set, all requests pass through.
Cloud mode: SP_BACKEND_URL set -> every request requires a valid sp_ key.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Any, Callable

import httpx

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

_CACHE_TTL_SECONDS: int = 300  # 5 minutes
_CACHE_MAX_ENTRIES: int = 256
_HTTP_TIMEOUT_SECONDS: float = 5.0
_VALIDATE_PATH: str = "/api/v1/keys/validate"
_BEARER_PREFIX: str = "Bearer "

# ─── HTTP client singleton ─────────────────────────────────────────────────────

_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    """Return the shared httpx client, initializing it on first call."""
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS)
    return _http_client


# ─── FIFO + TTL cache ─────────────────────────────────────────────────────────

class _KeyCache:
    """FIFO + TTL cache for API key validation results.

    Key: SHA-256 hex digest of the raw API key (never stores raw keys).
    Value: dict returned from the backend validate endpoint.
    Eviction: FIFO on overflow, TTL expiry on reads.
    """

    def __init__(self) -> None:
        # Ordered by insertion: list of key_hashes in insertion order
        self._order: list[str] = []
        # key_hash -> (result_dict, inserted_at_monotonic)
        self._store: dict[str, tuple[dict[str, Any], float]] = {}

    def get(self, key_hash: str) -> dict[str, Any] | None:
        """Return cached result or None if missing or expired."""
        entry = self._store.get(key_hash)
        if entry is None:
            return None
        result, inserted_at = entry
        if time.monotonic() - inserted_at > _CACHE_TTL_SECONDS:
            # Expired — remove from store (order list cleaned lazily on put)
            del self._store[key_hash]
            return None
        return result

    def put(self, key_hash: str, result: dict[str, Any]) -> None:
        """Insert result into cache. Evicts oldest entry on overflow (FIFO)."""
        # Remove existing entry from order list to prevent unbounded growth
        if key_hash in self._store:
            try:
                self._order.remove(key_hash)
            except ValueError:
                pass
        elif len(self._store) >= _CACHE_MAX_ENTRIES:
            # Evict oldest entry
            while self._order:
                oldest = self._order.pop(0)
                if oldest in self._store:
                    del self._store[oldest]
                    break
        self._store[key_hash] = (result, time.monotonic())
        self._order.append(key_hash)


_cache = _KeyCache()


# ─── Key validation ───────────────────────────────────────────────────────────

async def validate_api_key(key: str, backend_url: str) -> dict[str, Any] | None:
    """Validate an API key against the backend.

    Checks the in-process cache first. On a cache miss, calls
    POST {backend_url}/api/v1/keys/validate. Caches and returns the
    result dict on success, or None on 401 / network error (fail closed).

    Never logs the raw key value.
    """
    key_hash = hashlib.sha256(key.encode()).hexdigest()

    cached = _cache.get(key_hash)
    if cached is not None:
        return cached

    client = _get_http_client()
    url = f"{backend_url.rstrip('/')}{_VALIDATE_PATH}"
    try:
        response = await client.post(url, json={"key": key})
    except httpx.HTTPError as exc:
        logger.warning("MCP auth: network error contacting backend: %s", exc)
        return None

    if response.status_code == 200:
        result: dict[str, Any] = response.json()
        _cache.put(key_hash, result)
        logger.debug(
            "MCP auth: key validated (key_id=%s key_name=%s)",
            result.get("key_id"),
            result.get("key_name"),
        )
        return result

    if response.status_code == 401:
        logger.debug("MCP auth: backend rejected key (401)")
        return None

    logger.warning(
        "MCP auth: unexpected backend status %d — failing closed",
        response.status_code,
    )
    return None


# ─── ASGI middleware ──────────────────────────────────────────────────────────

_warned_no_backend_url: bool = False


class MCPAuthMiddleware:
    """Pure ASGI middleware that authenticates MCP streamable-http requests.

    Uses pure ASGI (not BaseHTTPMiddleware) to remain compatible with
    streaming responses returned by the MCP Starlette app.

    Auth flow:
    - SP_BACKEND_URL unset -> pass through (local/dev mode). Logs warning once.
    - SP_BACKEND_URL set:
        - Extract Authorization: Bearer <key> header.
        - Validate key via backend (cache-first).
        - On success: set scope["state"]["auth"] and call wrapped app.
        - On failure: return 401 JSON immediately.
    """

    def __init__(self, app: Callable) -> None:
        self._app = app

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable,
        send: Callable,
    ) -> None:
        # Only intercept HTTP connections (not lifespan/websocket)
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        backend_url = os.environ.get("SP_BACKEND_URL")
        # Only use backend-based auth in cloud mode. In local mode, fall through
        # to the local key check (or pass-through if no keys exist).
        is_cloud = (
            backend_url
            and os.environ.get("SP_DEPLOYMENT_MODE", "local") == "cloud"
        )

        if is_cloud:
            # Cloud mode: validate against backend
            raw_key = _extract_bearer_key(scope)
            if not raw_key:
                raw_key = _extract_api_key_header(scope)
            if not raw_key:
                await _send_401(send, "Authentication required. Provide API key via Authorization: Bearer <key> or X-API-Key header.")
                return

            auth_info = await validate_api_key(raw_key, backend_url)
            if auth_info is None:
                await _send_401(send, "Invalid or expired API key.")
                return

            if not auth_info.get("org_id"):
                await _send_401(send, "API key is not bound to an organization.")
                return

            if "state" not in scope:
                scope["state"] = {}
            scope["state"]["auth"] = auth_info
            # Set context variables so MCP tools can access the user_id and org_id
            from .mcp_server import mcp_user_id_var, mcp_org_id_var
            mcp_user_id_var.set(auth_info.get("user_id"))
            mcp_org_id_var.set(auth_info.get("org_id"))
            await self._app(scope, receive, send)
            return

        # Local mode: validate against user-created gateway keys (DB-backed)
        from .db.engine import get_session_factory
        from .mcp_server import mcp_user_id_var, mcp_org_id_var
        from .store import Store
        from sqlalchemy.exc import SQLAlchemyError

        try:
            factory = get_session_factory()
            async with factory() as session:
                store = Store(session, allow_unscoped=True)  # No org filter for key lookup

                keys = await store.list_api_keys()
                has_user_keys = len(keys) > 0

                if not has_user_keys:
                    global _warned_no_backend_url
                    if not _warned_no_backend_url:
                        logger.info(
                            "MCP auth: no API keys configured — MCP accepts all connections. "
                            "Create an API key in settings to require authentication."
                        )
                        _warned_no_backend_url = True
                    # Set user_id and org_id to "local" so MCP tools can access the store
                    mcp_user_id_var.set("local")
                    mcp_org_id_var.set("local")
                    if "state" not in scope:
                        scope["state"] = {}
                    scope["state"]["auth"] = {"user_id": "local", "org_id": "local"}
                    await self._app(scope, receive, send)
                    return

                raw_key = _extract_bearer_key(scope)
                if not raw_key:
                    raw_key = _extract_api_key_header(scope)
                if not raw_key:
                    await _send_401(send, "Authentication required. Provide API key via X-API-Key header.")
                    return

                matched = await store.validate_stored_api_key(raw_key)
                if matched is None:
                    await _send_401(send, "Invalid API key.")
                    return

                if "state" not in scope:
                    scope["state"] = {}
                scope["state"]["auth"] = {
                    "key_id": matched.id,
                    "key_name": matched.name,
                    "user_id": matched.user_id or "local",
                    "org_id": "local",  # clamp: matched.org_id may be stale cloud data
                }
                # Set user_id and org_id context vars for MCP store access
                mcp_user_id_var.set(matched.user_id or "local")
                mcp_org_id_var.set("local")
                await self._app(scope, receive, send)
        except (SQLAlchemyError, ValueError) as e:
            logger.error("MCP auth: DB error in local validation: %s", e)
            await _send_503(send, "Authentication service unavailable. Please try again.")


def _extract_bearer_key(scope: dict[str, Any]) -> str | None:
    """Extract the raw API key from the Authorization: Bearer header."""
    headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
    for name, value in headers:
        if name.lower() == b"authorization":
            decoded = value.decode("latin-1")
            if decoded.startswith(_BEARER_PREFIX):
                return decoded[len(_BEARER_PREFIX):].strip()
    return None


def _extract_api_key_header(scope: dict[str, Any]) -> str | None:
    """Extract the raw API key from the X-API-Key header."""
    headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
    for name, value in headers:
        if name.lower() == b"x-api-key":
            return value.decode("latin-1").strip()
    return None


async def _send_401(send: Callable, message: str) -> None:
    """Send a minimal 401 JSON response through the ASGI send callable."""
    body = json.dumps({"detail": message}).encode()
    await send({
        "type": "http.response.start",
        "status": 401,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
    })
    await send({
        "type": "http.response.body",
        "body": body,
        "more_body": False,
    })


async def _send_503(send: Callable, message: str) -> None:
    """Send a minimal 503 JSON response through the ASGI send callable."""
    body = json.dumps({"detail": message}).encode()
    await send({
        "type": "http.response.start",
        "status": 503,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
    })
    await send({
        "type": "http.response.body",
        "body": body,
        "more_body": False,
    })
