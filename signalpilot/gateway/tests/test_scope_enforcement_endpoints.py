"""Integration tests for scope enforcement on protected endpoints.

Tests that each protected endpoint returns 403 when called with an API key
that lacks the required scope, and succeeds (or returns a non-403 error)
when called with the correct scope.

Strategy:
- Starlette's BaseHTTPMiddleware captures self.dispatch as dispatch_func at
  __init__ time. Patching the class method after the app is built does not
  affect existing instances. The fix is to patch dispatch_func on the
  middleware INSTANCE directly after the TestClient starts the app.
- A shared _CURRENT_AUTH dict allows each test to set the auth state for its
  request without recreating the client.
- init_db/close_db are mocked to avoid needing DATABASE_URL.
- get_store is overridden to avoid DB calls in handlers.
"""

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


def _make_mock_store() -> AsyncMock:
    store = AsyncMock()
    store.list_connections.return_value = []
    store.list_projects.return_value = []
    store.list_api_keys.return_value = []
    store.get_connection.return_value = None
    store.get_project.return_value = None
    store.save_settings = AsyncMock()
    mock_settings = AsyncMock()
    mock_settings.default_timeout_seconds = 30
    mock_settings.blocked_tables = []
    store.load_settings.return_value = mock_settings
    return store


async def _fake_get_store() -> AsyncMock:
    return _make_mock_store()


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
    """Single TestClient for all scope enforcement tests.

    Uses scope='module' to build the ASGI stack once and reuse it.
    The auth state is controlled per-test via _set_scopes().
    """
    app.dependency_overrides[get_store] = _fake_get_store

    with (
        patch("gateway.main.init_db", new_callable=AsyncMock),
        patch("gateway.main.close_db", new_callable=AsyncMock),
        patch("gateway.main.get_session_factory", return_value=AsyncMock()),
    ):
        _client = TestClient(app, raise_server_exceptions=False)
        with _client:
            # Patch the dispatch_func on the instance (not the class).
            # BaseHTTPMiddleware captures self.dispatch at __init__ time, so
            # class-level patching doesn't work after the app is built.
            middleware_instance = _find_auth_middleware()
            if middleware_instance is not None:
                middleware_instance.dispatch_func = _controlled_dispatch
            yield _client

    app.dependency_overrides.pop(get_store, None)


# ─── TestConnectionsWriteScope ────────────────────────────────────────────────


class TestConnectionsWriteScope:
    """POST/PUT/DELETE connections require 'write' scope."""

    def test_add_connection_returns_403_without_write_scope(self, client):
        _set_scopes([])
        response = client.post("/api/connections", json={
            "name": "test-conn", "db_type": "postgres",
        })
        assert response.status_code == 403

    def test_add_connection_passes_with_write_scope(self, client):
        _set_scopes(["write"])
        response = client.post("/api/connections", json={
            "name": "scope-test-write",
            "db_type": "postgres",
            "host": "db.example.com",
            "port": 5432,
            "database": "testdb",
            "username": "user",
        })
        assert response.status_code != 403

    def test_edit_connection_returns_403_without_write_scope(self, client):
        _set_scopes([])
        response = client.put("/api/connections/my-conn", json={})
        assert response.status_code == 403

    def test_edit_connection_passes_with_write_scope(self, client):
        _set_scopes(["write"])
        response = client.put("/api/connections/nonexistent-conn", json={})
        assert response.status_code != 403

    def test_remove_connection_returns_403_without_write_scope(self, client):
        _set_scopes([])
        response = client.delete("/api/connections/my-conn")
        assert response.status_code == 403

    def test_remove_connection_passes_with_write_scope(self, client):
        _set_scopes(["write"])
        response = client.delete("/api/connections/nonexistent-conn")
        assert response.status_code != 403

    def test_clone_connection_returns_403_without_write_scope(self, client):
        _set_scopes([])
        response = client.post(
            "/api/connections/my-conn/clone", params={"new_name": "clone-name"}
        )
        assert response.status_code == 403

    def test_clone_connection_passes_with_write_scope(self, client):
        _set_scopes(["write"])
        response = client.post(
            "/api/connections/nonexistent-conn/clone", params={"new_name": "clone-name"}
        )
        assert response.status_code != 403

    def test_export_connections_returns_403_without_write_scope(self, client):
        _set_scopes([])
        response = client.post("/api/connections/export", json={
            "include_credentials": False, "confirm": True,
        })
        assert response.status_code == 403

    def test_export_connections_passes_with_write_scope(self, client):
        _set_scopes(["write"])
        response = client.post("/api/connections/export", json={
            "include_credentials": False, "confirm": True,
        })
        assert response.status_code != 403

    def test_import_connections_returns_403_without_write_scope(self, client):
        _set_scopes([])
        response = client.post("/api/connections/import", json={
            "connections": []
        })
        assert response.status_code == 403

    def test_import_connections_passes_with_write_scope(self, client):
        _set_scopes(["write"])
        response = client.post("/api/connections/import", json={
            "connections": []
        })
        assert response.status_code != 403


# ─── TestSchemaRefreshWriteScope ──────────────────────────────────────────────


class TestSchemaRefreshWriteScope:
    """Schema refresh and warmup require 'write' scope."""

    def test_refresh_schema_returns_403_without_write_scope(self, client):
        _set_scopes([])
        response = client.post("/api/connections/my-conn/schema/refresh")
        assert response.status_code == 403

    def test_refresh_schema_passes_with_write_scope(self, client):
        _set_scopes(["write"])
        response = client.post("/api/connections/nonexistent/schema/refresh")
        assert response.status_code != 403

    def test_warmup_all_schemas_returns_403_without_write_scope(self, client):
        _set_scopes([])
        response = client.post("/api/connections/schema/warmup")
        assert response.status_code == 403

    def test_warmup_all_schemas_passes_with_write_scope(self, client):
        _set_scopes(["write"])
        response = client.post("/api/connections/schema/warmup")
        assert response.status_code != 403


# ─── TestTestCredentialsWriteScope ───────────────────────────────────────────


class TestTestCredentialsWriteScope:
    """test-credentials requires 'write' scope (primary SSRF vector)."""

    def test_test_credentials_returns_403_without_write_scope(self, client):
        _set_scopes([])
        response = client.post("/api/connections/test-credentials", json={
            "name": "test", "db_type": "postgres",
            "host": "localhost", "port": 5432,
        })
        assert response.status_code == 403

    def test_test_credentials_passes_with_write_scope(self, client):
        """With write scope, request reaches the handler (non-403 response expected)."""
        _set_scopes(["write"])
        response = client.post("/api/connections/test-credentials", json={
            "name": "test", "db_type": "postgres",
            "host": "db.example.com", "port": 5432,
        })
        assert response.status_code != 403


# ─── TestConnectionReadScope ──────────────────────────────────────────────────


class TestConnectionReadScope:
    """test_connection and diagnose_connection require 'read' scope."""

    def test_test_connection_returns_403_without_read_scope(self, client):
        _set_scopes([])
        response = client.post("/api/connections/my-conn/test")
        assert response.status_code == 403

    def test_test_connection_passes_with_read_scope(self, client):
        _set_scopes(["read"])
        response = client.post("/api/connections/nonexistent-conn/test")
        assert response.status_code != 403

    def test_diagnose_connection_returns_403_without_read_scope(self, client):
        _set_scopes([])
        response = client.post("/api/connections/my-conn/diagnose")
        assert response.status_code == 403

    def test_diagnose_connection_passes_with_read_scope(self, client):
        _set_scopes(["read"])
        response = client.post("/api/connections/nonexistent-conn/diagnose")
        assert response.status_code != 403


# ─── TestSandboxExecuteScope ──────────────────────────────────────────────────


class TestSandboxExecuteScope:
    """Sandbox create/delete/execute require 'execute' scope."""

    def test_create_sandbox_returns_403_without_execute_scope(self, client):
        _set_scopes([])
        response = client.post("/api/sandboxes", json={
            "connection_name": "test-conn", "label": "test sandbox",
        })
        assert response.status_code == 403

    def test_create_sandbox_passes_with_execute_scope(self, client):
        _set_scopes(["execute"])
        response = client.post("/api/sandboxes", json={
            "connection_name": "test-conn", "label": "test sandbox",
        })
        assert response.status_code != 403

    def test_kill_sandbox_returns_403_without_execute_scope(self, client):
        _set_scopes([])
        response = client.delete("/api/sandboxes/some-sandbox-id")
        assert response.status_code == 403

    def test_kill_sandbox_passes_with_execute_scope(self, client):
        _set_scopes(["execute"])
        response = client.delete("/api/sandboxes/nonexistent-sandbox-id")
        assert response.status_code != 403

    def test_execute_in_sandbox_returns_403_without_execute_scope(self, client):
        _set_scopes([])
        response = client.post("/api/sandboxes/some-sandbox-id/execute", json={
            "sql": "SELECT 1",
        })
        assert response.status_code == 403

    def test_execute_in_sandbox_passes_with_execute_scope(self, client):
        _set_scopes(["execute"])
        response = client.post("/api/sandboxes/nonexistent-sandbox-id/execute", json={
            "sql": "SELECT 1",
        })
        assert response.status_code != 403


# ─── TestQueryScope ───────────────────────────────────────────────────────────


class TestQueryScope:
    """POST /api/query and POST /api/query/explain require 'query' scope."""

    def test_query_database_returns_403_without_query_scope(self, client):
        _set_scopes([])
        response = client.post("/api/query", json={
            "connection_name": "test-conn",
            "sql": "SELECT 1",
        })
        assert response.status_code == 403

    def test_query_database_passes_with_query_scope(self, client):
        _set_scopes(["query"])
        response = client.post("/api/query", json={
            "connection_name": "nonexistent-conn",
            "sql": "SELECT 1",
        })
        assert response.status_code != 403

    def test_explain_query_returns_403_without_query_scope(self, client):
        _set_scopes([])
        response = client.post("/api/query/explain", json={
            "connection_name": "test-conn",
            "sql": "SELECT 1",
        })
        assert response.status_code == 403

    def test_explain_query_passes_with_query_scope(self, client):
        _set_scopes(["query"])
        response = client.post("/api/query/explain", json={
            "connection_name": "nonexistent-conn",
            "sql": "SELECT 1",
        })
        assert response.status_code != 403


# ─── TestSettingsAdminScope ───────────────────────────────────────────────────


class TestSettingsAdminScope:
    """PUT /api/settings requires 'admin' scope."""

    def test_update_settings_returns_403_without_admin_scope(self, client):
        _set_scopes([])
        response = client.put("/api/settings", json={
            "sandbox_manager_url": "http://localhost:8180",
            "sandbox_provider": "local",
            "default_row_limit": 10000,
            "default_budget_usd": 10.0,
            "default_timeout_seconds": 30,
            "max_concurrent_sandboxes": 10,
            "blocked_tables": [],
            "gateway_url": "http://localhost:3300",
        })
        assert response.status_code == 403

    def test_update_settings_passes_with_admin_scope(self, client):
        _set_scopes(["admin"])
        response = client.put("/api/settings", json={
            "sandbox_manager_url": "http://localhost:8180",
            "sandbox_provider": "local",
            "default_row_limit": 10000,
            "default_budget_usd": 10.0,
            "default_timeout_seconds": 30,
            "max_concurrent_sandboxes": 10,
            "blocked_tables": [],
            "gateway_url": "http://localhost:3300",
        })
        assert response.status_code != 403


# ─── TestProjectsWriteScope ───────────────────────────────────────────────────


class TestProjectsWriteScope:
    """Project create/update/delete/scan require 'write' scope."""

    def test_add_project_returns_403_without_write_scope(self, client):
        _set_scopes([])
        response = client.post("/api/projects", json={"name": "my-project"})
        assert response.status_code == 403

    def test_add_project_passes_with_write_scope(self, client):
        _set_scopes(["write"])
        response = client.post("/api/projects", json={"name": "scope-test-project"})
        assert response.status_code != 403

    def test_edit_project_returns_403_without_write_scope(self, client):
        _set_scopes([])
        response = client.put("/api/projects/my-project", json={})
        assert response.status_code == 403

    def test_edit_project_passes_with_write_scope(self, client):
        _set_scopes(["write"])
        response = client.put("/api/projects/nonexistent-project", json={})
        assert response.status_code != 403

    def test_remove_project_returns_403_without_write_scope(self, client):
        _set_scopes([])
        response = client.delete("/api/projects/my-project")
        assert response.status_code == 403

    def test_remove_project_passes_with_write_scope(self, client):
        _set_scopes(["write"])
        response = client.delete("/api/projects/nonexistent-project")
        assert response.status_code != 403

    def test_scan_project_returns_403_without_write_scope(self, client):
        _set_scopes([])
        response = client.post("/api/projects/my-project/scan")
        assert response.status_code == 403

    def test_scan_project_passes_with_write_scope(self, client):
        _set_scopes(["write"])
        response = client.post("/api/projects/nonexistent-project/scan")
        assert response.status_code != 403


# ─── TestSandboxReadScope ─────────────────────────────────────────────────────


class TestSandboxReadScope:
    """GET /api/sandboxes and GET /api/sandboxes/{id} require 'read' scope."""

    def test_list_sandboxes_returns_403_without_read_scope(self, client):
        _set_scopes([])
        response = client.get("/api/sandboxes")
        assert response.status_code == 403

    def test_list_sandboxes_passes_with_read_scope(self, client):
        _set_scopes(["read"])
        response = client.get("/api/sandboxes")
        assert response.status_code != 403

    def test_list_sandboxes_returns_403_with_only_execute_scope(self, client):
        _set_scopes(["execute"])
        response = client.get("/api/sandboxes")
        assert response.status_code == 403

    def test_get_sandbox_detail_returns_403_without_read_scope(self, client):
        _set_scopes([])
        response = client.get("/api/sandboxes/some-sandbox-id")
        assert response.status_code == 403

    def test_get_sandbox_detail_passes_with_read_scope(self, client):
        _set_scopes(["read"])
        response = client.get("/api/sandboxes/nonexistent-sandbox-id")
        assert response.status_code != 403

    def test_get_sandbox_detail_returns_403_with_only_execute_scope(self, client):
        _set_scopes(["execute"])
        response = client.get("/api/sandboxes/some-sandbox-id")
        assert response.status_code == 403


# ─── TestGetSettingsAdminScopeEnforcement ─────────────────────────────────────


class TestGetSettingsAdminScopeEnforcement:
    """GET /api/settings requires 'admin' scope."""

    def test_get_settings_returns_403_without_admin_scope(self, client):
        _set_scopes([])
        response = client.get("/api/settings")
        assert response.status_code == 403

    def test_get_settings_passes_with_admin_scope(self, client):
        _set_scopes(["admin"])
        response = client.get("/api/settings")
        assert response.status_code != 403

    def test_get_settings_returns_403_with_only_read_scope(self, client):
        _set_scopes(["read"])
        response = client.get("/api/settings")
        assert response.status_code == 403


# ─── TestUrlUtilityReadScope ──────────────────────────────────────────────────


class TestUrlUtilityReadScope:
    """parse-url, validate-url, build-url require 'read' scope (R12)."""

    def test_parse_url_returns_403_without_read_scope(self, client):
        _set_scopes([])
        response = client.post("/api/connections/parse-url", json={
            "url": "postgresql://user:pass@db.example.com:5432/mydb",
            "db_type": "postgres",
        })
        assert response.status_code == 403

    def test_parse_url_passes_with_read_scope(self, client):
        _set_scopes(["read"])
        response = client.post("/api/connections/parse-url", json={
            "url": "postgresql://user:pass@db.example.com:5432/mydb",
            "db_type": "postgres",
        })
        assert response.status_code != 403

    def test_validate_url_returns_403_without_read_scope(self, client):
        _set_scopes([])
        response = client.post("/api/connections/validate-url", json={
            "connection_string": "postgresql://user:pass@db.example.com:5432/mydb",
            "db_type": "postgres",
        })
        assert response.status_code == 403

    def test_validate_url_passes_with_read_scope(self, client):
        _set_scopes(["read"])
        response = client.post("/api/connections/validate-url", json={
            "connection_string": "postgresql://user:pass@db.example.com:5432/mydb",
            "db_type": "postgres",
        })
        assert response.status_code != 403

    def test_build_url_returns_403_without_read_scope(self, client):
        _set_scopes([])
        response = client.post("/api/connections/build-url", json={
            "db_type": "postgres",
            "host": "db.example.com",
            "port": 5432,
            "database": "mydb",
            "username": "user",
            "password": "pass",
        })
        assert response.status_code == 403

    def test_build_url_passes_with_read_scope(self, client):
        _set_scopes(["read"])
        response = client.post("/api/connections/build-url", json={
            "db_type": "postgres",
            "host": "db.example.com",
            "port": 5432,
            "database": "mydb",
            "username": "user",
            "password": "pass",
        })
        assert response.status_code != 403


# ─── TestAuditAdminScope ──────────────────────────────────────────────────────


class TestAuditAdminScope:
    """GET /api/audit and GET /api/audit/export require 'admin' scope."""

    def test_get_audit_returns_403_without_admin_scope(self, client):
        _set_scopes([])
        response = client.get("/api/audit")
        assert response.status_code == 403

    def test_get_audit_returns_403_with_only_read_scope(self, client):
        _set_scopes(["read"])
        response = client.get("/api/audit")
        assert response.status_code == 403

    def test_get_audit_passes_with_admin_scope(self, client):
        _set_scopes(["admin"])
        response = client.get("/api/audit")
        assert response.status_code != 403

    def test_export_audit_returns_403_without_admin_scope(self, client):
        _set_scopes([])
        response = client.get("/api/audit/export")
        assert response.status_code == 403

    def test_export_audit_passes_with_admin_scope(self, client):
        _set_scopes(["admin"])
        response = client.get("/api/audit/export")
        assert response.status_code != 403


# ─── TestFilesBrowseReadScope ─────────────────────────────────────────────────


class TestFilesBrowseReadScope:
    """GET /api/files/browse requires 'read' scope."""

    def test_browse_files_returns_403_without_read_scope(self, client):
        _set_scopes([])
        response = client.get("/api/files/browse")
        assert response.status_code == 403

    def test_browse_files_passes_with_read_scope(self, client):
        _set_scopes(["read"])
        response = client.get("/api/files/browse")
        assert response.status_code != 403


# ─── TestNetworkInfoAdminScope ────────────────────────────────────────────────


class TestNetworkInfoAdminScope:
    """GET /api/network/info requires 'admin' scope."""

    def test_network_info_returns_403_without_admin_scope(self, client):
        _set_scopes([])
        response = client.get("/api/network/info")
        assert response.status_code == 403

    def test_network_info_returns_403_with_only_read_scope(self, client):
        _set_scopes(["read"])
        response = client.get("/api/network/info")
        assert response.status_code == 403

    def test_network_info_passes_with_admin_scope(self, client):
        _set_scopes(["admin"])
        response = client.get("/api/network/info")
        assert response.status_code != 403


# ─── TestConnectionsGetReadScope ─────────────────────────────────────────────


class TestConnectionsGetReadScope:
    """GET connection list/detail/health/stats require 'read' scope."""

    def test_list_connections_returns_403_without_read_scope(self, client):
        _set_scopes([])
        response = client.get("/api/connections")
        assert response.status_code == 403

    def test_list_connections_passes_with_read_scope(self, client):
        _set_scopes(["read"])
        response = client.get("/api/connections")
        assert response.status_code != 403

    def test_list_connections_returns_403_with_only_execute_scope(self, client):
        _set_scopes(["execute"])
        response = client.get("/api/connections")
        assert response.status_code == 403

    def test_get_connection_detail_returns_403_without_read_scope(self, client):
        _set_scopes([])
        response = client.get("/api/connections/my-conn")
        assert response.status_code == 403

    def test_get_connection_detail_passes_with_read_scope(self, client):
        _set_scopes(["read"])
        response = client.get("/api/connections/nonexistent-conn")
        assert response.status_code != 403

    def test_get_connections_health_returns_403_without_read_scope(self, client):
        _set_scopes([])
        response = client.get("/api/connections/health")
        assert response.status_code == 403

    def test_get_connections_health_passes_with_read_scope(self, client):
        _set_scopes(["read"])
        response = client.get("/api/connections/health")
        assert response.status_code != 403

    def test_get_connections_stats_returns_403_without_read_scope(self, client):
        _set_scopes([])
        response = client.get("/api/connections/stats")
        assert response.status_code == 403

    def test_get_connections_stats_passes_with_read_scope(self, client):
        _set_scopes(["read"])
        response = client.get("/api/connections/stats")
        assert response.status_code != 403

    def test_get_connector_capabilities_returns_403_without_read_scope(self, client):
        _set_scopes([])
        response = client.get("/api/connectors/capabilities")
        assert response.status_code == 403

    def test_get_connector_capabilities_passes_with_read_scope(self, client):
        _set_scopes(["read"])
        response = client.get("/api/connectors/capabilities")
        assert response.status_code != 403


# ─── TestProjectsGetReadScope ─────────────────────────────────────────────────


class TestProjectsGetReadScope:
    """GET /api/projects and GET /api/projects/{name} require 'read' scope."""

    def test_list_projects_returns_403_without_read_scope(self, client):
        _set_scopes([])
        response = client.get("/api/projects")
        assert response.status_code == 403

    def test_list_projects_passes_with_read_scope(self, client):
        _set_scopes(["read"])
        response = client.get("/api/projects")
        assert response.status_code != 403

    def test_list_projects_returns_403_with_only_query_scope(self, client):
        _set_scopes(["query"])
        response = client.get("/api/projects")
        assert response.status_code == 403

    def test_get_project_detail_returns_403_without_read_scope(self, client):
        _set_scopes([])
        response = client.get("/api/projects/my-project")
        assert response.status_code == 403

    def test_get_project_detail_passes_with_read_scope(self, client):
        _set_scopes(["read"])
        response = client.get("/api/projects/nonexistent-project")
        assert response.status_code != 403


# ─── TestSchemaGetReadScope ───────────────────────────────────────────────────


class TestSchemaGetReadScope:
    """Schema GET endpoints require 'read' scope."""

    def test_get_schema_returns_403_without_read_scope(self, client):
        _set_scopes([])
        response = client.get("/api/connections/my-conn/schema")
        assert response.status_code == 403

    def test_get_schema_passes_with_read_scope(self, client):
        _set_scopes(["read"])
        response = client.get("/api/connections/nonexistent/schema")
        assert response.status_code != 403

    def test_get_schema_returns_403_with_only_query_scope(self, client):
        """query-only key cannot enumerate schema — specific threat from Finding 4."""
        _set_scopes(["query"])
        response = client.get("/api/connections/my-conn/schema")
        assert response.status_code == 403

    def test_get_grouped_schema_returns_403_without_read_scope(self, client):
        _set_scopes([])
        response = client.get("/api/connections/my-conn/schema/grouped")
        assert response.status_code == 403

    def test_get_grouped_schema_passes_with_read_scope(self, client):
        _set_scopes(["read"])
        response = client.get("/api/connections/nonexistent/schema/grouped")
        assert response.status_code != 403

    def test_get_schema_changes_returns_403_without_read_scope(self, client):
        _set_scopes([])
        response = client.get("/api/schema/changes")
        assert response.status_code == 403

    def test_get_schema_changes_passes_with_read_scope(self, client):
        _set_scopes(["read"])
        response = client.get("/api/schema/changes")
        assert response.status_code != 403


# ─── TestBudgetGetReadScope ───────────────────────────────────────────────────


class TestBudgetGetReadScope:
    """Budget GET endpoints require 'read' scope."""

    def test_list_budgets_returns_403_without_read_scope(self, client):
        _set_scopes([])
        response = client.get("/api/budget")
        assert response.status_code == 403

    def test_list_budgets_passes_with_read_scope(self, client):
        _set_scopes(["read"])
        response = client.get("/api/budget")
        assert response.status_code != 403

    def test_get_budget_session_returns_403_without_read_scope(self, client):
        _set_scopes([])
        response = client.get("/api/budget/some-session")
        assert response.status_code == 403

    def test_get_budget_session_passes_with_read_scope(self, client):
        _set_scopes(["read"])
        response = client.get("/api/budget/nonexistent-session")
        assert response.status_code != 403


# ─── TestCacheStatsReadScope ──────────────────────────────────────────────────


class TestCacheStatsReadScope:
    """Cache/pool/schema-cache stats GET endpoints require 'read' scope."""

    def test_cache_stats_returns_403_without_read_scope(self, client):
        _set_scopes([])
        response = client.get("/api/cache/stats")
        assert response.status_code == 403

    def test_cache_stats_passes_with_read_scope(self, client):
        _set_scopes(["read"])
        response = client.get("/api/cache/stats")
        assert response.status_code != 403

    def test_pool_stats_returns_403_without_read_scope(self, client):
        _set_scopes([])
        response = client.get("/api/pool/stats")
        assert response.status_code == 403

    def test_pool_stats_passes_with_read_scope(self, client):
        _set_scopes(["read"])
        response = client.get("/api/pool/stats")
        assert response.status_code != 403

    def test_schema_cache_stats_returns_403_without_read_scope(self, client):
        _set_scopes([])
        response = client.get("/api/schema-cache/stats")
        assert response.status_code == 403

    def test_schema_cache_stats_passes_with_read_scope(self, client):
        _set_scopes(["read"])
        response = client.get("/api/schema-cache/stats")
        assert response.status_code != 403


# ─── TestMetricsReadScope ─────────────────────────────────────────────────────


class TestMetricsReadScope:
    """GET /api/metrics requires 'read' scope.

    Note: /api/metrics is an SSE stream (infinite generator). Only the 403 path
    is tested synchronously — the success path would block forever waiting for
    the stream to close and is covered by scope_guard unit tests instead.
    """

    def test_metrics_returns_403_without_read_scope(self, client):
        _set_scopes([])
        response = client.get("/api/metrics")
        assert response.status_code == 403

    def test_metrics_returns_403_with_only_execute_scope(self, client):
        _set_scopes(["execute"])
        response = client.get("/api/metrics")
        assert response.status_code == 403
