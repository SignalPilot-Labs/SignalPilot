"""Integration tests for the gateway API using httpx TestClient."""

import pytest
from fastapi.testclient import TestClient

from gateway.main import app
from gateway.api.settings import _redact_settings
from gateway.models import GatewaySettings


@pytest.fixture
def client():
    """Create a test client with no auth required (no api_key configured)."""
    return TestClient(app)


class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data
        assert "connections" in data

    def test_health_no_auth_required(self, client):
        """Health is a public endpoint — no API key needed."""
        response = client.get("/health")
        assert response.status_code == 200


class TestSettingsEndpoint:
    def test_get_settings(self, client):
        response = client.get("/api/settings")
        assert response.status_code == 200
        data = response.json()
        assert "sandbox_manager_url" in data
        assert "default_row_limit" in data
        assert "gateway_url" in data

    def test_update_settings(self, client):
        settings = client.get("/api/settings").json()
        settings["default_row_limit"] = 5000
        response = client.put("/api/settings", json=settings)
        assert response.status_code == 200
        assert response.json()["default_row_limit"] == 5000


class TestConnectionsEndpoint:
    def test_list_connections_empty(self, client):
        response = client.get("/api/connections")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_create_connection(self, client):
        conn = {
            "name": "test-pg",
            "db_type": "postgres",
            "host": "localhost",
            "port": 5432,
            "database": "testdb",
            "username": "testuser",
            "password": "testpass",
            "description": "Test connection",
        }
        response = client.post("/api/connections", json=conn)
        # May fail with 409 if already exists from previous test run
        assert response.status_code in (201, 409)

    def test_create_connection_invalid_name(self, client):
        """Connection names must match ^[a-zA-Z0-9_-]+$ pattern."""
        conn = {
            "name": "../../../etc/passwd",
            "db_type": "postgres",
        }
        response = client.post("/api/connections", json=conn)
        assert response.status_code == 422  # Validation error

    def test_create_connection_name_too_long(self, client):
        conn = {
            "name": "a" * 100,
            "db_type": "postgres",
        }
        response = client.post("/api/connections", json=conn)
        assert response.status_code == 422

    def test_get_nonexistent_connection(self, client):
        response = client.get("/api/connections/nonexistent-conn")
        assert response.status_code == 404

    def test_delete_nonexistent_connection(self, client):
        response = client.delete("/api/connections/nonexistent-conn")
        assert response.status_code == 404


class TestQueryEndpoint:
    def test_query_blocked_ddl(self, client):
        response = client.post(
            "/api/query",
            json={
                "connection_name": "test-pg",
                "sql": "DROP TABLE users",
                "row_limit": 10,
            },
        )
        assert response.status_code == 400
        assert "blocked" in response.json()["detail"].lower()

    def test_query_blocked_insert(self, client):
        response = client.post(
            "/api/query",
            json={
                "connection_name": "test-pg",
                "sql": "INSERT INTO users VALUES (1, 'test')",
                "row_limit": 10,
            },
        )
        assert response.status_code == 400

    def test_query_blocked_stacking(self, client):
        response = client.post(
            "/api/query",
            json={
                "connection_name": "test-pg",
                "sql": "SELECT 1; DROP TABLE users",
                "row_limit": 10,
            },
        )
        assert response.status_code == 400
        assert "stacking" in response.json()["detail"].lower()

    def test_query_empty_sql_rejected(self, client):
        """Empty SQL should be rejected by Pydantic validation."""
        response = client.post(
            "/api/query",
            json={
                "connection_name": "test-pg",
                "sql": "",
                "row_limit": 10,
            },
        )
        assert response.status_code == 422

    def test_query_invalid_connection_name(self, client):
        """Path traversal in connection name blocked by regex."""
        response = client.post(
            "/api/query",
            json={
                "connection_name": "../../../etc",
                "sql": "SELECT 1",
            },
        )
        assert response.status_code == 422

    def test_query_nonexistent_connection(self, client):
        response = client.post(
            "/api/query",
            json={
                "connection_name": "nonexistent",
                "sql": "SELECT 1",
                "row_limit": 10,
            },
        )
        assert response.status_code == 404


class TestBudgetEndpoint:
    def test_create_budget(self, client):
        response = client.post(
            "/api/budget",
            json={"session_id": "test-session-1", "budget_usd": 25.0},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["session_id"] == "test-session-1"
        assert data["budget_usd"] == 25.0
        assert data["spent_usd"] == 0.0

    def test_get_budget(self, client):
        # Create first
        client.post(
            "/api/budget",
            json={"session_id": "test-session-2", "budget_usd": 10.0},
        )
        response = client.get("/api/budget/test-session-2")
        assert response.status_code == 200
        assert response.json()["budget_usd"] == 10.0

    def test_list_budgets(self, client):
        response = client.get("/api/budget")
        assert response.status_code == 200
        assert "sessions" in response.json()
        assert "total_spent_usd" in response.json()

    def test_get_nonexistent_budget(self, client):
        response = client.get("/api/budget/nonexistent-session")
        assert response.status_code == 404

    def test_budget_invalid_amount(self, client):
        response = client.post(
            "/api/budget",
            json={"session_id": "test", "budget_usd": -5.0},
        )
        assert response.status_code == 422


class TestAuditEndpoint:
    def test_get_audit(self, client):
        response = client.get("/api/audit")
        assert response.status_code == 200
        data = response.json()
        assert "entries" in data
        assert "total" in data

    def test_audit_with_filters(self, client):
        response = client.get("/api/audit?event_type=query&limit=10")
        assert response.status_code == 200

    def test_audit_limit_validation(self, client):
        response = client.get("/api/audit?limit=1000")
        assert response.status_code == 422  # Over max 500


class TestCacheEndpoint:
    def test_cache_stats(self, client):
        response = client.get("/api/cache/stats")
        assert response.status_code == 200
        data = response.json()
        assert "entries" in data
        assert "max_entries" in data
        assert "ttl_seconds" in data
        assert "hits" in data
        assert "misses" in data
        assert "hit_rate" in data

    def test_invalidate_cache(self, client):
        response = client.post("/api/cache/invalidate")
        assert response.status_code == 200
        data = response.json()
        assert "invalidated" in data

    def test_invalidate_cache_with_connection(self, client):
        response = client.post("/api/cache/invalidate?connection_name=test-pg")
        assert response.status_code == 200
        data = response.json()
        assert data["connection_name"] == "test-pg"


class TestHealthEndpoints:
    def test_all_connections_health(self, client):
        response = client.get("/api/connections/health")
        assert response.status_code == 200
        data = response.json()
        assert "connections" in data
        assert isinstance(data["connections"], list)

    def test_connection_health_not_found(self, client):
        response = client.get("/api/connections/nonexistent/health")
        assert response.status_code == 404

    def test_health_window_parameter(self, client):
        response = client.get("/api/connections/health?window=600")
        assert response.status_code == 200

    def test_health_window_validation(self, client):
        response = client.get("/api/connections/health?window=10")
        assert response.status_code == 422  # Below minimum of 60


class TestSettingsRedaction:
    """Tests for _redact_settings in settings.py."""

    def test_redacts_api_key_when_set(self):
        settings = GatewaySettings(api_key="secret123")
        result = _redact_settings(settings)
        assert result["api_key"] == "***"

    def test_redacts_sandbox_api_key_when_set(self):
        settings = GatewaySettings(sandbox_api_key="sandbox_secret")
        result = _redact_settings(settings)
        assert result["sandbox_api_key"] == "***"

    def test_redacts_both_keys_when_both_set(self):
        settings = GatewaySettings(api_key="key1", sandbox_api_key="key2")
        result = _redact_settings(settings)
        assert result["api_key"] == "***"
        assert result["sandbox_api_key"] == "***"

    def test_preserves_none_api_key(self):
        settings = GatewaySettings(api_key=None)
        result = _redact_settings(settings)
        assert result["api_key"] is None

    def test_preserves_none_sandbox_api_key(self):
        settings = GatewaySettings(sandbox_api_key=None)
        result = _redact_settings(settings)
        assert result["sandbox_api_key"] is None

    def test_preserves_other_fields(self):
        settings = GatewaySettings(
            api_key="secret",
            sandbox_api_key="sandbox_secret",
            default_row_limit=500,
            gateway_url="http://custom-host:9999",
            default_budget_usd=42.0,
        )
        result = _redact_settings(settings)
        assert result["default_row_limit"] == 500
        assert result["gateway_url"] == "http://custom-host:9999"
        assert result["default_budget_usd"] == 42.0

    def test_returns_dict(self):
        settings = GatewaySettings()
        result = _redact_settings(settings)
        assert isinstance(result, dict)
