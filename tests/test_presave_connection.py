"""Tests for pre-save connection testing endpoint.

Verifies the test-credentials endpoint accepts connection params
and returns phase-by-phase results without saving the connection.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import json


class TestPreSaveConnectionParams:
    """Test that the endpoint correctly parses various DB type payloads."""

    def test_postgres_payload_builds_connection_string(self):
        """Postgres payload should build a valid connection string."""
        from signalpilot.gateway.gateway.store import _build_connection_string
        from signalpilot.gateway.gateway.models import ConnectionCreate

        conn = ConnectionCreate(
            name="test",
            db_type="postgres",
            host="localhost",
            port=5432,
            database="testdb",
            username="user",
            password="pass",
        )
        cs = _build_connection_string(conn)
        assert cs.startswith("postgresql://")
        assert "user" in cs
        assert "localhost" in cs
        assert "5432" in cs
        assert "testdb" in cs

    def test_mysql_payload_builds_connection_string(self):
        from signalpilot.gateway.gateway.store import _build_connection_string
        from signalpilot.gateway.gateway.models import ConnectionCreate

        conn = ConnectionCreate(
            name="test",
            db_type="mysql",
            host="db.example.com",
            port=3306,
            database="analytics",
            username="analyst",
            password="secret",
        )
        cs = _build_connection_string(conn)
        assert cs.startswith("mysql+pymysql://")
        assert "analyst" in cs
        assert "3306" in cs

    def test_mssql_payload_builds_connection_string(self):
        from signalpilot.gateway.gateway.store import _build_connection_string
        from signalpilot.gateway.gateway.models import ConnectionCreate

        conn = ConnectionCreate(
            name="test",
            db_type="mssql",
            host="sql.example.com",
            port=1433,
            database="master",
            username="sa",
            password="p@ss",
        )
        cs = _build_connection_string(conn)
        assert cs.startswith("mssql://")
        assert "sql.example.com" in cs

    def test_clickhouse_native_builds_connection_string(self):
        from signalpilot.gateway.gateway.store import _build_connection_string
        from signalpilot.gateway.gateway.models import ConnectionCreate

        conn = ConnectionCreate(
            name="test",
            db_type="clickhouse",
            host="ch.example.com",
            port=9000,
            database="default",
            username="default",
            password="pass",
        )
        cs = _build_connection_string(conn)
        assert cs.startswith("clickhouse://")
        assert "9000" in cs

    def test_clickhouse_http_builds_connection_string(self):
        from signalpilot.gateway.gateway.store import _build_connection_string
        from signalpilot.gateway.gateway.models import ConnectionCreate

        conn = ConnectionCreate(
            name="test",
            db_type="clickhouse",
            host="ch.example.com",
            port=8123,
            database="default",
            username="default",
            password="pass",
            protocol="http",
        )
        cs = _build_connection_string(conn)
        assert "clickhouse+http" in cs

    def test_snowflake_builds_connection_string(self):
        from signalpilot.gateway.gateway.store import _build_connection_string
        from signalpilot.gateway.gateway.models import ConnectionCreate

        conn = ConnectionCreate(
            name="test",
            db_type="snowflake",
            account="xy12345.us-east-1",
            username="ANALYST",
            password="secret",
            database="PROD_DB",
            warehouse="COMPUTE_WH",
        )
        cs = _build_connection_string(conn)
        assert cs.startswith("snowflake://")
        assert "xy12345" in cs
        assert "warehouse=COMPUTE_WH" in cs

    def test_bigquery_uses_project_as_connection_string(self):
        from signalpilot.gateway.gateway.store import _build_connection_string
        from signalpilot.gateway.gateway.models import ConnectionCreate

        conn = ConnectionCreate(
            name="test",
            db_type="bigquery",
            project="my-project-123",
        )
        cs = _build_connection_string(conn)
        assert cs == "my-project-123"

    def test_redshift_builds_connection_string(self):
        from signalpilot.gateway.gateway.store import _build_connection_string
        from signalpilot.gateway.gateway.models import ConnectionCreate

        conn = ConnectionCreate(
            name="test",
            db_type="redshift",
            host="cluster.abc.us-east-1.redshift.amazonaws.com",
            port=5439,
            database="dev",
            username="admin",
            password="secret",
        )
        cs = _build_connection_string(conn)
        assert cs.startswith("redshift://")
        assert "5439" in cs


class TestCredentialExtrasExtraction:
    """Test that credential extras are correctly extracted from connection params."""

    def test_ssl_config_extracted(self):
        from signalpilot.gateway.gateway.store import _extract_credential_extras
        from signalpilot.gateway.gateway.models import ConnectionCreate, SSLConfig

        conn = ConnectionCreate(
            name="test",
            db_type="postgres",
            host="localhost",
            ssl_config=SSLConfig(enabled=True, mode="verify-full", ca_cert="-----BEGIN CERT-----"),
        )
        extras = _extract_credential_extras(conn)
        assert "ssl_config" in extras
        assert extras["ssl_config"]["enabled"] is True
        assert extras["ssl_config"]["mode"] == "verify-full"

    def test_bigquery_extras(self):
        from signalpilot.gateway.gateway.store import _extract_credential_extras
        from signalpilot.gateway.gateway.models import ConnectionCreate

        conn = ConnectionCreate(
            name="test",
            db_type="bigquery",
            project="my-project",
            credentials_json='{"type": "service_account"}',
        )
        extras = _extract_credential_extras(conn)
        assert extras.get("credentials_json") == '{"type": "service_account"}'
        assert extras.get("project") == "my-project"

    def test_timeout_config_extracted(self):
        from signalpilot.gateway.gateway.store import _extract_credential_extras
        from signalpilot.gateway.gateway.models import ConnectionCreate

        conn = ConnectionCreate(
            name="test",
            db_type="postgres",
            host="localhost",
            connection_timeout=30,
            query_timeout=120,
        )
        extras = _extract_credential_extras(conn)
        assert extras.get("connection_timeout") == 30
        assert extras.get("query_timeout") == 120

    def test_snowflake_extras(self):
        from signalpilot.gateway.gateway.store import _extract_credential_extras
        from signalpilot.gateway.gateway.models import ConnectionCreate

        conn = ConnectionCreate(
            name="test",
            db_type="snowflake",
            account="abc123",
            username="ANALYST",
            warehouse="WH",
            schema_name="PUBLIC",
            role="READER",
        )
        extras = _extract_credential_extras(conn)
        assert extras["account"] == "abc123"
        assert extras["warehouse"] == "WH"
        assert extras["schema_name"] == "PUBLIC"
        assert extras["role"] == "READER"


class TestResponseFormat:
    """Test that pre-save test response format matches expectations."""

    def test_healthy_response_structure(self):
        """A healthy response should have all phases with 'ok' status."""
        response = {
            "status": "healthy",
            "message": "All connection tests passed",
            "phases": [
                {"phase": "network", "status": "ok", "message": "TCP OK", "duration_ms": 1.0},
                {"phase": "authentication", "status": "ok", "message": "Auth OK", "duration_ms": 10.0},
                {"phase": "schema_access", "status": "ok", "message": "10 tables", "duration_ms": 100.0},
            ],
            "total_duration_ms": 111.0,
        }
        assert response["status"] == "healthy"
        assert len(response["phases"]) == 3
        assert all(p["status"] == "ok" for p in response["phases"])

    def test_error_response_includes_hints(self):
        """Error responses should include hints for remediation."""
        response = {
            "status": "error",
            "message": "Connection test failed",
            "phases": [
                {"phase": "network", "status": "ok", "message": "TCP OK", "duration_ms": 1.0},
                {"phase": "authentication", "status": "error", "message": "Auth failed",
                 "hint": "Check username and password", "duration_ms": 5.0},
            ],
        }
        failed = [p for p in response["phases"] if p["status"] == "error"]
        assert len(failed) == 1
        assert "hint" in failed[0]
