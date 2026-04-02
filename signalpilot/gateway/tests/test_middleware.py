"""Tests for the middleware layer — authentication, rate limiting, security headers."""

import pytest
import time
from collections import defaultdict
from unittest.mock import MagicMock

from gateway.middleware import APIKeyAuthMiddleware, RateLimitMiddleware


class TestRateLimitMiddleware:
    """Test the rate limiter logic."""

    def test_check_rate_allows_under_limit(self):
        middleware = RateLimitMiddleware.__new__(RateLimitMiddleware)
        hits: list[float] = []
        assert middleware._check_rate(hits, 10) is True
        assert len(hits) == 1

    def test_check_rate_blocks_over_limit(self):
        middleware = RateLimitMiddleware.__new__(RateLimitMiddleware)
        now = time.monotonic()
        hits = [now - i for i in range(10)]  # 10 recent hits
        assert middleware._check_rate(hits, 10) is False

    def test_check_rate_prunes_old_entries(self):
        middleware = RateLimitMiddleware.__new__(RateLimitMiddleware)
        old_time = time.monotonic() - 120  # 2 minutes ago (outside 1-min window)
        hits = [old_time] * 50
        assert middleware._check_rate(hits, 10) is True
        # Old entries should have been pruned
        assert len(hits) == 1

    def test_check_rate_boundary_exactly_at_limit(self):
        """The Nth request at exactly the limit should be rejected."""
        middleware = RateLimitMiddleware.__new__(RateLimitMiddleware)
        now = time.monotonic()
        hits = [now - 0.1 * i for i in range(5)]  # 5 recent hits
        assert middleware._check_rate(hits, 5) is False

    def test_cleanup_stale_ips_removes_old(self):
        """Stale IP tracking entries should be cleaned up."""
        middleware = RateLimitMiddleware.__new__(RateLimitMiddleware)
        middleware._general_hits = defaultdict(list)
        middleware._expensive_hits = defaultdict(list)

        old = time.monotonic() - 300  # 5 minutes ago
        middleware._general_hits["1.2.3.4"] = [old]
        middleware._general_hits["5.6.7.8"] = [time.monotonic()]

        middleware._cleanup_stale_ips()
        assert "1.2.3.4" not in middleware._general_hits
        assert "5.6.7.8" in middleware._general_hits

    def test_client_ip_from_x_forwarded_for(self):
        """IP extraction should use the first X-Forwarded-For entry."""
        middleware = RateLimitMiddleware.__new__(RateLimitMiddleware)
        request = MagicMock()
        request.headers = {"x-forwarded-for": "10.0.0.1, 192.168.1.1, 172.16.0.1"}
        ip = middleware._client_ip(request)
        assert ip == "10.0.0.1"

    def test_client_ip_falls_back_to_client_host(self):
        middleware = RateLimitMiddleware.__new__(RateLimitMiddleware)
        request = MagicMock()
        request.headers = {}
        request.client.host = "127.0.0.1"
        ip = middleware._client_ip(request)
        assert ip == "127.0.0.1"

    def test_expensive_path_detection(self):
        middleware = RateLimitMiddleware.__new__(RateLimitMiddleware)
        # POST /api/query is expensive
        request = MagicMock()
        request.url.path = "/api/query"
        request.method = "POST"
        assert middleware._is_expensive(request) is True

        # GET /api/query is not expensive
        request.method = "GET"
        assert middleware._is_expensive(request) is False

        # POST /api/sandboxes/{id}/execute is expensive
        request.url.path = "/api/sandboxes/abc-123/execute"
        request.method = "POST"
        assert middleware._is_expensive(request) is True


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


class TestAPIKeyConstantTimeComparison:
    """Verify that API key comparison uses constant-time comparison."""

    def test_hmac_compare_digest_used(self):
        """The middleware source should use hmac.compare_digest, not == for key comparison."""
        import inspect
        source = inspect.getsource(APIKeyAuthMiddleware)
        assert "hmac.compare_digest" in source
        # Should NOT use plain equality for key comparison
        assert "provided_key ==" not in source
