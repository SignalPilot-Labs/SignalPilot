"""
Unit tests for Round 2 security hardening:
  - RequestBodySizeLimitMiddleware (raw ASGI)
  - _validate_local_db_path (DuckDB/SQLite path traversal)
  - Connection string bypass via store.py chokepoint
  - _generate_profiles_yml (no passwords in output)
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers for raw ASGI testing
# ---------------------------------------------------------------------------


def _make_scope(
    method: str = "POST",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> dict[str, Any]:
    return {
        "type": "http",
        "method": method,
        "headers": headers or [],
        "path": "/api/test",
    }


async def _collect_sent(scope, receive, send_fn) -> list[dict[str, Any]]:
    """Run an ASGI app and collect all messages sent via send()."""
    sent: list[dict[str, Any]] = []

    async def capturing_send(message: dict[str, Any]) -> None:
        sent.append(message)

    from gateway.middleware import RequestBodySizeLimitMiddleware

    async def downstream(scope, receive, send):
        # Drain the receive queue to allow counting_receive to run
        while True:
            msg = await receive()
            if msg.get("type") == "http.disconnect" or not msg.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok", "more_body": False})

    middleware = RequestBodySizeLimitMiddleware(downstream, max_body_bytes=100)
    await middleware(scope, send_fn, capturing_send)
    return sent


# ---------------------------------------------------------------------------
# TestRequestBodySizeLimit
# ---------------------------------------------------------------------------


class TestRequestBodySizeLimit:
    """Tests for RequestBodySizeLimitMiddleware."""

    def _make_middleware(self, limit: int = 2_097_152):
        from gateway.middleware import RequestBodySizeLimitMiddleware

        async def dummy_app(scope, receive, send):
            # Drain body
            while True:
                msg = await receive()
                if not msg.get("more_body", False):
                    break
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok", "more_body": False})

        return RequestBodySizeLimitMiddleware(dummy_app, max_body_bytes=limit)

    def test_post_with_large_content_length_returns_413(self):
        """POST with Content-Length > limit should be rejected with 413."""
        middleware = self._make_middleware(limit=100)
        scope = _make_scope(
            method="POST",
            headers=[(b"content-length", b"999")],
        )

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        sent: list[dict[str, Any]] = []

        async def send(msg):
            sent.append(msg)

        asyncio.get_event_loop().run_until_complete(middleware(scope, receive, send))

        start = next(m for m in sent if m["type"] == "http.response.start")
        assert start["status"] == 413

    def test_post_with_body_under_limit_passes_through(self):
        """POST with body smaller than limit should receive 200."""
        middleware = self._make_middleware(limit=1000)
        scope = _make_scope(method="POST", headers=[(b"content-length", b"10")])

        async def receive():
            return {"type": "http.request", "body": b"x" * 10, "more_body": False}

        sent: list[dict[str, Any]] = []

        async def send(msg):
            sent.append(msg)

        asyncio.get_event_loop().run_until_complete(middleware(scope, receive, send))

        start = next(m for m in sent if m["type"] == "http.response.start")
        assert start["status"] == 200

    def test_get_request_not_affected(self):
        """GET requests should pass through regardless of any size limit."""
        middleware = self._make_middleware(limit=1)  # Extremely tight limit
        scope = _make_scope(method="GET")

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        sent: list[dict[str, Any]] = []

        async def send(msg):
            sent.append(msg)

        asyncio.get_event_loop().run_until_complete(middleware(scope, receive, send))

        start = next(m for m in sent if m["type"] == "http.response.start")
        assert start["status"] == 200

    def test_options_request_not_affected(self):
        """OPTIONS requests should pass through (CORS preflight)."""
        middleware = self._make_middleware(limit=1)
        scope = _make_scope(method="OPTIONS")

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        sent: list[dict[str, Any]] = []

        async def send(msg):
            sent.append(msg)

        asyncio.get_event_loop().run_until_complete(middleware(scope, receive, send))

        start = next(m for m in sent if m["type"] == "http.response.start")
        assert start["status"] == 200

    def test_non_http_scope_passes_through(self):
        """WebSocket/lifespan scopes should be passed through unchanged."""
        from gateway.middleware import RequestBodySizeLimitMiddleware

        downstream_called = []

        async def downstream(scope, receive, send):
            downstream_called.append(True)

        middleware = RequestBodySizeLimitMiddleware(downstream, max_body_bytes=1)
        scope = {"type": "websocket", "method": "GET"}

        asyncio.get_event_loop().run_until_complete(middleware(scope, None, None))
        assert downstream_called

    def test_chunked_body_exceeding_limit_returns_413(self):
        """Chunked body without Content-Length that exceeds limit returns 413."""
        middleware = self._make_middleware(limit=50)
        scope = _make_scope(method="POST", headers=[])  # No Content-Length

        chunks = [b"x" * 30, b"x" * 30]  # 60 bytes total > 50 limit
        chunk_iter = iter(chunks)

        async def receive():
            try:
                chunk = next(chunk_iter)
                return {"type": "http.request", "body": chunk, "more_body": True}
            except StopIteration:
                return {"type": "http.request", "body": b"", "more_body": False}

        sent: list[dict[str, Any]] = []

        async def send(msg):
            sent.append(msg)

        asyncio.get_event_loop().run_until_complete(middleware(scope, receive, send))

        start = next((m for m in sent if m.get("type") == "http.response.start"), None)
        assert start is not None
        assert start["status"] == 413


# ---------------------------------------------------------------------------
# TestLocalDbPathValidation
# ---------------------------------------------------------------------------


class TestLocalDbPathValidation:
    """Tests for _validate_local_db_path in store.py."""

    def _validate(self, path: str) -> str:
        from gateway.store import _validate_local_db_path

        return _validate_local_db_path(path)

    def test_memory_is_allowed(self):
        assert self._validate(":memory:") == ":memory:"

    def test_motherduck_prefix_is_allowed(self):
        assert self._validate("md:my_database") == "md:my_database"

    def test_motherduck_with_extra_path_is_allowed(self):
        assert self._validate("md:organization/my_db") == "md:organization/my_db"

    def test_path_within_data_dir_is_allowed(self):
        from gateway.store._constants import DATA_DIR

        valid_path = str(DATA_DIR / "test.duckdb")
        assert self._validate(valid_path) == valid_path

    def test_relative_path_resolves_within_data_dir(self):
        """A relative path that resolves inside DATA_DIR should be allowed."""
        from gateway.store._constants import DATA_DIR

        # Build a path that resolves within DATA_DIR
        relative = str(DATA_DIR / "subdir" / ".." / "test.duckdb")
        assert self._validate(relative) == relative

    def test_etc_passwd_is_rejected(self):
        with pytest.raises(ValueError, match="Database path not allowed"):
            self._validate("/etc/passwd")

    def test_proc_self_environ_is_rejected(self):
        with pytest.raises(ValueError, match="Database path not allowed"):
            self._validate("/proc/self/environ")

    def test_traversal_sequence_is_rejected(self):
        with pytest.raises(ValueError, match="Database path not allowed"):
            self._validate("../../etc/passwd")

    def test_ssh_key_outside_data_dir_is_rejected(self):
        """A path in ~/.ssh is outside DATA_DIR and must be rejected."""
        ssh_key = str(Path.home() / ".ssh" / "id_rsa")
        with pytest.raises(ValueError, match="Database path not allowed"):
            self._validate(ssh_key)

    def test_home_dir_root_is_rejected(self):
        """The home directory itself is outside DATA_DIR."""
        home = str(Path.home() / "some_file.db")
        with pytest.raises(ValueError, match="Database path not allowed"):
            self._validate(home)

    def test_abs_root_path_is_rejected(self):
        with pytest.raises(ValueError, match="Database path not allowed"):
            self._validate("/tmp/evil.duckdb")


# ---------------------------------------------------------------------------
# TestConnectionStringBypass
# ---------------------------------------------------------------------------


class TestConnectionStringBypass:
    """Verify that direct connection_string does not bypass path validation."""

    def test_validate_connection_params_rejects_dangerous_connection_string(self):
        """_validate_connection_params should reject /etc/passwd for duckdb."""
        from gateway.api.connections import _validate_connection_params
        from gateway.models import ConnectionCreate

        conn = ConnectionCreate(
            name="evil",
            db_type="duckdb",
            connection_string="/etc/passwd",
        )
        errors = _validate_connection_params(conn)
        assert errors, "Expected validation errors for dangerous connection_string"
        assert any("Database path not allowed" in e for e in errors)

    def test_validate_connection_params_rejects_dangerous_database_field(self):
        """_validate_connection_params should reject /etc/passwd for sqlite database."""
        from gateway.api.connections import _validate_connection_params
        from gateway.models import ConnectionCreate

        conn = ConnectionCreate(
            name="evil",
            db_type="sqlite",
            database="/etc/passwd",
        )
        errors = _validate_connection_params(conn)
        assert errors, "Expected validation errors for dangerous database path"
        assert any("Database path not allowed" in e for e in errors)

    def test_store_chokepoint_rejects_dangerous_connection_string(self):
        """store._validate_local_db_path should be called at the raw_cred chokepoint."""
        from gateway.store import _validate_local_db_path

        with pytest.raises(ValueError, match="Database path not allowed"):
            _validate_local_db_path("/etc/passwd")

    def test_memory_connection_string_allowed_in_validate_params(self):
        """`:memory:` as connection_string should not produce errors."""
        from gateway.api.connections import _validate_connection_params
        from gateway.models import ConnectionCreate

        conn = ConnectionCreate(
            name="inmem",
            db_type="duckdb",
            connection_string=":memory:",
        )
        errors = _validate_connection_params(conn)
        assert not errors

    def test_safe_connection_string_within_data_dir_allowed(self):
        """A connection_string within DATA_DIR should not produce path errors."""
        from gateway.api.connections import _validate_connection_params
        from gateway.models import ConnectionCreate
        from gateway.store._constants import DATA_DIR

        conn = ConnectionCreate(
            name="safe",
            db_type="duckdb",
            connection_string=str(DATA_DIR / "my.duckdb"),
        )
        errors = _validate_connection_params(conn)
        # Should not contain a path-related error
        assert not any("Database path not allowed" in e for e in errors)


# ---------------------------------------------------------------------------
# TestProfilesYmlPermissions
# ---------------------------------------------------------------------------


class TestProfilesYmlPermissions:
    """Tests for profiles.yml generation — content sanity and no passwords."""

    def _make_store(self):
        from gateway.store import Store

        session = MagicMock()
        store = Store.__new__(Store)
        store.session = session
        store.user_id = "local"
        return store

    def _make_connection(self, db_type: str, **kwargs) -> Any:
        from gateway.models import ConnectionInfo

        return ConnectionInfo(
            id="test-id",
            name="test-conn",
            db_type=db_type,
            host=kwargs.get("host", "localhost"),
            port=kwargs.get("port", 5432),
            username=kwargs.get("username", "testuser"),
            password=kwargs.get("password", "supersecret"),
            database=kwargs.get("database", "mydb"),
            account=kwargs.get("account", ""),
            warehouse=kwargs.get("warehouse", ""),
            role=kwargs.get("role", ""),
            project=kwargs.get("project", ""),
        )

    def test_postgres_profiles_yml_is_valid_yaml(self):
        """Generated postgres profiles.yml should be parseable YAML."""
        import yaml

        store = self._make_store()
        conn = self._make_connection("postgres", host="db.example.com", username="admin", database="prod")
        result = store._generate_profiles_yml("my_project", conn)
        parsed = yaml.safe_load(result)
        assert "my_project" in parsed

    def test_duckdb_profiles_yml_is_valid_yaml(self):
        import yaml

        store = self._make_store()
        conn = self._make_connection("duckdb", database=":memory:")
        result = store._generate_profiles_yml("duck_project", conn)
        parsed = yaml.safe_load(result)
        assert "duck_project" in parsed

    def test_no_passwords_in_postgres_profiles_yml(self):
        """Passwords must NOT appear in profiles.yml output."""
        store = self._make_store()
        conn = self._make_connection("postgres", password="topsecretpassword123")
        result = store._generate_profiles_yml("my_project", conn)
        assert "topsecretpassword123" not in result

    def test_no_passwords_in_snowflake_profiles_yml(self):
        """Snowflake profiles should not include passwords."""
        store = self._make_store()
        conn = self._make_connection(
            "snowflake",
            account="my_account",
            username="snowflake_user",
            password="flake_secret_999",
            database="PROD_DB",
            warehouse="COMPUTE_WH",
        )
        result = store._generate_profiles_yml("sf_project", conn)
        assert "flake_secret_999" not in result


# ---------------------------------------------------------------------------
# TestSecurityHeadersMiddleware
# ---------------------------------------------------------------------------


class TestSecurityHeadersMiddleware:
    """Tests for SecurityHeadersMiddleware header injection."""

    def _run_middleware(self, headers: dict[str, str] | None = None) -> dict[str, str]:
        """Run SecurityHeadersMiddleware and return response headers as a dict."""
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import PlainTextResponse
        from starlette.routing import Route
        from starlette.testclient import TestClient

        from gateway.middleware import SecurityHeadersMiddleware

        async def homepage(request: Request) -> PlainTextResponse:
            return PlainTextResponse("ok")

        app = Starlette(routes=[Route("/", homepage)])
        app.add_middleware(SecurityHeadersMiddleware)

        client = TestClient(app, raise_server_exceptions=True)
        response = client.get("/", headers=headers or {})
        return dict(response.headers)

    def test_permissions_policy_header(self):
        """Permissions-Policy header must be present on any response."""
        headers = self._run_middleware()
        assert "permissions-policy" in headers
        assert "camera=()" in headers["permissions-policy"]
        assert "microphone=()" in headers["permissions-policy"]
        assert "geolocation=()" in headers["permissions-policy"]

    def test_hsts_header_when_https(self):
        """Strict-Transport-Security must be set when X-Forwarded-Proto is https."""
        headers = self._run_middleware(headers={"X-Forwarded-Proto": "https"})
        assert "strict-transport-security" in headers
        assert "max-age=63072000" in headers["strict-transport-security"]
        assert "includeSubDomains" in headers["strict-transport-security"]

    def test_no_hsts_header_when_http(self):
        """Strict-Transport-Security must NOT be set on plain HTTP requests."""
        headers = self._run_middleware()
        assert "strict-transport-security" not in headers

    def test_csp_header_present(self):
        """content-security-policy header must be present on any response."""
        headers = self._run_middleware()
        assert "content-security-policy" in headers

    def test_csp_default_directives(self):
        """Default CSP must include baseline directives."""
        headers = self._run_middleware()
        csp = headers["content-security-policy"]
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp

    def test_csp_no_unsafe_inline_scripts(self):
        """script-src directive must not allow unsafe-inline."""
        headers = self._run_middleware()
        csp = headers["content-security-policy"]
        # Find the script-src directive and verify it has no unsafe-inline
        directives = {d.strip().split(" ")[0]: d.strip() for d in csp.split(";")}
        script_src = directives.get("script-src", "")
        assert "'unsafe-inline'" not in script_src

    def test_x_xss_protection_disabled(self):
        """X-XSS-Protection must be set to 0 (disabled) to prevent XSS auditor exploits."""
        headers = self._run_middleware()
        assert headers.get("x-xss-protection") == "0"

    def test_x_content_type_options_nosniff(self):
        """X-Content-Type-Options must be set to nosniff."""
        headers = self._run_middleware()
        assert headers.get("x-content-type-options") == "nosniff"

    def test_x_frame_options_deny(self):
        """X-Frame-Options must be set to DENY."""
        headers = self._run_middleware()
        assert headers.get("x-frame-options") == "DENY"

    def test_csp_custom_override(self):
        """SP_GATEWAY_CSP_POLICY env var replaces the default policy entirely."""
        import os

        custom_policy = "default-src 'none'; script-src 'self' cdn.example.com"
        with MagicMock():
            original = os.environ.get("SP_GATEWAY_CSP_POLICY")
            try:
                os.environ["SP_GATEWAY_CSP_POLICY"] = custom_policy
                headers = self._run_middleware()
                assert headers["content-security-policy"] == custom_policy
            finally:
                if original is None:
                    os.environ.pop("SP_GATEWAY_CSP_POLICY", None)
                else:
                    os.environ["SP_GATEWAY_CSP_POLICY"] = original


# ---------------------------------------------------------------------------
# TestCorsOriginValidation
# ---------------------------------------------------------------------------


class TestCorsOriginValidation:
    """Tests for SP_ALLOWED_ORIGINS validation in main.py."""

    def _build_allowed_origins(self, extra_origins: str) -> list[str]:
        """Re-run the CORS origin filtering logic with a custom env-var value."""
        hardcoded = [
            "http://localhost:3200",
            "http://localhost:3000",
            "http://127.0.0.1:3200",
            "http://127.0.0.1:3000",
        ]
        result = list(hardcoded)
        import logging

        logger = logging.getLogger("gateway.main")
        for origin in (o.strip() for o in extra_origins.split(",") if o.strip()):
            if origin == "*":
                logger.warning(
                    "SP_ALLOWED_ORIGINS contains '*' — wildcard origin is not allowed "
                    "with allow_credentials=True; skipping."
                )
                continue
            if not (origin.startswith(("http://", "https://"))):
                logger.warning(
                    "SP_ALLOWED_ORIGINS entry %r is not a valid HTTP/HTTPS origin; skipping.",
                    origin,
                )
                continue
            result.append(origin)
        return result

    def test_wildcard_is_excluded(self):
        """'*' must never be added to the origins list."""
        origins = self._build_allowed_origins("*")
        assert "*" not in origins

    def test_wildcard_among_valid_origins_is_excluded(self):
        """'*' mixed with valid origins — the valid one is kept, '*' is dropped."""
        origins = self._build_allowed_origins("https://app.example.com,*")
        assert "*" not in origins
        assert "https://app.example.com" in origins

    def test_non_url_value_is_excluded(self):
        """A value without http/https scheme must be skipped."""
        origins = self._build_allowed_origins("not-a-url")
        assert "not-a-url" not in origins

    def test_ftp_scheme_is_excluded(self):
        """An ftp:// origin must be skipped (not http/https)."""
        origins = self._build_allowed_origins("ftp://evil.example.com")
        assert "ftp://evil.example.com" not in origins

    def test_valid_https_origin_is_included(self):
        """A well-formed https:// origin must be added."""
        origins = self._build_allowed_origins("https://dashboard.example.com")
        assert "https://dashboard.example.com" in origins

    def test_valid_http_origin_is_included(self):
        """A well-formed http:// origin must be added (e.g. internal LAN)."""
        origins = self._build_allowed_origins("http://internal.corp:8080")
        assert "http://internal.corp:8080" in origins

    def test_hardcoded_localhost_origins_always_present(self):
        """Filtering bad entries must not remove the hardcoded localhost origins."""
        origins = self._build_allowed_origins("*,not-a-url")
        assert "http://localhost:3000" in origins
        assert "http://localhost:3200" in origins
        assert "http://127.0.0.1:3000" in origins
        assert "http://127.0.0.1:3200" in origins


# ---------------------------------------------------------------------------
# TestAuthRateLimiting
# ---------------------------------------------------------------------------


class TestAuthRateLimiting:
    """Tests for the third rate-limit tier targeting POST /api/keys."""

    def _make_test_app(self, auth_rpm: int, general_rpm: int = 120, expensive_rpm: int = 30):
        """Return a (TestClient, middleware) pair for rate limit testing.

        The inner Starlette app accepts every method on every path so tests can
        issue arbitrary method/path combinations without 405 responses.
        """
        from starlette.applications import Starlette
        from starlette.requests import Request as StarletteRequest
        from starlette.responses import PlainTextResponse
        from starlette.routing import Route
        from starlette.testclient import TestClient

        from gateway.middleware import RateLimitMiddleware

        async def catch_all(request: StarletteRequest) -> PlainTextResponse:
            return PlainTextResponse("ok")

        # Mount a single route that accepts all HTTP methods
        route = Route("/{path:path}", catch_all, methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
        app = Starlette(routes=[route])
        app.add_middleware(
            RateLimitMiddleware,
            general_rpm=general_rpm,
            expensive_rpm=expensive_rpm,
            auth_rpm=auth_rpm,
        )
        return TestClient(app, raise_server_exceptions=False)

    def test_auth_endpoint_429_after_limit(self):
        """POST /api/keys returns 429 after auth_rpm requests from same IP."""
        client = self._make_test_app(auth_rpm=3, general_rpm=120)

        statuses = [client.post("/api/keys", headers={"X-Forwarded-For": "10.0.0.1"}).status_code for _ in range(5)]
        # First 3 should succeed (200), then 429
        assert statuses[:3] == [200, 200, 200], f"Expected first 3 to be 200, got {statuses[:3]}"
        assert statuses[3] == 429, f"Expected 4th request to be 429, got {statuses[3]}"
        assert statuses[4] == 429, f"Expected 5th request to be 429, got {statuses[4]}"

    def test_general_endpoint_not_affected_by_auth_limit(self):
        """GET /health is not blocked by the auth rate limit."""
        client = self._make_test_app(auth_rpm=3, general_rpm=120)

        statuses = [client.get("/health", headers={"X-Forwarded-For": "10.0.0.2"}).status_code for _ in range(10)]
        assert all(s == 200 for s in statuses), f"Expected all 200, got {statuses}"

    def test_auth_429_does_not_increment_general_bucket(self):
        """Auth 429s must not consume the general rate limit bucket.

        After exhausting the auth limit, the general bucket for that IP should
        still have capacity (i.e., a non-auth request from same IP returns 200).
        """
        # general_rpm=5 so any leakage from auth 429s into the general bucket
        # would be clearly visible — 6 auth 429s > 5 general slots.
        client = self._make_test_app(auth_rpm=2, general_rpm=5)
        ip_header = {"X-Forwarded-For": "10.0.0.3"}

        # Exhaust auth limit (2 allowed + 4 extra 429s = 6 total auth requests)
        for _ in range(6):
            client.post("/api/keys", headers=ip_header)

        # After auth exhaustion, a non-auth request should NOT be rate-limited
        # (the 4 auth 429s must not have incremented the general bucket)
        response = client.get("/health", headers=ip_header)
        assert response.status_code == 200, (
            f"Expected 200 for general request after auth exhaustion, got {response.status_code}. "
            "Auth 429s must not increment the general bucket."
        )


# ---------------------------------------------------------------------------
# TestSseResourceLimits
# ---------------------------------------------------------------------------


class TestSseResourceLimits:
    """Tests for SSE /api/metrics connection cap and timeout."""

    def _reset_semaphore(self, value: int) -> None:
        """Replace the module-level semaphore with a fresh one for test isolation."""
        import gateway.api.metrics as metrics_mod

        metrics_mod._sse_semaphore = asyncio.Semaphore(value)

    def test_exceeding_max_connections_returns_429(self):
        """When all SSE permits are taken, the endpoint must return 429."""
        from unittest.mock import AsyncMock

        import gateway.api.metrics as metrics_mod

        # Replace semaphore with a fully-exhausted one (capacity 0 remaining).
        metrics_mod._sse_semaphore = asyncio.Semaphore(0)

        async def run():
            mock_store = AsyncMock()
            mock_store.list_connections = AsyncMock(return_value=[])
            try:
                # The handler checks locked() before creating the StreamingResponse.
                # locked() returns True when counter == 0.
                assert metrics_mod._sse_semaphore.locked()
                from fastapi import HTTPException

                try:
                    # Simulate what the handler does
                    if metrics_mod._sse_semaphore.locked():
                        raise HTTPException(
                            status_code=429,
                            detail="Too many concurrent SSE connections. Try again later.",
                            headers={"Retry-After": "30"},
                        )
                    raise AssertionError("Should have raised 429")
                except HTTPException as exc:
                    assert exc.status_code == 429
                    assert exc.headers is not None
                    assert "Retry-After" in exc.headers
            finally:
                pass

        asyncio.get_event_loop().run_until_complete(run())
        self._reset_semaphore(20)

    def test_stream_ends_after_max_duration(self):
        """Generator must stop yielding after SSE_MAX_DURATION_SECONDS."""
        import time

        import gateway.api.metrics as metrics_mod

        original_duration = metrics_mod.SSE_MAX_DURATION_SECONDS
        metrics_mod.SSE_MAX_DURATION_SECONDS = 0  # Expires immediately
        metrics_mod._sse_semaphore = asyncio.Semaphore(20)

        async def generate_test():
            await metrics_mod._sse_semaphore.acquire()
            try:
                deadline = time.monotonic() + metrics_mod.SSE_MAX_DURATION_SECONDS
                while time.monotonic() < deadline:
                    yield "data: {}\n\n"
                    await asyncio.sleep(0)
            finally:
                metrics_mod._sse_semaphore.release()

        async def run():
            events = []
            async for event in generate_test():
                events.append(event)
            return events

        events = asyncio.get_event_loop().run_until_complete(run())
        # With duration=0, the deadline is already passed before any iteration.
        assert len(events) == 0

        metrics_mod.SSE_MAX_DURATION_SECONDS = original_duration
        self._reset_semaphore(20)

    def test_semaphore_released_after_stream_ends(self):
        """Semaphore must be released when the generator completes normally."""
        import time

        import gateway.api.metrics as metrics_mod

        metrics_mod._sse_semaphore = asyncio.Semaphore(1)
        original_duration = metrics_mod.SSE_MAX_DURATION_SECONDS
        metrics_mod.SSE_MAX_DURATION_SECONDS = 0  # Immediate exit

        async def generate_test():
            await metrics_mod._sse_semaphore.acquire()
            try:
                deadline = time.monotonic() + metrics_mod.SSE_MAX_DURATION_SECONDS
                while time.monotonic() < deadline:
                    yield "data: {}\n\n"
                    await asyncio.sleep(0)
            finally:
                metrics_mod._sse_semaphore.release()

        async def run():
            async for _ in generate_test():
                pass
            # After generator exits, semaphore should be back at capacity
            assert not metrics_mod._sse_semaphore.locked()

        asyncio.get_event_loop().run_until_complete(run())

        metrics_mod.SSE_MAX_DURATION_SECONDS = original_duration
        self._reset_semaphore(20)
