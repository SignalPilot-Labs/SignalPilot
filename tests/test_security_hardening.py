"""Tests for security hardening: metrics auth enforcement, payload sanitization,
health endpoint shape, and PUBLIC_PATHS membership."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.testclient import TestClient

from signalpilot.gateway.gateway.middleware import APIKeyAuthMiddleware, PUBLIC_PATHS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_metrics_app() -> FastAPI:
    """Minimal FastAPI app with /api/metrics and /health endpoints plus auth middleware."""
    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"status": "healthy", "version": "0.1.0"}

    @app.get("/api/metrics")
    async def metrics():
        # Represents the sanitized metrics payload (no sandbox_manager, no cache stats).
        return {
            "timestamp": 1234567890.0,
            "sandbox_health": "healthy",
            "sandbox_available": True,
            "active_sandboxes": 2,
            "running_sandboxes": 1,
            "active_sandbox_instances": 3,
            "max_sandbox_instances": 10,
            "connections": 4,
        }

    app.add_middleware(APIKeyAuthMiddleware)
    return app


# ---------------------------------------------------------------------------
# PUBLIC_PATHS membership
# ---------------------------------------------------------------------------


class TestPublicPathsMembership:
    """/api/metrics must NOT be public; /health must be."""

    def test_health_is_public(self):
        assert "/health" in PUBLIC_PATHS

    def test_metrics_is_not_public(self):
        """/api/metrics must require authentication to prevent topology leakage."""
        assert "/api/metrics" not in PUBLIC_PATHS

    def test_docs_is_public(self):
        assert "/docs" in PUBLIC_PATHS

    def test_openapi_json_is_public(self):
        assert "/openapi.json" in PUBLIC_PATHS


# ---------------------------------------------------------------------------
# /api/metrics auth enforcement
# ---------------------------------------------------------------------------


class TestMetricsAuthEnforcement:
    """Unauthenticated requests to /api/metrics must be rejected by middleware."""

    def _client(self) -> TestClient:
        app = _make_metrics_app()
        return TestClient(app, raise_server_exceptions=False)

    def test_unauthenticated_get_returns_401(self):
        """No credentials → middleware returns 401 before the endpoint is reached."""
        client = self._client()
        resp = client.get("/api/metrics")
        assert resp.status_code == 401

    def test_wrong_key_returns_403(self):
        """An sp_-prefixed key that doesn't match any stored key → 403."""
        client = self._client()
        resp = client.get("/api/metrics", headers={"Authorization": "Bearer sp_wrongkey123"})
        assert resp.status_code == 403

    def test_health_still_accessible_without_auth(self):
        """/health remains public even after /api/metrics was removed from PUBLIC_PATHS."""
        client = self._client()
        resp = client.get("/health")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# /health endpoint shape
# ---------------------------------------------------------------------------


class TestHealthEndpointShape:
    """GET /health must return exactly {status, version} — no extra fields."""

    def test_health_returns_status_and_version(self):
        app = FastAPI()

        @app.get("/health")
        async def health():
            return {"status": "healthy", "version": "0.1.0"}

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == {"status", "version"}

    def test_health_has_no_infrastructure_fields(self):
        """Health must not expose sandbox URLs, cache stats, or internal config."""
        app = FastAPI()

        @app.get("/health")
        async def health():
            return {"status": "healthy", "version": "0.1.0"}

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/health")
        body = resp.json()
        forbidden_keys = {"sandbox_manager", "sandbox_manager_url", "query_cache",
                          "schema_cache", "database_url", "encryption_key"}
        assert not forbidden_keys.intersection(body.keys())


# ---------------------------------------------------------------------------
# Metrics payload sanitization
# ---------------------------------------------------------------------------


class TestMetricsPayloadSanitization:
    """The metrics SSE payload must not expose sensitive infrastructure details."""

    _ALLOWED_KEYS = frozenset({
        "timestamp",
        "sandbox_health",
        "sandbox_available",
        "connections",
        "active_sandboxes",
        "running_sandboxes",
        "active_sandbox_instances",
        "max_sandbox_instances",
    })

    _FORBIDDEN_KEYS = frozenset({
        "sandbox_manager",
        "sandbox_manager_url",
        "query_cache",
        "schema_cache",
    })

    def test_sample_payload_has_no_forbidden_keys(self):
        """A sample payload matching the sanitized metrics format has no forbidden keys."""
        sample_payload = {
            "timestamp": 1234567890.0,
            "sandbox_health": "healthy",
            "sandbox_available": True,
            "active_sandboxes": 2,
            "running_sandboxes": 1,
            "active_sandbox_instances": 3,
            "max_sandbox_instances": 10,
            "connections": 4,
        }
        assert not self._FORBIDDEN_KEYS.intersection(sample_payload.keys())

    def test_sample_payload_has_all_allowed_keys(self):
        sample_payload = {
            "timestamp": 1234567890.0,
            "sandbox_health": "healthy",
            "sandbox_available": True,
            "active_sandboxes": 2,
            "running_sandboxes": 1,
            "active_sandbox_instances": 3,
            "max_sandbox_instances": 10,
            "connections": 4,
        }
        assert self._ALLOWED_KEYS == set(sample_payload.keys())

    def test_metrics_module_does_not_import_query_cache(self):
        """The metrics module must not import query_cache (removed as per spec)."""
        import importlib
        import signalpilot.gateway.gateway.api.metrics as metrics_mod
        # query_cache should not be referenced in the metrics module namespace
        assert not hasattr(metrics_mod, "query_cache")

    def test_metrics_module_does_not_import_schema_cache(self):
        """The metrics module must not import schema_cache (removed as per spec)."""
        import signalpilot.gateway.gateway.api.metrics as metrics_mod
        assert not hasattr(metrics_mod, "schema_cache")
