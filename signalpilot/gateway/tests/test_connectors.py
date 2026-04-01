"""Integration tests for database connectors.

These tests run against real databases:
  - Enterprise PostgreSQL: host.docker.internal:5601
  - Warehouse PostgreSQL: host.docker.internal:5602
  - Local PostgreSQL: host.docker.internal:5600
  - MySQL: host.docker.internal:3307

Run with: pytest tests/test_connectors.py -v
"""

import asyncio
import pytest
import pytest_asyncio

from gateway.connectors.postgres import PostgresConnector
from gateway.connectors.mysql import MySQLConnector
from gateway.connectors.base import ConnectionTestResult
from gateway.connectors.registry import get_connector, list_supported_types, DB_TYPE_META
from gateway.models import DBType


# ─── Fixtures ──────────────────────────────────────────────────────────

ENTERPRISE_PG = "postgresql://enterprise_admin:Ent3rpr1se!S3cur3@host.docker.internal:5601/enterprise_prod"
WAREHOUSE_PG = "postgresql://warehouse_admin:W4reh0use!An4lyt1cs@host.docker.internal:5602/analytics_warehouse"
LOCAL_PG = "postgresql://postgres:testpass@host.docker.internal:5600/testdb"
MYSQL_DSN = "mysql://analyst:An4lyst!P4ss@host.docker.internal:3307/test_analytics"


@pytest_asyncio.fixture
async def pg_connector():
    connector = PostgresConnector()
    await connector.connect(ENTERPRISE_PG)
    yield connector
    await connector.close()


@pytest_asyncio.fixture
async def mysql_connector():
    connector = MySQLConnector()
    await connector.connect(MYSQL_DSN)
    yield connector
    await connector.close()


# ─── PostgreSQL Connector Tests ────────────────────────────────────────


class TestPostgresConnector:
    """Test PostgresConnector against the enterprise database."""

    @pytest.mark.asyncio
    async def test_connect_and_health_check(self):
        connector = PostgresConnector()
        await connector.connect(ENTERPRISE_PG)
        assert await connector.health_check() is True
        await connector.close()

    @pytest.mark.asyncio
    async def test_connect_to_multiple_databases(self):
        """Verify we can connect to different PG instances."""
        for dsn in [ENTERPRISE_PG, WAREHOUSE_PG, LOCAL_PG]:
            connector = PostgresConnector()
            await connector.connect(dsn)
            assert await connector.health_check() is True
            await connector.close()

    @pytest.mark.asyncio
    async def test_execute_read_query(self, pg_connector: PostgresConnector):
        rows = await pg_connector.execute("SELECT 1 AS val")
        assert len(rows) == 1
        assert rows[0]["val"] == 1

    @pytest.mark.asyncio
    async def test_execute_with_enterprise_data(self, pg_connector: PostgresConnector):
        """Query real tables in the enterprise database."""
        rows = await pg_connector.execute("SELECT COUNT(*) AS cnt FROM customers")
        assert len(rows) == 1
        assert rows[0]["cnt"] > 0

    @pytest.mark.asyncio
    async def test_execute_read_only_enforced(self, pg_connector: PostgresConnector):
        """Ensure write operations fail due to read-only transaction."""
        with pytest.raises(Exception):
            await pg_connector.execute("CREATE TABLE _test_fail (id int)")

    @pytest.mark.asyncio
    async def test_get_schema(self, pg_connector: PostgresConnector):
        schema = await pg_connector.get_schema()
        assert isinstance(schema, dict)
        assert len(schema) > 0
        # Check schema structure
        first_table = next(iter(schema.values()))
        assert "schema" in first_table
        assert "name" in first_table
        assert "columns" in first_table
        assert len(first_table["columns"]) > 0
        col = first_table["columns"][0]
        assert "name" in col
        assert "type" in col
        assert "nullable" in col
        assert "primary_key" in col

    @pytest.mark.asyncio
    async def test_connection_test_result(self, pg_connector: PostgresConnector):
        """Test the rich connection test method."""
        result = await pg_connector.test_connection()
        assert isinstance(result, ConnectionTestResult)
        assert result.healthy is True
        assert result.message == "Connection successful"
        assert result.latency_ms > 0
        assert result.server_version is not None
        assert "PostgreSQL" in result.server_version
        assert result.database_name == "enterprise_prod"
        assert result.table_count is not None
        assert result.table_count > 0
        assert isinstance(result.schema_preview, list)
        assert result.max_connections is not None

    @pytest.mark.asyncio
    async def test_connection_test_to_dict(self, pg_connector: PostgresConnector):
        """Ensure to_dict() filters out None values."""
        result = await pg_connector.test_connection()
        d = result.to_dict()
        assert "healthy" in d
        assert "message" in d
        assert "latency_ms" in d
        # None values should be excluded
        assert all(v is not None for v in d.values())

    @pytest.mark.asyncio
    async def test_connect_with_bad_credentials(self):
        """Verify friendly error messages on auth failure."""
        connector = PostgresConnector()
        with pytest.raises(Exception) as exc_info:
            await connector.connect("postgresql://baduser:badpass@host.docker.internal:5601/enterprise_prod")
        msg, hint = connector.friendly_error(exc_info.value)
        assert hint is not None  # Should provide a helpful hint

    @pytest.mark.asyncio
    async def test_connect_with_bad_host(self):
        """Verify timeout on unreachable host."""
        connector = PostgresConnector()
        with pytest.raises(Exception):
            await connector.connect(
                "postgresql://user:pass@192.0.2.1:5432/db",
                connect_timeout=2.0,
            )

    @pytest.mark.asyncio
    async def test_execute_without_connect_raises(self):
        connector = PostgresConnector()
        with pytest.raises(RuntimeError, match="Not connected"):
            await connector.execute("SELECT 1")

    @pytest.mark.asyncio
    async def test_health_check_when_not_connected(self):
        connector = PostgresConnector()
        assert await connector.health_check() is False

    @pytest.mark.asyncio
    async def test_close_idempotent(self):
        connector = PostgresConnector()
        await connector.connect(LOCAL_PG)
        await connector.close()
        await connector.close()  # Should not raise

    @pytest.mark.asyncio
    async def test_test_connection_when_not_connected(self):
        connector = PostgresConnector()
        result = await connector.test_connection()
        assert result.healthy is False
        assert result.error_code == "NOT_CONNECTED"


# ─── MySQL Connector Tests ─────────────────────────────────────────────


class TestMySQLConnector:
    """Test MySQLConnector against the test MySQL database."""

    @pytest.mark.asyncio
    async def test_connect_and_health_check(self):
        connector = MySQLConnector()
        await connector.connect(MYSQL_DSN)
        assert await connector.health_check() is True
        await connector.close()

    @pytest.mark.asyncio
    async def test_execute_read_query(self, mysql_connector: MySQLConnector):
        rows = await mysql_connector.execute("SELECT 1 AS val")
        assert len(rows) == 1
        assert rows[0]["val"] == 1

    @pytest.mark.asyncio
    async def test_execute_with_test_data(self, mysql_connector: MySQLConnector):
        """Query real tables in the MySQL test database."""
        rows = await mysql_connector.execute("SELECT COUNT(*) AS cnt FROM users")
        assert len(rows) == 1
        assert rows[0]["cnt"] > 0

    @pytest.mark.asyncio
    async def test_get_schema(self, mysql_connector: MySQLConnector):
        schema = await mysql_connector.get_schema()
        assert isinstance(schema, dict)
        assert len(schema) > 0
        first_table = next(iter(schema.values()))
        assert "schema" in first_table
        assert "name" in first_table
        assert "columns" in first_table
        col = first_table["columns"][0]
        assert "name" in col
        assert "type" in col
        assert "primary_key" in col

    @pytest.mark.asyncio
    async def test_connection_test_result(self, mysql_connector: MySQLConnector):
        result = await mysql_connector.test_connection()
        assert isinstance(result, ConnectionTestResult)
        assert result.healthy is True
        assert result.message == "Connection successful"
        assert result.latency_ms > 0
        assert result.server_version is not None
        assert "MySQL" in result.server_version
        assert result.database_name == "test_analytics"
        assert result.table_count is not None
        assert result.table_count > 0
        assert isinstance(result.schema_preview, list)

    @pytest.mark.asyncio
    async def test_execute_without_connect_raises(self):
        connector = MySQLConnector()
        with pytest.raises(RuntimeError, match="Not connected"):
            await connector.execute("SELECT 1")

    @pytest.mark.asyncio
    async def test_health_check_when_not_connected(self):
        connector = MySQLConnector()
        assert await connector.health_check() is False

    @pytest.mark.asyncio
    async def test_close_idempotent(self):
        connector = MySQLConnector()
        await connector.connect(MYSQL_DSN)
        await connector.close()
        await connector.close()  # Should not raise

    @pytest.mark.asyncio
    async def test_test_connection_when_not_connected(self):
        connector = MySQLConnector()
        result = await connector.test_connection()
        assert result.healthy is False
        assert result.error_code == "NOT_CONNECTED"


# ─── Registry Tests ────────────────────────────────────────────────────


class TestRegistry:
    def test_get_postgres_connector(self):
        c = get_connector(DBType.postgres)
        assert isinstance(c, PostgresConnector)

    def test_get_mysql_connector(self):
        c = get_connector(DBType.mysql)
        assert isinstance(c, MySQLConnector)

    def test_get_unsupported_raises(self):
        with pytest.raises(ValueError, match="coming soon"):
            get_connector(DBType.duckdb)

    def test_list_supported_types(self):
        types = list_supported_types()
        assert isinstance(types, list)
        assert len(types) >= 4  # postgres, mysql, duckdb, snowflake
        names = [t["name"] for t in types]
        assert "PostgreSQL" in names
        assert "MySQL" in names
        assert "DuckDB" in names
        assert "Snowflake" in names

    def test_db_type_meta_has_required_fields(self):
        for db_type, meta in DB_TYPE_META.items():
            assert "name" in meta
            assert "description" in meta
            assert "status" in meta
            assert "connection_fields" in meta


# ─── API Integration Tests ─────────────────────────────────────────────


class TestGatewayAPI:
    """Test the gateway API endpoints for connections."""

    @pytest.mark.asyncio
    async def test_create_test_delete_connection(self):
        """Full lifecycle: create -> test -> delete a connection via the API."""
        import httpx

        base = "http://host.docker.internal:3300"
        name = "pytest-enterprise"

        async with httpx.AsyncClient(timeout=30) as client:
            # Delete if exists from previous run
            await client.delete(f"{base}/api/connections/{name}")

            # Create
            resp = await client.post(f"{base}/api/connections", json={
                "name": name,
                "db_type": "postgres",
                "host": "host.docker.internal",
                "port": 5601,
                "database": "enterprise_prod",
                "username": "enterprise_admin",
                "password": "Ent3rpr1se!S3cur3",
                "description": "Test connection from pytest",
            })
            assert resp.status_code == 201
            data = resp.json()
            assert data["name"] == name
            assert data["db_type"] == "postgres"

            # Test
            resp = await client.post(f"{base}/api/connections/{name}/test")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "healthy"
            assert "latency_ms" in data
            assert "server_version" in data
            assert "table_count" in data
            assert "schema_preview" in data
            assert data["table_count"] > 0

            # List
            resp = await client.get(f"{base}/api/connections")
            assert resp.status_code == 200
            names = [c["name"] for c in resp.json()]
            assert name in names

            # Delete
            resp = await client.delete(f"{base}/api/connections/{name}")
            assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_db_types_endpoint(self):
        """Test the /api/db-types metadata endpoint."""
        import httpx

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get("http://host.docker.internal:3300/api/db-types")
            assert resp.status_code == 200
            types = resp.json()
            assert isinstance(types, list)
            assert len(types) >= 4
            pg = next(t for t in types if t["type"] == "postgres")
            assert pg["status"] == "available"
            assert pg["default_port"] == 5432

    @pytest.mark.asyncio
    async def test_create_and_test_mysql_connection(self):
        """Full lifecycle for MySQL connection via API."""
        import httpx

        base = "http://host.docker.internal:3300"
        name = "pytest-mysql"

        async with httpx.AsyncClient(timeout=30) as client:
            await client.delete(f"{base}/api/connections/{name}")

            resp = await client.post(f"{base}/api/connections", json={
                "name": name,
                "db_type": "mysql",
                "host": "host.docker.internal",
                "port": 3307,
                "database": "test_analytics",
                "username": "analyst",
                "password": "An4lyst!P4ss",
                "description": "MySQL test from pytest",
            })
            assert resp.status_code == 201

            resp = await client.post(f"{base}/api/connections/{name}/test")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "healthy"
            assert "MySQL" in data.get("server_version", "")
            assert data.get("table_count", 0) > 0

            # Cleanup
            await client.delete(f"{base}/api/connections/{name}")

    @pytest.mark.asyncio
    async def test_connection_test_with_bad_credentials(self):
        """Test that connection with bad creds returns friendly error."""
        import httpx

        base = "http://host.docker.internal:3300"
        name = "pytest-bad-creds"

        async with httpx.AsyncClient(timeout=30) as client:
            await client.delete(f"{base}/api/connections/{name}")

            resp = await client.post(f"{base}/api/connections", json={
                "name": name,
                "db_type": "postgres",
                "host": "host.docker.internal",
                "port": 5601,
                "database": "enterprise_prod",
                "username": "wrong_user",
                "password": "wrong_pass",
            })
            assert resp.status_code == 201

            resp = await client.post(f"{base}/api/connections/{name}/test")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "error"
            assert "error_hint" in data
            assert data["error_hint"] is not None

            await client.delete(f"{base}/api/connections/{name}")
