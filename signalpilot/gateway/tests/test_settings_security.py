"""Tests for settings endpoint security: scope enforcement and secret redaction."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import Request, Response
from fastapi.testclient import TestClient
from starlette.middleware.base import RequestResponseEndpoint

from gateway.api.deps import get_store
from gateway.main import app
from gateway.middleware import APIKeyAuthMiddleware
from gateway.models import GatewaySettings, SandboxProvider

# ─── Shared auth state ────────────────────────────────────────────────────────

_CURRENT_AUTH: dict[str, Any] = {
    "auth_method": "api_key",
    "user_id": "test-user",
    "scopes": [],
}


async def _controlled_dispatch(
    request: Request,
    call_next: RequestResponseEndpoint,
) -> Response:
    """Injects _CURRENT_AUTH into request.state on every request."""
    request.state.auth = dict(_CURRENT_AUTH)
    return await call_next(request)


def _set_scopes(scopes: list[str]) -> None:
    _CURRENT_AUTH["scopes"] = list(scopes)


# ─── Store mock ──────────────────────────────────────────────────────────────

_REAL_API_KEY = "sp_realkey_abc123"
_REAL_SANDBOX_API_KEY = "sp_sandbox_xyz789"

# Module-level mock store — settings are swapped per test class as needed.
_mock_store = AsyncMock()


def _configure_store_with_keys(api_key: str | None, sandbox_api_key: str | None) -> None:
    """Reconfigure the module-level mock store with specific key values."""
    settings = GatewaySettings(
        sandbox_manager_url="http://localhost:8180",
        sandbox_provider=SandboxProvider.local,
        sandbox_api_key=sandbox_api_key,
        default_row_limit=10_000,
        default_budget_usd=10.0,
        default_timeout_seconds=30,
        max_concurrent_sandboxes=10,
        blocked_tables=[],
        gateway_url="http://localhost:3300",
        api_key=api_key,
    )
    _mock_store.load_settings.return_value = settings
    _mock_store.save_settings = AsyncMock()


def _find_auth_middleware() -> APIKeyAuthMiddleware | None:
    """Walk app.middleware_stack to find the APIKeyAuthMiddleware instance."""
    current = app.middleware_stack
    while current is not None:
        if isinstance(current, APIKeyAuthMiddleware):
            return current
        current = getattr(current, "app", None)
    return None


# ─── Module-scoped client fixture ────────────────────────────────────────────


@pytest.fixture(scope="module")
def client():
    """Single TestClient for all settings security tests."""
    _configure_store_with_keys(
        api_key=_REAL_API_KEY,
        sandbox_api_key=_REAL_SANDBOX_API_KEY,
    )

    async def _fake_get_store() -> AsyncMock:
        return _mock_store

    app.dependency_overrides[get_store] = _fake_get_store

    with (
        patch("gateway.main.init_db", new_callable=AsyncMock),
        patch("gateway.main.close_db", new_callable=AsyncMock),
        patch("gateway.main.get_session_factory", return_value=AsyncMock()),
        patch("gateway.main._mcp_session_manager", None),
    ):
        _client = TestClient(app, raise_server_exceptions=False)
        with _client:
            middleware_instance = _find_auth_middleware()
            if middleware_instance is not None:
                middleware_instance.dispatch_func = _controlled_dispatch
            yield _client

    app.dependency_overrides.pop(get_store, None)


# ─── TestGetSettingsAdminScopeRequired ───────────────────────────────────────


class TestGetSettingsAdminScopeRequired:
    """GET /api/settings must require admin scope."""

    def test_get_settings_returns_403_without_any_scope(self, client):
        _set_scopes([])
        response = client.get("/api/settings")
        assert response.status_code == 403

    def test_get_settings_returns_403_with_read_scope_only(self, client):
        _set_scopes(["read"])
        response = client.get("/api/settings")
        assert response.status_code == 403

    def test_get_settings_returns_403_with_write_scope_only(self, client):
        _set_scopes(["write"])
        response = client.get("/api/settings")
        assert response.status_code == 403

    def test_get_settings_returns_403_with_query_scope_only(self, client):
        _set_scopes(["query"])
        response = client.get("/api/settings")
        assert response.status_code == 403

    def test_get_settings_returns_200_with_admin_scope(self, client):
        _set_scopes(["admin"])
        response = client.get("/api/settings")
        assert response.status_code == 200

    def test_get_settings_passes_with_admin_and_other_scopes(self, client):
        _set_scopes(["read", "admin"])
        response = client.get("/api/settings")
        assert response.status_code == 200


# ─── TestGetSettingsSecretRedaction ──────────────────────────────────────────


class TestGetSettingsSecretRedaction:
    """GET /api/settings must return masked values for api_key and sandbox_api_key."""

    def test_get_settings_masks_api_key(self, client):
        _set_scopes(["admin"])
        response = client.get("/api/settings")
        assert response.status_code == 200
        data = response.json()
        assert data["api_key"] == "****"

    def test_get_settings_masks_sandbox_api_key(self, client):
        _set_scopes(["admin"])
        response = client.get("/api/settings")
        assert response.status_code == 200
        data = response.json()
        assert data["sandbox_api_key"] == "****"

    def test_get_settings_does_not_expose_real_api_key(self, client):
        _set_scopes(["admin"])
        response = client.get("/api/settings")
        assert response.status_code == 200
        data = response.json()
        assert _REAL_API_KEY not in str(data)

    def test_get_settings_does_not_expose_real_sandbox_api_key(self, client):
        _set_scopes(["admin"])
        response = client.get("/api/settings")
        assert response.status_code == 200
        data = response.json()
        assert _REAL_SANDBOX_API_KEY not in str(data)

    def test_get_settings_returns_non_secret_fields_unchanged(self, client):
        _set_scopes(["admin"])
        response = client.get("/api/settings")
        assert response.status_code == 200
        data = response.json()
        assert data["sandbox_manager_url"] == "http://localhost:8180"
        assert data["default_row_limit"] == 10_000
        assert data["gateway_url"] == "http://localhost:3300"


# ─── TestGetSettingsNullRedaction ─────────────────────────────────────────────


class TestGetSettingsNullRedaction:
    """GET /api/settings returns None (not '****') when secret fields are not set."""

    def test_null_api_key_stays_null(self, client):
        """When api_key is None in the store, GET /settings returns null, not '****'."""
        _configure_store_with_keys(api_key=None, sandbox_api_key=None)
        _set_scopes(["admin"])
        response = client.get("/api/settings")
        assert response.status_code == 200
        data = response.json()
        assert data["api_key"] is None

    def test_null_sandbox_api_key_stays_null(self, client):
        """When sandbox_api_key is None, GET /settings returns null, not '****'."""
        _configure_store_with_keys(api_key=None, sandbox_api_key=None)
        _set_scopes(["admin"])
        response = client.get("/api/settings")
        assert response.status_code == 200
        data = response.json()
        assert data["sandbox_api_key"] is None

    def teardown_method(self, _method: Any) -> None:
        """Restore the store to have real keys after null-key tests."""
        _configure_store_with_keys(
            api_key=_REAL_API_KEY,
            sandbox_api_key=_REAL_SANDBOX_API_KEY,
        )


# ─── TestPutSettingsSecretRedaction ──────────────────────────────────────────


class TestPutSettingsSecretRedaction:
    """PUT /api/settings must return masked values in response even when accepting real values."""

    _SETTINGS_PAYLOAD: dict[str, Any] = {
        "sandbox_manager_url": "http://localhost:8180",
        "sandbox_provider": "local",
        "sandbox_api_key": _REAL_SANDBOX_API_KEY,
        "default_row_limit": 10_000,
        "default_budget_usd": 10.0,
        "default_timeout_seconds": 30,
        "max_concurrent_sandboxes": 10,
        "blocked_tables": [],
        "gateway_url": "http://localhost:3300",
        "api_key": _REAL_API_KEY,
    }

    def test_put_settings_returns_200_with_admin_scope(self, client):
        _set_scopes(["admin"])
        response = client.put("/api/settings", json=self._SETTINGS_PAYLOAD)
        assert response.status_code == 200

    def test_put_settings_masks_api_key_in_response(self, client):
        _set_scopes(["admin"])
        response = client.put("/api/settings", json=self._SETTINGS_PAYLOAD)
        assert response.status_code == 200
        data = response.json()
        assert data["api_key"] == "****"

    def test_put_settings_masks_sandbox_api_key_in_response(self, client):
        _set_scopes(["admin"])
        response = client.put("/api/settings", json=self._SETTINGS_PAYLOAD)
        assert response.status_code == 200
        data = response.json()
        assert data["sandbox_api_key"] == "****"

    def test_put_settings_does_not_echo_real_api_key(self, client):
        _set_scopes(["admin"])
        response = client.put("/api/settings", json=self._SETTINGS_PAYLOAD)
        assert response.status_code == 200
        assert _REAL_API_KEY not in str(response.json())

    def test_put_settings_does_not_echo_real_sandbox_api_key(self, client):
        _set_scopes(["admin"])
        response = client.put("/api/settings", json=self._SETTINGS_PAYLOAD)
        assert response.status_code == 200
        assert _REAL_SANDBOX_API_KEY not in str(response.json())

    def test_put_settings_returns_403_without_admin_scope(self, client):
        _set_scopes(["read"])
        response = client.put("/api/settings", json=self._SETTINGS_PAYLOAD)
        assert response.status_code == 403

    def test_put_settings_mask_roundtrip_preserves_real_keys(self, client):
        """PUT with '****' should preserve existing keys, not overwrite them."""
        _configure_store_with_keys(
            api_key=_REAL_API_KEY,
            sandbox_api_key=_REAL_SANDBOX_API_KEY,
        )
        _set_scopes(["admin"])
        payload = dict(self._SETTINGS_PAYLOAD)
        payload["api_key"] = "****"
        payload["sandbox_api_key"] = "****"
        response = client.put("/api/settings", json=payload)
        assert response.status_code == 200
        # Verify save_settings was called with real keys, not mask
        saved = _mock_store.save_settings.call_args[0][0]
        assert saved.api_key == _REAL_API_KEY
        assert saved.sandbox_api_key == _REAL_SANDBOX_API_KEY
