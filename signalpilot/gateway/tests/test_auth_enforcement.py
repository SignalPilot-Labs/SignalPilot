"""Tests for auth enforcement: JWT verification via UserID dependency.

Validates that endpoints which previously lacked a StoreD/UserID dependency
now correctly enforce JWT verification in cloud mode.

Strategy:
- Single module-scoped TestClient shared across all test classes.
- Two modes controlled via _AUTH_MODE dict:
    "api_key": middleware sets api_key auth; resolve_user_id override allows.
    "reject_jwt": middleware leaves auth=None; resolve_user_id raises 401.
- JWT enforcement tests: set mode to "reject_jwt", confirm endpoint returns 401.
  This proves the UserID dependency IS wired up and calling resolve_user_id.
- Scope escalation tests: set mode to "api_key", set scopes via _set_scopes().
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException, Request, Response
from fastapi.testclient import TestClient
from starlette.middleware.base import RequestResponseEndpoint

from gateway.api.deps import get_store
from gateway.auth import resolve_user_id
from gateway.main import app
from gateway.middleware import APIKeyAuthMiddleware, RateLimitMiddleware

# ─── Shared mutable state ─────────────────────────────────────────────────────

_AUTH_MODE: dict[str, str] = {"mode": "api_key"}

_API_KEY_AUTH: dict[str, Any] = {
    "auth_method": "api_key",
    "user_id": "test-user",
    "scopes": [],
}


def _set_scopes(scopes: list[str]) -> None:
    _API_KEY_AUTH["scopes"] = list(scopes)


def _set_mode(mode: str) -> None:
    """Switch auth mode: 'api_key' or 'reject_jwt'."""
    _AUTH_MODE["mode"] = mode


async def _controlled_dispatch(
    request: Request,
    call_next: RequestResponseEndpoint,
) -> Response:
    """Dispatches based on current _AUTH_MODE.

    api_key: injects API-key auth dict into request.state.auth.
    reject_jwt: leaves auth unset (None) — simulates JWT/cookie path.
    """
    if _AUTH_MODE["mode"] == "api_key":
        request.state.auth = dict(_API_KEY_AUTH)
    # In reject_jwt mode: do not set request.state.auth (stays None)
    return await call_next(request)


async def _resolve_user_id_override(request: Request) -> str:
    """Overrides resolve_user_id.

    api_key mode: returns "test-user" (JWT verification bypassed).
    reject_jwt mode: raise 401 to simulate invalid JWT in cloud mode.
    """
    if _AUTH_MODE["mode"] == "reject_jwt":
        raise HTTPException(status_code=401, detail="Invalid authentication token")
    return "test-user"


def _make_mock_store() -> AsyncMock:
    store = AsyncMock()
    store.list_connections.return_value = []
    store.list_api_keys.return_value = []
    store.get_connection.return_value = None
    store.user_id = "test-user"
    mock_settings = AsyncMock()
    mock_settings.default_timeout_seconds = 30
    mock_settings.blocked_tables = []
    store.load_settings.return_value = mock_settings
    return store


async def _fake_get_store() -> AsyncMock:
    return _make_mock_store()


def _find_middleware(middleware_type: type) -> object | None:
    """Walk app.middleware_stack to find a middleware instance by type."""
    current = app.middleware_stack
    while current is not None:
        if isinstance(current, middleware_type):
            return current
        current = getattr(current, "app", None)
    return None


# ─── Single module-scoped client ─────────────────────────────────────────────


@pytest.fixture(scope="module")
def client():
    """Single TestClient shared across all tests.

    Auth mode is controlled per-test via _set_mode() and _set_scopes().
    """
    app.dependency_overrides[get_store] = _fake_get_store
    app.dependency_overrides[resolve_user_id] = _resolve_user_id_override

    with (
        patch("gateway.main.init_db", new_callable=AsyncMock),
        patch("gateway.main.close_db", new_callable=AsyncMock),
        patch("gateway.main.get_session_factory", return_value=AsyncMock()),
        patch("gateway.main._mcp_session_manager", None),
    ):
        _client = TestClient(app, raise_server_exceptions=False)
        with _client:
            auth_middleware = _find_middleware(APIKeyAuthMiddleware)
            if auth_middleware is not None:
                auth_middleware.dispatch_func = _controlled_dispatch  # type: ignore[union-attr]
            rate_limiter = _find_middleware(RateLimitMiddleware)
            if rate_limiter is not None:
                # Clear accumulated hits from prior test modules to prevent
                # false 429 responses in this test module.
                rate_limiter._general_hits.clear()  # type: ignore[union-attr]
                rate_limiter._expensive_hits.clear()  # type: ignore[union-attr]
                rate_limiter._auth_hits.clear()  # type: ignore[union-attr]
            yield _client

    app.dependency_overrides.pop(get_store, None)
    app.dependency_overrides.pop(resolve_user_id, None)


FAKE_BEARER_HEADERS = {"Authorization": "Bearer fake.jwt.token"}


# ─── TestJWTEnforcementCacheEndpoints ─────────────────────────────────────────


class TestJWTEnforcementCacheEndpoints:
    """Cache/pool/schema-cache endpoints enforce UserID dependency (returns 401 for bad JWT)."""

    def test_cache_stats_rejects_invalid_jwt(self, client):
        _set_mode("reject_jwt")
        response = client.get("/api/cache/stats", headers=FAKE_BEARER_HEADERS)
        assert response.status_code == 401

    def test_invalidate_cache_rejects_invalid_jwt(self, client):
        _set_mode("reject_jwt")
        response = client.post("/api/cache/invalidate", headers=FAKE_BEARER_HEADERS)
        assert response.status_code == 401

    def test_pool_stats_rejects_invalid_jwt(self, client):
        _set_mode("reject_jwt")
        response = client.get("/api/pool/stats", headers=FAKE_BEARER_HEADERS)
        assert response.status_code == 401

    def test_schema_cache_stats_rejects_invalid_jwt(self, client):
        _set_mode("reject_jwt")
        response = client.get("/api/schema-cache/stats", headers=FAKE_BEARER_HEADERS)
        assert response.status_code == 401

    def test_invalidate_schema_cache_rejects_invalid_jwt(self, client):
        _set_mode("reject_jwt")
        response = client.post("/api/schema-cache/invalidate", headers=FAKE_BEARER_HEADERS)
        assert response.status_code == 401


# ─── TestJWTEnforcementConnectionEndpoints ────────────────────────────────────


class TestJWTEnforcementConnectionEndpoints:
    """Connection endpoints without StoreD enforce UserID dependency."""

    def test_connections_health_rejects_invalid_jwt(self, client):
        _set_mode("reject_jwt")
        response = client.get("/api/connections/health", headers=FAKE_BEARER_HEADERS)
        assert response.status_code == 401

    def test_connection_health_rejects_invalid_jwt(self, client):
        _set_mode("reject_jwt")
        response = client.get("/api/connections/myconn/health", headers=FAKE_BEARER_HEADERS)
        assert response.status_code == 401

    def test_connection_health_history_rejects_invalid_jwt(self, client):
        _set_mode("reject_jwt")
        response = client.get("/api/connections/myconn/health/history", headers=FAKE_BEARER_HEADERS)
        assert response.status_code == 401

    def test_network_info_rejects_invalid_jwt(self, client):
        _set_mode("reject_jwt")
        response = client.get("/api/network/info", headers=FAKE_BEARER_HEADERS)
        assert response.status_code == 401

    def test_parse_url_rejects_invalid_jwt(self, client):
        _set_mode("reject_jwt")
        response = client.post(
            "/api/connections/parse-url",
            json={"url": "postgresql://user:pass@host:5432/db"},
            headers=FAKE_BEARER_HEADERS,
        )
        assert response.status_code == 401

    def test_test_credentials_rejects_invalid_jwt(self, client):
        _set_mode("reject_jwt")
        response = client.post(
            "/api/connections/test-credentials",
            json={"db_type": "postgres", "host": "localhost"},
            headers=FAKE_BEARER_HEADERS,
        )
        assert response.status_code == 401

    def test_validate_url_rejects_invalid_jwt(self, client):
        _set_mode("reject_jwt")
        response = client.post(
            "/api/connections/validate-url",
            json={"connection_string": "postgresql://user:pass@host/db", "db_type": "postgres"},
            headers=FAKE_BEARER_HEADERS,
        )
        assert response.status_code == 401

    def test_build_url_rejects_invalid_jwt(self, client):
        _set_mode("reject_jwt")
        response = client.post(
            "/api/connections/build-url",
            json={"db_type": "postgres", "host": "host", "database": "db"},
            headers=FAKE_BEARER_HEADERS,
        )
        assert response.status_code == 401

    def test_connector_capabilities_rejects_invalid_jwt(self, client):
        _set_mode("reject_jwt")
        response = client.get("/api/connectors/capabilities", headers=FAKE_BEARER_HEADERS)
        assert response.status_code == 401


# ─── TestJWTEnforcementBudgetEndpoints ────────────────────────────────────────


class TestJWTEnforcementBudgetEndpoints:
    """Budget endpoints enforce UserID dependency."""

    def test_create_budget_rejects_invalid_jwt(self, client):
        _set_mode("reject_jwt")
        response = client.post(
            "/api/budget",
            json={"session_id": "sess-1", "budget_usd": 5.0},
            headers=FAKE_BEARER_HEADERS,
        )
        assert response.status_code == 401

    def test_get_budget_rejects_invalid_jwt(self, client):
        _set_mode("reject_jwt")
        response = client.get("/api/budget/sess-1", headers=FAKE_BEARER_HEADERS)
        assert response.status_code == 401

    def test_list_budgets_rejects_invalid_jwt(self, client):
        _set_mode("reject_jwt")
        response = client.get("/api/budget", headers=FAKE_BEARER_HEADERS)
        assert response.status_code == 401

    def test_delete_budget_rejects_invalid_jwt(self, client):
        _set_mode("reject_jwt")
        response = client.delete("/api/budget/sess-1", headers=FAKE_BEARER_HEADERS)
        assert response.status_code == 401


# ─── TestJWTEnforcementSandboxEndpoints ───────────────────────────────────────


class TestJWTEnforcementSandboxEndpoints:
    """Sandbox list/detail endpoints enforce UserID dependency."""

    def test_list_sandboxes_rejects_invalid_jwt(self, client):
        _set_mode("reject_jwt")
        response = client.get("/api/sandboxes", headers=FAKE_BEARER_HEADERS)
        assert response.status_code == 401

    def test_get_sandbox_detail_rejects_invalid_jwt(self, client):
        _set_mode("reject_jwt")
        response = client.get("/api/sandboxes/some-id", headers=FAKE_BEARER_HEADERS)
        assert response.status_code == 401


# ─── TestCredentialExportScopeEscalation ─────────────────────────────────────


class TestCredentialExportScopeEscalation:
    """POST /connections/export with include_credentials=true requires admin scope."""

    def test_export_with_credentials_returns_403_for_write_only_key(self, client):
        """write scope is not sufficient to export credentials — admin required."""
        _set_mode("api_key")
        _set_scopes(["write"])
        response = client.post(
            "/api/connections/export",
            json={"include_credentials": True, "confirm": True},
        )
        assert response.status_code == 403

    def test_export_without_credentials_succeeds_with_write_scope(self, client):
        """Exporting without credentials is fine at write scope."""
        _set_mode("api_key")
        _set_scopes(["write"])
        response = client.post(
            "/api/connections/export",
            json={"include_credentials": False, "confirm": True},
        )
        assert response.status_code != 403

    def test_export_with_credentials_succeeds_with_admin_scope(self, client):
        """admin scope satisfies the additional credential export gate."""
        _set_mode("api_key")
        _set_scopes(["admin", "write"])
        response = client.post(
            "/api/connections/export",
            json={"include_credentials": True, "confirm": True},
        )
        assert response.status_code != 403

    def test_export_without_write_scope_returns_403(self, client):
        """Base write scope check still enforced even without include_credentials."""
        _set_mode("api_key")
        _set_scopes(["read"])
        response = client.post(
            "/api/connections/export",
            json={"include_credentials": False, "confirm": True},
        )
        assert response.status_code == 403
