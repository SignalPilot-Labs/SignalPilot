"""Tests for the middleware layer — authentication, rate limiting, security headers."""

import time

import pytest

from gateway.http import APIKeyAuthMiddleware, RateLimitMiddleware


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


class TestMiddlewarePublicPaths:
    """Verify public path list."""

    def test_health_is_public(self):
        from gateway.http import PUBLIC_PATHS

        assert "/health" in PUBLIC_PATHS

    def test_api_endpoints_not_public(self):
        from gateway.http import PUBLIC_PATHS

        assert "/api/settings" not in PUBLIC_PATHS
        assert "/api/connections" not in PUBLIC_PATHS
        assert "/api/query" not in PUBLIC_PATHS

    def test_metrics_not_public(self):
        """Metrics endpoint must require auth to prevent infrastructure topology leakage."""
        from gateway.http import PUBLIC_PATHS

        assert "/api/metrics" not in PUBLIC_PATHS
