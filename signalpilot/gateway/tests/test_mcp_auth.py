"""Tests for MCP API key authentication — cache, validate, middleware."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from gateway.mcp_auth import (
    MCPAuthMiddleware,
    _KeyCache,
    _extract_bearer_key,
    validate_api_key,
)


# ─── TestKeyCache ─────────────────────────────────────────────────────────────


class TestKeyCache:
    """Tests for the FIFO+TTL in-process cache."""

    def test_put_and_get_returns_result(self):
        cache = _KeyCache()
        cache.put("abc123", {"user_id": "u1", "scopes": []})
        result = cache.get("abc123")
        assert result == {"user_id": "u1", "scopes": []}

    def test_miss_returns_none(self):
        cache = _KeyCache()
        assert cache.get("nonexistent") is None

    def test_ttl_expiry_returns_none(self):
        cache = _KeyCache()
        cache.put("abc123", {"user_id": "u1"})
        # Backdate the insertion time to simulate expiry
        old_result, _ = cache._store["abc123"]
        cache._store["abc123"] = (old_result, time.monotonic() - 400)
        assert cache.get("abc123") is None

    def test_ttl_not_expired_returns_result(self):
        cache = _KeyCache()
        cache.put("abc123", {"user_id": "u1"})
        # Entry just inserted, should still be valid
        assert cache.get("abc123") is not None

    def test_fifo_eviction_on_overflow(self):
        cache = _KeyCache()
        # Fill to max (256 entries)
        for i in range(256):
            cache.put(f"key{i}", {"user_id": f"u{i}"})

        # First entry should still be present (not yet evicted)
        assert cache.get("key0") is not None

        # Adding one more should evict the oldest (key0)
        cache.put("key_overflow", {"user_id": "overflow"})
        assert cache.get("key0") is None
        assert cache.get("key_overflow") is not None

    def test_fifo_preserves_insertion_order(self):
        cache = _KeyCache()
        for i in range(256):
            cache.put(f"key{i}", {"user_id": f"u{i}"})

        # Overflow evicts key0 (oldest), not key255 (newest)
        cache.put("newest", {"user_id": "newest"})
        assert cache.get("key0") is None
        assert cache.get("key255") is not None

    def test_expired_entry_removed_from_store(self):
        cache = _KeyCache()
        cache.put("k", {"user_id": "u"})
        old_result, _ = cache._store["k"]
        cache._store["k"] = (old_result, time.monotonic() - 400)
        cache.get("k")  # triggers removal
        assert "k" not in cache._store


# ─── TestValidateApiKey ───────────────────────────────────────────────────────


class TestValidateApiKey:
    """Tests for the async validate_api_key function."""

    @pytest.mark.asyncio
    async def test_200_success_returns_dict_and_caches(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "user_id": "u1",
            "scopes": ["read"],
            "key_id": "kid1",
            "key_name": "my-key",
        }
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        import gateway.mcp_auth as mcp_auth
        # Reset module-level cache and client
        original_client = mcp_auth._http_client
        original_cache = mcp_auth._cache
        mcp_auth._http_client = mock_client
        mcp_auth._cache = _KeyCache()
        try:
            result = await validate_api_key("sp_testkey123", "http://backend")
            assert result is not None
            assert result["user_id"] == "u1"
            mock_client.post.assert_called_once()
        finally:
            mcp_auth._http_client = original_client
            mcp_auth._cache = original_cache

    @pytest.mark.asyncio
    async def test_401_returns_none(self):
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        import gateway.mcp_auth as mcp_auth
        original_client = mcp_auth._http_client
        mcp_auth._http_client = mock_client
        try:
            result = await validate_api_key("sp_badkey", "http://backend")
            assert result is None
        finally:
            mcp_auth._http_client = original_client

    @pytest.mark.asyncio
    async def test_network_error_returns_none_fail_closed(self):
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError("connection refused")

        import gateway.mcp_auth as mcp_auth
        original_client = mcp_auth._http_client
        mcp_auth._http_client = mock_client
        try:
            result = await validate_api_key("sp_testkey", "http://backend")
            assert result is None
        finally:
            mcp_auth._http_client = original_client

    @pytest.mark.asyncio
    async def test_cache_hit_skips_http_call(self):
        mock_client = AsyncMock()

        import gateway.mcp_auth as mcp_auth
        original_client = mcp_auth._http_client
        original_cache = mcp_auth._cache
        mcp_auth._http_client = mock_client

        fresh_cache = _KeyCache()
        key = "sp_cachedkey"
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        cached_data = {"user_id": "u_cached", "scopes": [], "key_id": "kid", "key_name": "k"}
        fresh_cache.put(key_hash, cached_data)
        mcp_auth._cache = fresh_cache

        try:
            result = await validate_api_key(key, "http://backend")
            assert result == cached_data
            mock_client.post.assert_not_called()
        finally:
            mcp_auth._http_client = original_client
            mcp_auth._cache = original_cache

    @pytest.mark.asyncio
    async def test_cache_key_is_sha256_not_raw(self):
        """Verify the cache stores the key hash, not the raw key."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "user_id": "u1", "scopes": [], "key_id": "k1", "key_name": "n"
        }
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        import gateway.mcp_auth as mcp_auth
        original_client = mcp_auth._http_client
        original_cache = mcp_auth._cache
        mcp_auth._http_client = mock_client
        mcp_auth._cache = _KeyCache()

        raw_key = "sp_rawkey12345"
        try:
            await validate_api_key(raw_key, "http://backend")
            expected_hash = hashlib.sha256(raw_key.encode()).hexdigest()
            # Cache must use hash, not raw key
            assert expected_hash in mcp_auth._cache._store
            assert raw_key not in mcp_auth._cache._store
        finally:
            mcp_auth._http_client = original_client
            mcp_auth._cache = original_cache


# ─── TestMCPAuthMiddleware ────────────────────────────────────────────────────


def _make_scope(headers: list[tuple[bytes, bytes]] | None = None) -> dict[str, Any]:
    """Build a minimal ASGI HTTP scope."""
    return {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": headers or [],
    }


def _bearer_headers(key: str) -> list[tuple[bytes, bytes]]:
    return [(b"authorization", f"Bearer {key}".encode())]


async def _collect_response(middleware: MCPAuthMiddleware, scope: dict) -> dict:
    """Run the middleware and collect status + body from ASGI send calls."""
    received: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(event: dict):
        received.append(event)

    await middleware(scope, receive, send)
    start = next((e for e in received if e["type"] == "http.response.start"), None)
    body_event = next((e for e in received if e["type"] == "http.response.body"), None)
    return {
        "status": start["status"] if start else None,
        "body": json.loads(body_event["body"]) if body_event and body_event.get("body") else None,
    }


class TestMCPAuthMiddleware:
    """Tests for the pure ASGI MCPAuthMiddleware."""

    @pytest.mark.asyncio
    async def test_db_error_returns_503_not_401(self):
        """When the DB is unavailable during local auth, return 503 (not 401).

        A DB error is a server-side fault, not an auth failure. Returning 401
        would confuse clients into rotating valid keys unnecessarily.
        """
        downstream_called = False

        async def downstream_app(scope, receive, send):
            nonlocal downstream_called
            downstream_called = True
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}", "more_body": False})

        middleware = MCPAuthMiddleware(downstream_app)
        scope = _make_scope()

        import gateway.mcp_auth as mcp_auth
        original_warned = mcp_auth._warned_no_backend_url
        mcp_auth._warned_no_backend_url = False

        with patch.dict("os.environ", {}, clear=True):
            # Ensure SP_BACKEND_URL is absent so DB session factory raises
            import os
            os.environ.pop("SP_BACKEND_URL", None)
            response = await _collect_response(middleware, scope)

        mcp_auth._warned_no_backend_url = original_warned
        # DB errors must return 503 (service unavailable), not 401 (auth failure)
        assert downstream_called is False
        assert response["status"] == 503
        assert "service unavailable" in response["body"]["detail"].lower()

    @pytest.mark.asyncio
    async def test_valid_key_passes_through_and_sets_auth(self):
        auth_info = {"user_id": "u1", "scopes": ["read"], "key_id": "k1", "key_name": "n", "org_id": "org-1"}
        captured_scope: dict = {}

        async def downstream_app(scope, receive, send):
            captured_scope.update(scope)
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}", "more_body": False})

        middleware = MCPAuthMiddleware(downstream_app)
        scope = _make_scope(headers=_bearer_headers("sp_validkey123"))

        with patch("gateway.mcp_auth.validate_api_key", new=AsyncMock(return_value=auth_info)):
            with patch.dict("os.environ", {"SP_BACKEND_URL": "http://backend", "SP_DEPLOYMENT_MODE": "cloud"}):
                response = await _collect_response(middleware, scope)

        assert response["status"] == 200
        assert captured_scope.get("state", {}).get("auth") == auth_info

    @pytest.mark.asyncio
    async def test_invalid_key_returns_401(self):
        async def downstream_app(scope, receive, send):
            pytest.fail("Should not reach downstream app with invalid key")

        middleware = MCPAuthMiddleware(downstream_app)
        scope = _make_scope(headers=_bearer_headers("sp_badkey"))

        with patch("gateway.mcp_auth.validate_api_key", new=AsyncMock(return_value=None)):
            with patch.dict("os.environ", {"SP_BACKEND_URL": "http://backend", "SP_DEPLOYMENT_MODE": "cloud"}):
                response = await _collect_response(middleware, scope)

        assert response["status"] == 401
        assert "detail" in response["body"]

    @pytest.mark.asyncio
    async def test_missing_authorization_header_returns_401(self):
        async def downstream_app(scope, receive, send):
            pytest.fail("Should not reach downstream app without Authorization header")

        middleware = MCPAuthMiddleware(downstream_app)
        scope = _make_scope(headers=[])  # no Authorization header

        with patch.dict("os.environ", {"SP_BACKEND_URL": "http://backend", "SP_DEPLOYMENT_MODE": "cloud"}):
            response = await _collect_response(middleware, scope)

        assert response["status"] == 401
        assert "detail" in response["body"]

    @pytest.mark.asyncio
    async def test_non_http_scope_passes_through(self):
        """Lifespan and other non-http scope types should pass through unmodified."""
        downstream_called = False

        async def downstream_app(scope, receive, send):
            nonlocal downstream_called
            downstream_called = True

        middleware = MCPAuthMiddleware(downstream_app)
        scope = {"type": "lifespan"}

        with patch.dict("os.environ", {"SP_BACKEND_URL": "http://backend"}):
            await middleware(scope, AsyncMock(), AsyncMock())

        assert downstream_called is True

    @pytest.mark.asyncio
    async def test_extract_bearer_key_parses_header(self):
        scope = _make_scope(headers=[(b"authorization", b"Bearer sp_abc123")])
        assert _extract_bearer_key(scope) == "sp_abc123"

    def test_extract_bearer_key_missing_returns_none(self):
        scope = _make_scope(headers=[])
        assert _extract_bearer_key(scope) is None

    def test_extract_bearer_key_non_bearer_scheme_returns_none(self):
        scope = _make_scope(headers=[(b"authorization", b"Basic dXNlcjpwYXNz")])
        assert _extract_bearer_key(scope) is None

    @pytest.mark.asyncio
    async def test_local_mode_clamps_org_id_to_local(self):
        """Key-matched local-mode path must clamp org_id to 'local'.

        Even if the matched GatewayApiKey has org_id='stale-cloud-org' (e.g. from
        cloud sync), the middleware must set scope["state"]["auth"]["org_id"] = "local"
        and mcp_org_id_var = "local" to prevent stale cloud org data from leaking
        into the local governance context.

        We verify by inspecting the auth dict written to the ASGI scope by the middleware.
        The middleware uses inline imports so we patch at the source module level.
        """
        from gateway.mcp_server import mcp_org_id_var

        # Simulate a matched API key with a stale cloud org_id
        stale_key = MagicMock()
        stale_key.id = "key-id-1"
        stale_key.name = "test-key"
        stale_key.user_id = "user-123"
        stale_key.org_id = "stale-cloud-org"  # Must be clamped to "local"

        captured_scope: dict = {}

        async def capturing_app(scope_arg, receive, send):
            captured_scope.update(scope_arg)
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}", "more_body": False})

        capturing_middleware = MCPAuthMiddleware(capturing_app)

        # Build mock store that returns a key with stale org_id and has user keys present
        mock_store = MagicMock()
        mock_store.list_api_keys = AsyncMock(return_value=[stale_key])
        mock_store.validate_stored_api_key = AsyncMock(return_value=stale_key)
        # Store.__init__ calls current_org_id_var.set; allow_unscoped=True means org_id=None
        mock_store.org_id = None

        # The session factory yields mock_store through an async context manager
        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session_cm)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)
        mock_factory = MagicMock(return_value=mock_session_cm)

        scope = _make_scope(headers=_bearer_headers("sp_localkey"))

        # Patch at the modules where mcp_auth.py imports from
        with patch("gateway.db.engine.get_session_factory", return_value=mock_factory):
            with patch("gateway.store.Store", return_value=mock_store):
                with patch.dict("os.environ", {}, clear=True):
                    import os as _os
                    _os.environ.pop("SP_BACKEND_URL", None)
                    _os.environ.pop("SP_DEPLOYMENT_MODE", None)
                    response = await _collect_response(capturing_middleware, scope)

        # The clamped org_id must be "local", not the stale cloud value
        auth = captured_scope.get("state", {}).get("auth", {})
        assert auth.get("org_id") == "local", (
            f"Expected org_id='local' (clamped) but got '{auth.get('org_id')}'"
        )
        # mcp_org_id_var must also be "local"
        assert mcp_org_id_var.get() == "local"
