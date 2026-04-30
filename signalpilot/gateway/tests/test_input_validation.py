"""Tests for input validation sweep (Round 21).

Covers Pydantic model field limits, Literal type enforcement, list size caps,
and inline validation for untyped dict endpoints.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import Request, Response
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.middleware.base import RequestResponseEndpoint

from gateway.api.deps import get_store
from gateway.http import APIKeyAuthMiddleware
from gateway.main import app
from gateway.models import (
    ConnectionCreate,
    ConnectionUpdate,
    GatewaySettings,
    MCPToolCall,
    ProjectCreate,
    ProjectStatus,
    ProjectUpdate,
    SandboxCreate,
    SSHTunnelConfig,
    SSLConfig,
)

# ─── Auth bypass for API-level tests ─────────────────────────────────────────

_TEST_AUTH: dict[str, Any] = {
    "auth_method": "api_key",
    "user_id": "test-user",
    "scopes": ["read", "write", "admin", "execute", "query"],
}


async def _bypass_auth_dispatch(
    request: Request,
    call_next: RequestResponseEndpoint,
) -> Response:
    request.state.auth = dict(_TEST_AUTH)
    return await call_next(request)


def _make_mock_store() -> AsyncMock:
    store = AsyncMock()
    store.list_connections.return_value = []
    store.get_connection.return_value = None
    store.get_connection_string.return_value = None
    mock_settings = AsyncMock()
    mock_settings.default_timeout_seconds = 30
    mock_settings.blocked_tables = []
    store.load_settings.return_value = mock_settings
    return store


async def _fake_get_store() -> AsyncMock:
    return _make_mock_store()


def _find_auth_middleware() -> APIKeyAuthMiddleware | None:
    current = app.middleware_stack
    while current is not None:
        if isinstance(current, APIKeyAuthMiddleware):
            return current
        current = getattr(current, "app", None)
    return None


@pytest.fixture(scope="module")
def client() -> TestClient:
    """Test client with authentication bypassed and store mocked."""
    app.dependency_overrides[get_store] = _fake_get_store
    with (
        patch("gateway.main.init_db", new_callable=AsyncMock),
        patch("gateway.main.close_db", new_callable=AsyncMock),
        patch("gateway.main.get_session_factory", return_value=AsyncMock()),
    ):
        _client = TestClient(app, raise_server_exceptions=False)
        with _client:
            middleware_instance = _find_auth_middleware()
            if middleware_instance is not None:
                middleware_instance.dispatch_func = _bypass_auth_dispatch
            yield _client
    app.dependency_overrides.pop(get_store, None)


# ─── Enum / Literal validation ────────────────────────────────────────────────


class TestEnumLiteralValidation:
    def test_ssh_tunnel_auth_method_rejects_invalid(self):
        with pytest.raises(ValidationError):
            SSHTunnelConfig(auth_method="evil")

    def test_ssh_tunnel_auth_method_accepts_valid(self):
        for method in ("password", "key", "agent"):
            cfg = SSHTunnelConfig(auth_method=method)
            assert cfg.auth_method == method

    def test_ssl_config_mode_rejects_invalid(self):
        with pytest.raises(ValidationError):
            SSLConfig(mode="custom")

    def test_ssl_config_mode_accepts_valid(self):
        for mode in ("disable", "allow", "prefer", "require", "verify-ca", "verify-full"):
            cfg = SSLConfig(mode=mode)
            assert cfg.mode == mode

    def test_project_create_link_mode_rejects_invalid(self):
        with pytest.raises(ValidationError):
            ProjectCreate(name="myproject", connection_name="myconn", link_mode="symlink")

    def test_project_create_link_mode_accepts_valid(self):
        for mode in ("link", "copy"):
            p = ProjectCreate(name="myproject", connection_name="myconn", link_mode=mode)
            assert p.link_mode == mode

    def test_project_update_status_rejects_invalid(self):
        with pytest.raises(ValidationError):
            ProjectUpdate(status="deleted")

    def test_project_update_status_accepts_valid_enum(self):
        for status in ProjectStatus:
            p = ProjectUpdate(status=status)
            assert p.status == status

    def test_project_update_status_accepts_string_values(self):
        """ProjectStatus is a str enum so string values should coerce."""
        p = ProjectUpdate(status="active")
        assert p.status == ProjectStatus.active


# ─── String length limits (model-level) ──────────────────────────────────────


class TestStringLengthLimits:
    def test_project_create_connection_name_too_long(self):
        with pytest.raises(ValidationError):
            ProjectCreate(name="myproject", connection_name="a" * 65)

    def test_project_create_connection_name_max_ok(self):
        p = ProjectCreate(name="myproject", connection_name="a" * 64)
        assert len(p.connection_name) == 64

    def test_project_create_git_url_too_long(self):
        with pytest.raises(ValidationError):
            ProjectCreate(name="myproject", connection_name="myconn", git_url="x" * 2049)

    def test_project_create_git_url_max_ok(self):
        p = ProjectCreate(name="myproject", connection_name="myconn", git_url="x" * 2048)
        assert len(p.git_url) == 2048

    def test_project_create_git_branch_too_long(self):
        with pytest.raises(ValidationError):
            ProjectCreate(name="myproject", connection_name="myconn", git_branch="b" * 257)

    def test_project_create_local_path_too_long(self):
        with pytest.raises(ValidationError):
            ProjectCreate(name="myproject", connection_name="myconn", local_path="/" + "a" * 4096)

    def test_project_update_git_remote_too_long(self):
        with pytest.raises(ValidationError):
            ProjectUpdate(git_remote="x" * 2049)

    def test_project_update_git_branch_too_long(self):
        with pytest.raises(ValidationError):
            ProjectUpdate(git_branch="b" * 257)

    def test_project_update_connection_name_too_long(self):
        with pytest.raises(ValidationError):
            ProjectUpdate(connection_name="a" * 65)

    def test_sandbox_create_label_too_long(self):
        with pytest.raises(ValidationError):
            SandboxCreate(label="a" * 129)

    def test_sandbox_create_label_max_ok(self):
        s = SandboxCreate(label="a" * 128)
        assert len(s.label) == 128

    def test_sandbox_create_connection_name_too_long(self):
        with pytest.raises(ValidationError):
            SandboxCreate(connection_name="a" * 65)

    def test_mcp_tool_call_tool_too_long(self):
        with pytest.raises(ValidationError):
            MCPToolCall(tool="t" * 129)

    def test_mcp_tool_call_tool_max_ok(self):
        m = MCPToolCall(tool="t" * 128)
        assert len(m.tool) == 128

    def test_mcp_tool_call_session_id_too_long(self):
        with pytest.raises(ValidationError):
            MCPToolCall(tool="my_tool", session_id="s" * 129)

    def test_mcp_tool_call_arguments_depth_limit(self):
        """arguments nested 21 levels deep must raise ValidationError."""
        nested: dict[str, Any] = {}
        cursor = nested
        for _ in range(21):
            cursor["x"] = {}
            cursor = cursor["x"]
        with pytest.raises(ValidationError):
            MCPToolCall(tool="my_tool", arguments=nested)

    def test_mcp_tool_call_arguments_depth_ok(self):
        """arguments nested exactly 20 levels deep must pass validation."""
        nested: dict[str, Any] = {}
        cursor = nested
        for _ in range(20):
            cursor["x"] = {}
            cursor = cursor["x"]
        m = MCPToolCall(tool="my_tool", arguments=nested)
        assert m.tool == "my_tool"

    def test_mcp_tool_call_arguments_size_limit(self):
        """arguments with serialized size exceeding 100KB must raise ValidationError."""
        large_value = "a" * 101_000
        with pytest.raises(ValidationError):
            MCPToolCall(tool="my_tool", arguments={"data": large_value})

    def test_mcp_tool_call_arguments_normal_ok(self):
        """Normal arguments dict must pass validation without errors."""
        m = MCPToolCall(
            tool="my_tool",
            arguments={"key": "value", "nested": {"a": 1, "b": [1, 2, 3]}},
        )
        assert m.arguments["key"] == "value"

    def test_gateway_settings_sandbox_manager_url_too_long(self):
        with pytest.raises(ValidationError):
            GatewaySettings(sandbox_manager_url="http://" + "a" * 2048)

    def test_gateway_settings_gateway_url_too_long(self):
        with pytest.raises(ValidationError):
            GatewaySettings(gateway_url="http://" + "a" * 2048)


# ─── List size limits ────────────────────────────────────────────────────────


class TestListSizeLimits:
    def test_connection_create_tags_too_many(self):
        with pytest.raises(ValidationError):
            ConnectionCreate(
                name="myconn",
                db_type="postgres",
                tags=["tag"] * 51,
            )

    def test_connection_create_tags_max_ok(self):
        conn = ConnectionCreate(
            name="myconn",
            db_type="postgres",
            tags=[f"tag{i}" for i in range(50)],
        )
        assert len(conn.tags) == 50

    def test_connection_create_tags_item_too_long(self):
        with pytest.raises(ValidationError):
            ConnectionCreate(
                name="myconn",
                db_type="postgres",
                tags=["a" * 65],
            )

    def test_connection_update_tags_too_many(self):
        with pytest.raises(ValidationError):
            ConnectionUpdate(tags=["tag"] * 51)

    def test_connection_update_tags_item_too_long(self):
        with pytest.raises(ValidationError):
            ConnectionUpdate(tags=["a" * 65])

    def test_connection_create_schema_filter_include_too_many(self):
        with pytest.raises(ValidationError):
            ConnectionCreate(
                name="myconn",
                db_type="postgres",
                schema_filter_include=["schema"] * 101,
            )

    def test_connection_create_schema_filter_include_max_ok(self):
        conn = ConnectionCreate(
            name="myconn",
            db_type="postgres",
            schema_filter_include=[f"s{i}" for i in range(100)],
        )
        assert len(conn.schema_filter_include) == 100

    def test_connection_create_schema_filter_item_too_long(self):
        with pytest.raises(ValidationError):
            ConnectionCreate(
                name="myconn",
                db_type="postgres",
                schema_filter_include=["a" * 257],
            )

    def test_connection_create_schema_filter_exclude_too_many(self):
        with pytest.raises(ValidationError):
            ConnectionCreate(
                name="myconn",
                db_type="postgres",
                schema_filter_exclude=["schema"] * 101,
            )

    def test_connection_update_schema_filter_too_many(self):
        with pytest.raises(ValidationError):
            ConnectionUpdate(schema_filter_include=["s"] * 101)

    def test_connection_update_schema_filter_item_too_long(self):
        with pytest.raises(ValidationError):
            ConnectionUpdate(schema_filter_exclude=["a" * 257])

    def test_gateway_settings_blocked_tables_too_many(self):
        with pytest.raises(ValidationError):
            GatewaySettings(blocked_tables=["t"] * 501)

    def test_gateway_settings_blocked_tables_max_ok(self):
        s = GatewaySettings(blocked_tables=[f"t{i}" for i in range(500)])
        assert len(s.blocked_tables) == 500

    def test_gateway_settings_blocked_tables_item_too_long(self):
        with pytest.raises(ValidationError):
            GatewaySettings(blocked_tables=["a" * 257])

    def test_project_create_tags_too_many(self):
        with pytest.raises(ValidationError):
            ProjectCreate(
                name="myproject",
                connection_name="myconn",
                tags=["tag"] * 51,
            )

    def test_project_create_tags_item_too_long(self):
        with pytest.raises(ValidationError):
            ProjectCreate(
                name="myproject",
                connection_name="myconn",
                tags=["a" * 65],
            )

    def test_project_update_tags_too_many(self):
        with pytest.raises(ValidationError):
            ProjectUpdate(tags=["tag"] * 51)

    def test_project_update_tags_item_too_long(self):
        with pytest.raises(ValidationError):
            ProjectUpdate(tags=["a" * 65])


# ─── Numeric bounds (model-level) ────────────────────────────────────────────


class TestNumericBounds:
    def test_sandbox_create_budget_too_low(self):
        with pytest.raises(ValidationError):
            SandboxCreate(budget_usd=-1.0)

    def test_sandbox_create_budget_zero_rejected(self):
        with pytest.raises(ValidationError):
            SandboxCreate(budget_usd=0.0)

    def test_sandbox_create_budget_max_ok(self):
        s = SandboxCreate(budget_usd=10_000.0)
        assert s.budget_usd == 10_000.0

    def test_sandbox_create_budget_over_max(self):
        with pytest.raises(ValidationError):
            SandboxCreate(budget_usd=10_001.0)

    def test_sandbox_create_row_limit_zero_rejected(self):
        with pytest.raises(ValidationError):
            SandboxCreate(row_limit=0)

    def test_sandbox_create_row_limit_max_ok(self):
        s = SandboxCreate(row_limit=100_000)
        assert s.row_limit == 100_000

    def test_sandbox_create_row_limit_over_max(self):
        with pytest.raises(ValidationError):
            SandboxCreate(row_limit=100_001)

    def test_sandbox_create_timeout_zero_rejected(self):
        with pytest.raises(ValidationError):
            SandboxCreate(timeout_seconds=0)

    def test_sandbox_create_timeout_max_ok(self):
        s = SandboxCreate(timeout_seconds=3600)
        assert s.timeout_seconds == 3600

    def test_sandbox_create_timeout_over_max(self):
        with pytest.raises(ValidationError):
            SandboxCreate(timeout_seconds=3601)


# ─── Import connections size cap (API-level) ──────────────────────────────────


class TestImportConnectionsSizeCap:
    def test_import_too_many_connections_rejected(self, client: TestClient):
        connections = [{"name": f"conn-{i}", "db_type": "postgres"} for i in range(501)]
        response = client.post(
            "/api/connections/import",
            json={"connections": connections},
        )
        assert response.status_code == 422
        assert "500" in response.json()["detail"]

    def test_import_exactly_500_connections_not_rejected_by_size_cap(self, client: TestClient):
        """500 connections should pass the size cap check (may fail for other reasons)."""
        connections = [{"name": f"conn-{i}", "db_type": "postgres"} for i in range(500)]
        response = client.post(
            "/api/connections/import",
            json={"connections": connections},
        )
        # Must not be rejected by the size cap specifically
        if response.status_code == 422:
            detail = response.json().get("detail", "")
            assert "Maximum 500 connections" not in detail


# ─── Untyped dict endpoint validation (API-level) ─────────────────────────────


class TestUntypedDictEndpoints:
    def test_parse_url_too_long_rejected(self, client: TestClient):
        response = client.post(
            "/api/connections/parse-url",
            json={"url": "postgres://" + "a" * 4090},
        )
        assert response.status_code == 422
        assert "4096" in response.json()["detail"]

    def test_parse_url_valid_length_accepted(self, client: TestClient):
        response = client.post(
            "/api/connections/parse-url",
            json={"url": "postgresql://user:pass@localhost:5432/mydb"},
        )
        # Should not be rejected for length
        assert response.status_code != 422

    def test_validate_url_too_long_rejected(self, client: TestClient):
        response = client.post(
            "/api/connections/validate-url",
            json={"connection_string": "postgres://" + "a" * 4090, "db_type": "postgres"},
        )
        assert response.status_code == 422
        assert "4096" in response.json()["detail"]

    def test_build_url_host_too_long_rejected(self, client: TestClient):
        response = client.post(
            "/api/connections/build-url",
            json={
                "db_type": "postgres",
                "host": "h" * 256,
                "database": "mydb",
                "username": "user",
            },
        )
        assert response.status_code == 422
        assert "host" in response.json()["detail"]

    def test_build_url_database_too_long_rejected(self, client: TestClient):
        response = client.post(
            "/api/connections/build-url",
            json={
                "db_type": "postgres",
                "host": "localhost",
                "database": "d" * 129,
                "username": "user",
            },
        )
        assert response.status_code == 422
        assert "database" in response.json()["detail"]

    def test_build_url_username_too_long_rejected(self, client: TestClient):
        response = client.post(
            "/api/connections/build-url",
            json={
                "db_type": "postgres",
                "host": "localhost",
                "database": "mydb",
                "username": "u" * 129,
            },
        )
        assert response.status_code == 422
        assert "username" in response.json()["detail"]

    def test_build_url_password_too_long_rejected(self, client: TestClient):
        response = client.post(
            "/api/connections/build-url",
            json={
                "db_type": "postgres",
                "host": "localhost",
                "database": "mydb",
                "username": "user",
                "password": "p" * 1025,
            },
        )
        assert response.status_code == 422
        assert "password" in response.json()["detail"]

    def test_build_url_valid_fields_accepted(self, client: TestClient):
        response = client.post(
            "/api/connections/build-url",
            json={
                "db_type": "postgres",
                "host": "localhost",
                "database": "mydb",
                "username": "user",
                "password": "pass",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "url" in data


# ─── Schema query param length limits (API-level) ────────────────────────────


class TestSchemaQueryParamLimits:
    def test_search_schema_q_too_long_rejected(self, client: TestClient):
        response = client.get(
            "/api/connections/myconn/schema/search",
            params={"q": "x" * 501},
        )
        assert response.status_code == 422

    def test_schema_link_question_too_long_rejected(self, client: TestClient):
        response = client.get(
            "/api/connections/myconn/schema/link",
            params={"question": "q" * 2001},
        )
        assert response.status_code == 422

    def test_agent_context_question_too_long_rejected(self, client: TestClient):
        response = client.get(
            "/api/connections/myconn/schema/agent-context",
            params={"question": "q" * 2001},
        )
        assert response.status_code == 422

    def test_explore_column_values_table_too_long_rejected(self, client: TestClient):
        response = client.post(
            "/api/connections/myconn/schema/explore",
            params={"table": "t" * 257, "column": "col"},
        )
        assert response.status_code == 422

    def test_explore_column_values_column_too_long_rejected(self, client: TestClient):
        response = client.post(
            "/api/connections/myconn/schema/explore",
            params={"table": "public.users", "column": "c" * 129},
        )
        assert response.status_code == 422

    def test_get_connection_schema_filter_too_long_rejected(self, client: TestClient):
        response = client.get(
            "/api/connections/myconn/schema",
            params={"filter": "f" * 1001},
        )
        assert response.status_code == 422


# ─── Correct-columns and explore-columns-deep list caps (API-level) ──────────


class TestBodyListCaps:
    def test_correct_columns_too_many_columns_rejected(self, client: TestClient):
        response = client.post(
            "/api/connections/myconn/schema/correct-columns",
            json={"table": "public.users", "columns": ["col"] * 101},
        )
        assert response.status_code == 422
        assert "100" in response.json()["detail"]

    def test_explore_columns_deep_too_many_columns_rejected(self, client: TestClient):
        response = client.post(
            "/api/connections/myconn/schema/explore-columns",
            json={"table": "public.users", "columns": ["col"] * 51},
        )
        assert response.status_code == 422
        assert "50" in response.json()["detail"]
