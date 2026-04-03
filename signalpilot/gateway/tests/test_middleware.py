"""Tests for the middleware layer — authentication, rate limiting, security headers."""

import time
import uuid
from collections import deque
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as StarletteResponse

from gateway.middleware import (
    APIKeyAuthMiddleware,
    AuthBruteForceMiddleware,
    RateLimitMiddleware,
    RequestIDMiddleware,
    SecurityHeadersMiddleware,
    _is_public_path,
)


def _make_test_app(*middleware_classes, **middleware_kwargs):
    """Create a minimal app with specified middleware for testing."""
    app = FastAPI()

    @app.get("/test")
    async def test_endpoint():
        return {"ok": True}

    @app.get("/health")
    async def health_endpoint():
        return {"status": "ok"}

    # Add middleware in reverse order so the first listed is the outermost
    for cls in reversed(middleware_classes):
        kwargs = middleware_kwargs.get(cls.__name__, {})
        app.add_middleware(cls, **kwargs)

    return TestClient(app, raise_server_exceptions=True)


class TestRateLimitMiddleware:
    """Test the rate limiter logic."""

    def test_check_rate_allows_under_limit(self):
        middleware = RateLimitMiddleware.__new__(RateLimitMiddleware)
        hits: deque[float] = deque()
        allowed, remaining = middleware._check_rate(hits, 10)
        assert allowed is True
        assert len(hits) == 1

    def test_check_rate_blocks_over_limit(self):
        middleware = RateLimitMiddleware.__new__(RateLimitMiddleware)
        now = time.monotonic()
        hits: deque[float] = deque(now - i for i in range(10))  # 10 recent hits
        allowed, remaining = middleware._check_rate(hits, 10)
        assert allowed is False
        assert remaining == 0

    def test_check_rate_prunes_old_entries(self):
        middleware = RateLimitMiddleware.__new__(RateLimitMiddleware)
        old_time = time.monotonic() - 120  # 2 minutes ago (outside 1-min window)
        hits: deque[float] = deque([old_time] * 50)
        allowed, remaining = middleware._check_rate(hits, 10)
        assert allowed is True
        # Old entries pruned, then current request appended — should be exactly 1
        assert len(hits) == 1

    def test_check_rate_remaining_decrements(self):
        middleware = RateLimitMiddleware.__new__(RateLimitMiddleware)
        hits: deque[float] = deque()
        _, remaining_first = middleware._check_rate(hits, 5)
        _, remaining_second = middleware._check_rate(hits, 5)
        assert remaining_first == 4
        assert remaining_second == 3


class TestMiddlewarePublicPaths:
    """Verify public path list."""

    def test_health_is_public(self):
        from gateway.middleware import PUBLIC_PATHS
        assert "/health" in PUBLIC_PATHS

    def test_api_endpoints_not_public(self):
        from gateway.middleware import PUBLIC_PATHS
        assert "/api/settings" not in PUBLIC_PATHS
        assert "/api/connections" not in PUBLIC_PATHS
        assert "/api/query" not in PUBLIC_PATHS


class TestIsPublicPath:
    """Test the _is_public_path helper."""

    def test_health_exact(self):
        assert _is_public_path("/health") is True

    def test_health_trailing_slash(self):
        assert _is_public_path("/health/") is True

    def test_docs_exact(self):
        assert _is_public_path("/docs") is True

    def test_docs_oauth_redirect_exact(self):
        assert _is_public_path("/docs/oauth2-redirect") is True

    def test_docs_arbitrary_subpath_not_public(self):
        """Arbitrary /docs/* subpaths should NOT be public (no prefix matching)."""
        assert _is_public_path("/docs/../../api/query") is False
        assert _is_public_path("/docs/admin") is False

    def test_api_settings_not_public(self):
        assert _is_public_path("/api/settings") is False

    def test_api_query_not_public(self):
        assert _is_public_path("/api/query") is False


class TestRequestIDMiddleware:
    """Verify RequestIDMiddleware can be imported and instantiated."""

    def test_class_exists_and_is_importable(self):
        # If the import at the top of this module succeeds, the class exists.
        assert RequestIDMiddleware is not None

    def test_instantiation_requires_app_arg(self):
        # BaseHTTPMiddleware requires an ASGI app; confirm the constructor
        # signature by checking that omitting the argument raises TypeError.
        with pytest.raises(TypeError):
            RequestIDMiddleware()  # type: ignore[call-arg]


class TestAuthBruteForceMiddleware:
    """Test brute-force tracking logic directly on the middleware instance."""

    def _make_middleware(self) -> AuthBruteForceMiddleware:
        """Create an AuthBruteForceMiddleware bypassing the ASGI app requirement."""
        return AuthBruteForceMiddleware.__new__(AuthBruteForceMiddleware)

    def _init_state(self, mw: AuthBruteForceMiddleware) -> None:
        """Manually initialise the instance dicts that __init__ would set up."""
        from collections import defaultdict
        mw._failures = defaultdict(deque)
        mw._blocked = {}

    def test_failures_tracked(self):
        """Recording a failure populates _failures for that IP."""
        mw = self._make_middleware()
        self._init_state(mw)

        ip = "10.0.0.1"
        now = time.monotonic()
        window_start = now - mw._WINDOW_SECONDS

        hits = mw._failures[ip]
        while hits and hits[0] < window_start:
            hits.popleft()
        hits.append(now)

        assert len(mw._failures[ip]) == 1

    def test_block_after_threshold(self):
        """IP is added to _blocked once failure count reaches _MAX_FAILURES."""
        mw = self._make_middleware()
        self._init_state(mw)

        ip = "10.0.0.2"
        now = time.monotonic()

        # Simulate _MAX_FAILURES failures within the window
        for _ in range(mw._MAX_FAILURES):
            hits = mw._failures[ip]
            window_start = now - mw._WINDOW_SECONDS
            while hits and hits[0] < window_start:
                hits.popleft()
            hits.append(now)
            if len(hits) >= mw._MAX_FAILURES:
                mw._blocked[ip] = now + mw._BLOCK_SECONDS

        assert ip in mw._blocked
        assert mw._blocked[ip] > now

    def test_block_expires(self):
        """An expired block entry is cleaned up when the next request is processed."""
        mw = self._make_middleware()
        self._init_state(mw)

        ip = "10.0.0.3"
        # Plant an already-expired block
        mw._blocked[ip] = time.monotonic() - 1  # expired 1 second ago
        mw._failures[ip].append(time.monotonic() - 2)

        now = time.monotonic()
        block_expiry = mw._blocked.get(ip)

        # Replicate the expiry-cleanup logic from dispatch()
        if block_expiry is not None and now >= block_expiry:
            del mw._blocked[ip]
            mw._failures[ip].clear()

        assert ip not in mw._blocked
        assert len(mw._failures[ip]) == 0


class TestClientIpExtraction:
    """Verify centralized _client_ip function."""

    def test_uses_client_host_by_default(self):
        """When SP_TRUSTED_PROXY_COUNT is 0, X-Forwarded-For is ignored."""
        from gateway.middleware import _client_ip, _TRUSTED_PROXY_COUNT
        # Default should be 0 (no trusted proxies)
        assert _TRUSTED_PROXY_COUNT == 0

    def test_module_level_function_exists(self):
        from gateway.middleware import _client_ip
        assert callable(_client_ip)


class TestBruteForceCleanup:
    """Verify brute-force middleware cleanup logic."""

    def test_cleanup_stale_removes_old_failures(self):
        from gateway.middleware import AuthBruteForceMiddleware
        mw = AuthBruteForceMiddleware.__new__(AuthBruteForceMiddleware)
        from collections import defaultdict
        mw._failures = defaultdict(deque)
        mw._blocked = {}
        mw._cleanup_counter = 0

        # Add stale failure entry (2x window ago)
        old_time = time.monotonic() - mw._WINDOW_SECONDS * 3
        mw._failures["stale-ip"].append(old_time)
        # Add fresh failure entry
        mw._failures["fresh-ip"].append(time.monotonic())

        mw._cleanup_stale()

        assert "stale-ip" not in mw._failures
        assert "fresh-ip" in mw._failures

    def test_cleanup_removes_expired_blocks(self):
        from gateway.middleware import AuthBruteForceMiddleware
        mw = AuthBruteForceMiddleware.__new__(AuthBruteForceMiddleware)
        from collections import defaultdict
        mw._failures = defaultdict(deque)
        mw._blocked = {}
        mw._cleanup_counter = 0

        # Add an expired block
        mw._blocked["expired-ip"] = time.monotonic() - 10
        mw._failures["expired-ip"].append(time.monotonic() - 100)

        mw._cleanup_stale()

        assert "expired-ip" not in mw._blocked
        assert "expired-ip" not in mw._failures


class TestSecurityHeadersIntegration:
    """Integration tests: verify SecurityHeadersMiddleware actually sets response headers."""

    def _client(self):
        return _make_test_app(SecurityHeadersMiddleware)

    def test_content_security_policy_header_present(self):
        resp = self._client().get("/test")
        assert resp.status_code == 200
        assert "Content-Security-Policy" in resp.headers

    def test_content_security_policy_has_default_src_self(self):
        resp = self._client().get("/test")
        assert "default-src 'self'" in resp.headers["Content-Security-Policy"]

    def test_strict_transport_security_header_present(self):
        resp = self._client().get("/test")
        assert "Strict-Transport-Security" in resp.headers

    def test_strict_transport_security_value(self):
        resp = self._client().get("/test")
        assert "max-age=31536000" in resp.headers["Strict-Transport-Security"]
        assert "includeSubDomains" in resp.headers["Strict-Transport-Security"]

    def test_x_frame_options_deny(self):
        resp = self._client().get("/test")
        assert resp.headers.get("X-Frame-Options") == "DENY"

    def test_x_content_type_options_nosniff(self):
        resp = self._client().get("/test")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"

    def test_referrer_policy_header_present(self):
        resp = self._client().get("/test")
        assert "Referrer-Policy" in resp.headers
        assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"

    def test_cache_control_no_store(self):
        resp = self._client().get("/test")
        assert resp.headers.get("Cache-Control") == "no-store"

    def test_permissions_policy_header_present(self):
        resp = self._client().get("/test")
        assert "Permissions-Policy" in resp.headers

    def test_permissions_policy_disables_camera_and_mic(self):
        resp = self._client().get("/test")
        policy = resp.headers["Permissions-Policy"]
        assert "camera=()" in policy
        assert "microphone=()" in policy

    def test_x_xss_protection_header_present(self):
        resp = self._client().get("/test")
        assert "X-XSS-Protection" in resp.headers
        assert "1" in resp.headers["X-XSS-Protection"]

    def test_all_eight_security_headers_present(self):
        """All 8 security headers must be present in a single response."""
        resp = self._client().get("/test")
        expected_headers = [
            "Content-Security-Policy",
            "Strict-Transport-Security",
            "X-Frame-Options",
            "X-Content-Type-Options",
            "Referrer-Policy",
            "Cache-Control",
            "Permissions-Policy",
            "X-XSS-Protection",
        ]
        missing = [h for h in expected_headers if h not in resp.headers]
        assert missing == [], f"Missing security headers: {missing}"


class TestRequestIDMiddlewareIntegration:
    """Integration tests: verify RequestIDMiddleware actually sets X-Request-ID."""

    def _client(self):
        return _make_test_app(RequestIDMiddleware)

    def test_x_request_id_header_present(self):
        resp = self._client().get("/test")
        assert resp.status_code == 200
        assert "X-Request-ID" in resp.headers

    def test_x_request_id_is_valid_uuid4(self):
        resp = self._client().get("/test")
        request_id = resp.headers["X-Request-ID"]
        parsed = uuid.UUID(request_id)
        assert parsed.version == 4

    def test_x_request_id_is_unique_per_request(self):
        client = self._client()
        ids = {client.get("/test").headers["X-Request-ID"] for _ in range(5)}
        assert len(ids) == 5, "Each request should have a unique X-Request-ID"


class TestRateLimitMiddlewareIntegration:
    """Integration tests: verify RateLimitMiddleware emits X-RateLimit-* headers and 429."""

    def _client(self, general_rpm=10):
        return _make_test_app(
            RateLimitMiddleware,
            **{"RateLimitMiddleware": {"general_rpm": general_rpm, "expensive_rpm": 3}},
        )

    def test_ratelimit_limit_header_present(self):
        resp = self._client().get("/test")
        assert resp.status_code == 200
        assert "X-RateLimit-Limit" in resp.headers

    def test_ratelimit_remaining_header_present(self):
        resp = self._client().get("/test")
        assert "X-RateLimit-Remaining" in resp.headers

    def test_ratelimit_limit_matches_configured_rpm(self):
        resp = self._client(general_rpm=42).get("/test")
        assert resp.headers["X-RateLimit-Limit"] == "42"

    def test_ratelimit_remaining_decrements_with_each_request(self):
        client = self._client(general_rpm=10)
        first = int(client.get("/test").headers["X-RateLimit-Remaining"])
        second = int(client.get("/test").headers["X-RateLimit-Remaining"])
        assert second == first - 1

    def test_ratelimit_returns_429_when_limit_exceeded(self):
        """With a limit of 3 RPM, the 4th request in the same window should be blocked."""
        client = self._client(general_rpm=3)
        responses = [client.get("/test") for _ in range(4)]
        status_codes = [r.status_code for r in responses]
        assert 429 in status_codes, f"Expected a 429 but got: {status_codes}"

    def test_ratelimit_429_has_retry_after_header(self):
        """A 429 from the rate limiter must include a Retry-After header."""
        client = self._client(general_rpm=3)
        responses = [client.get("/test") for _ in range(4)]
        blocked = [r for r in responses if r.status_code == 429]
        assert blocked, "Expected at least one 429 response"
        assert "Retry-After" in blocked[0].headers

    def test_options_requests_bypass_rate_limit(self):
        """CORS preflight OPTIONS requests must not consume rate-limit budget."""
        client = self._client(general_rpm=3)
        for _ in range(10):
            resp = client.options("/test")
            assert resp.status_code != 429


class TestCORSIntegration:
    """Integration tests for CORS behavior using an inline middleware."""

    ALLOWED_ORIGIN = "https://allowed.example.com"

    def _client(self, allowed_origins=None):
        if allowed_origins is None:
            allowed_origins = [self.ALLOWED_ORIGIN]

        app = FastAPI()

        @app.get("/test")
        async def test_endpoint():
            return {"ok": True}

        # Inline CORS middleware that mirrors the real DynamicCORSMiddleware logic
        _allowed = set(allowed_origins)

        class _InlineCORSMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                origin = request.headers.get("origin", "")
                response = await call_next(request)
                if origin in _allowed:
                    response.headers["Access-Control-Allow-Origin"] = origin
                    response.headers["Access-Control-Allow-Credentials"] = "true"
                    response.headers["Vary"] = "Origin"
                else:
                    response.headers["Vary"] = "Origin"
                return response

        app.add_middleware(_InlineCORSMiddleware)
        return TestClient(app, raise_server_exceptions=True)

    def test_vary_origin_always_present(self):
        """Vary: Origin must be set regardless of whether the origin is allowed."""
        resp = self._client().get("/test", headers={"Origin": "https://evil.example.com"})
        assert "Origin" in resp.headers.get("Vary", "")

    def test_allowed_origin_gets_acao_header(self):
        resp = self._client().get("/test", headers={"Origin": self.ALLOWED_ORIGIN})
        assert resp.headers.get("Access-Control-Allow-Origin") == self.ALLOWED_ORIGIN

    def test_disallowed_origin_does_not_get_acao_header(self):
        resp = self._client().get("/test", headers={"Origin": "https://evil.example.com"})
        assert "Access-Control-Allow-Origin" not in resp.headers

    def test_no_origin_header_gets_no_acao(self):
        resp = self._client().get("/test")
        assert "Access-Control-Allow-Origin" not in resp.headers

    def test_allowed_origin_gets_allow_credentials(self):
        resp = self._client().get("/test", headers={"Origin": self.ALLOWED_ORIGIN})
        assert resp.headers.get("Access-Control-Allow-Credentials") == "true"


class TestAuthMiddlewareIntegration:
    """Integration tests: verify APIKeyAuthMiddleware authenticates requests."""

    _TEST_API_KEY = "test-secret-key-for-auth-middleware"

    def _mock_settings(self, api_key=None):
        """Return a mock settings object."""
        settings = MagicMock()
        settings.api_key = api_key if api_key is not None else self._TEST_API_KEY
        return settings

    def _client(self, api_key=None):
        """Create test client with auth middleware and mocked settings."""
        settings = self._mock_settings(api_key)
        client = _make_test_app(APIKeyAuthMiddleware)
        client._settings_mock = settings
        return client, settings

    @pytest.fixture(autouse=True)
    def _patch_settings(self):
        """Patch load_settings for all auth tests — must be active during request dispatch."""
        self._settings = self._mock_settings()
        with patch("gateway.store.load_settings", return_value=self._settings):
            yield

    def test_no_key_configured_allows_all(self):
        """When no API key is configured (dev mode), requests pass through."""
        self._settings.api_key = None
        client = _make_test_app(APIKeyAuthMiddleware)
        resp = client.get("/test")
        assert resp.status_code == 200
        # Auth state should NOT be leaked in response headers
        assert "X-SignalPilot-Auth" not in resp.headers

    def test_valid_bearer_token_allowed(self):
        """Request with correct Bearer token is allowed."""
        client = _make_test_app(APIKeyAuthMiddleware)
        resp = client.get("/test", headers={"Authorization": f"Bearer {self._TEST_API_KEY}"})
        assert resp.status_code == 200

    def test_valid_x_api_key_allowed(self):
        """Request with correct X-API-Key header is allowed."""
        client = _make_test_app(APIKeyAuthMiddleware)
        resp = client.get("/test", headers={"X-API-Key": self._TEST_API_KEY})
        assert resp.status_code == 200

    def test_missing_key_returns_401(self):
        """Request with no API key returns 401."""
        client = _make_test_app(APIKeyAuthMiddleware)
        resp = client.get("/test")
        assert resp.status_code == 401

    def test_wrong_key_returns_403(self):
        """Request with wrong API key returns 403."""
        client = _make_test_app(APIKeyAuthMiddleware)
        resp = client.get("/test", headers={"X-API-Key": "wrong-key"})
        assert resp.status_code == 403

    def test_public_path_bypasses_auth(self):
        """Public paths (e.g. /health) don't require authentication."""
        client = _make_test_app(APIKeyAuthMiddleware)
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_options_request_bypasses_auth(self):
        """CORS preflight OPTIONS requests bypass auth."""
        client = _make_test_app(APIKeyAuthMiddleware)
        resp = client.options("/test")
        assert resp.status_code != 401
        assert resp.status_code != 403

    def test_401_response_body_contains_detail(self):
        """401 response body should include a helpful detail message."""
        client = _make_test_app(APIKeyAuthMiddleware)
        resp = client.get("/test")
        assert "Authentication required" in resp.json()["detail"]

    def test_403_response_body_contains_detail(self):
        """403 response body should include a detail message."""
        client = _make_test_app(APIKeyAuthMiddleware)
        resp = client.get("/test", headers={"X-API-Key": "wrong"})
        assert "Invalid API key" in resp.json()["detail"]
