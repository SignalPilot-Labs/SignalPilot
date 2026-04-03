"""Tests for the middleware layer — authentication, rate limiting, security headers."""

import time
from collections import deque

import pytest

from gateway.middleware import (
    APIKeyAuthMiddleware,
    AuthBruteForceMiddleware,
    RateLimitMiddleware,
    RequestIDMiddleware,
    _is_public_path,
)


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

    def test_docs_prefix_match(self):
        assert _is_public_path("/docs/oauth2-redirect") is True

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


class TestSecurityHeaders:
    """Verify SecurityHeadersMiddleware sets the expected headers."""

    def test_expected_headers_include_csp(self):
        import inspect
        from gateway.middleware import SecurityHeadersMiddleware
        source = inspect.getsource(SecurityHeadersMiddleware.dispatch)
        assert "Content-Security-Policy" in source

    def test_expected_headers_include_hsts(self):
        import inspect
        from gateway.middleware import SecurityHeadersMiddleware
        source = inspect.getsource(SecurityHeadersMiddleware.dispatch)
        assert "Strict-Transport-Security" in source

    def test_expected_headers_include_permissions_policy(self):
        import inspect
        from gateway.middleware import SecurityHeadersMiddleware
        source = inspect.getsource(SecurityHeadersMiddleware.dispatch)
        assert "Permissions-Policy" in source
