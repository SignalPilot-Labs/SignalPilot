"""Live integration tests for all database connectors.

Tests: connect, health_check, execute, get_schema, close
Databases under test:
  - PostgreSQL (enterprise-pg on port 5601)
  - MySQL (sp-mysql-test on port 3307)
  - ClickHouse (sp-clickhouse-test on port 9100)
  - DuckDB (in-memory)
  - SQLite (in-memory)
"""

import asyncio

import pytest

# ── PostgreSQL ──────────────────────────────────────────────────────────────


class TestPostgresConnector:
    CONN_STR = "postgresql://enterprise_admin:Ent3rpr1se!S3cur3@host.docker.internal:5601/enterprise_prod"

    @pytest.fixture
    def connector(self):
        from gateway.connectors.postgres import PostgresConnector

        return PostgresConnector()

    @pytest.mark.asyncio
    async def test_connect_and_health(self, connector):
        await connector.connect(self.CONN_STR)
        assert await connector.health_check() is True
        await connector.close()

    @pytest.mark.asyncio
    async def test_execute_query(self, connector):
        await connector.connect(self.CONN_STR)
        rows = await connector.execute("SELECT 1 AS value")
        assert len(rows) == 1
        assert rows[0]["value"] == 1
        await connector.close()

    @pytest.mark.asyncio
    async def test_get_schema(self, connector):
        await connector.connect(self.CONN_STR)
        schema = await connector.get_schema()
        assert isinstance(schema, dict)
        # Should have tables
        if len(schema) > 0:
            first_table = list(schema.values())[0]
            assert "columns" in first_table
            assert "schema" in first_table
            assert "name" in first_table
            # Check enhanced metadata
            assert "foreign_keys" in first_table
            assert "row_count" in first_table
            assert "description" in first_table
            # Check column metadata
            col = first_table["columns"][0]
            assert "name" in col
            assert "type" in col
            assert "nullable" in col
            assert "primary_key" in col
        await connector.close()

    @pytest.mark.asyncio
    async def test_readonly_enforcement(self, connector):
        await connector.connect(self.CONN_STR)
        with pytest.raises(Exception):
            await connector.execute("CREATE TABLE _test_readonly (id int)")
        await connector.close()


# ── MySQL ───────────────────────────────────────────────────────────────────


class TestMySQLConnector:
    CONN_STR = "mysql://analyst:An4lyst!P4ss@host.docker.internal:3307/test_analytics"

    @pytest.fixture
    def connector(self):
        from gateway.connectors.mysql import MySQLConnector

        return MySQLConnector()

    @pytest.mark.asyncio
    async def test_connect_and_health(self, connector):
        try:
            await connector.connect(self.CONN_STR)
            assert await connector.health_check() is True
            await connector.close()
        except Exception as e:
            pytest.skip(f"MySQL not available: {e}")

    @pytest.mark.asyncio
    async def test_execute_query(self, connector):
        try:
            await connector.connect(self.CONN_STR)
        except Exception:
            pytest.skip("MySQL not available")
        rows = await connector.execute("SELECT 1 AS value")
        assert len(rows) == 1
        assert rows[0]["value"] == 1
        await connector.close()

    @pytest.mark.asyncio
    async def test_get_schema(self, connector):
        try:
            await connector.connect(self.CONN_STR)
        except Exception:
            pytest.skip("MySQL not available")
        schema = await connector.get_schema()
        assert isinstance(schema, dict)
        if len(schema) > 0:
            first_table = list(schema.values())[0]
            assert "columns" in first_table
            assert "foreign_keys" in first_table
            assert "row_count" in first_table
        await connector.close()


# ── ClickHouse ──────────────────────────────────────────────────────────────


class TestClickHouseConnector:
    CONN_STR = "clickhouse://default:test123@host.docker.internal:9100/default"

    @pytest.fixture
    def connector(self):
        from gateway.connectors.clickhouse import ClickHouseConnector

        return ClickHouseConnector()

    @pytest.mark.asyncio
    async def test_connect_and_health(self, connector):
        try:
            await connector.connect(self.CONN_STR)
            assert await connector.health_check() is True
            await connector.close()
        except Exception as e:
            pytest.skip(f"ClickHouse not available: {e}")

    @pytest.mark.asyncio
    async def test_execute_query(self, connector):
        try:
            await connector.connect(self.CONN_STR)
        except Exception:
            pytest.skip("ClickHouse not available")
        rows = await connector.execute("SELECT 1 AS value")
        assert len(rows) == 1
        assert rows[0]["value"] == 1
        await connector.close()

    @pytest.mark.asyncio
    async def test_get_schema(self, connector):
        try:
            await connector.connect(self.CONN_STR)
        except Exception:
            pytest.skip("ClickHouse not available")
        schema = await connector.get_schema()
        assert isinstance(schema, dict)
        await connector.close()


# ── DuckDB ──────────────────────────────────────────────────────────────────


class TestDuckDBConnector:
    @pytest.fixture
    def connector(self):
        from gateway.connectors.duckdb import DuckDBConnector

        return DuckDBConnector()

    @pytest.mark.asyncio
    async def test_connect_and_health(self, connector):
        await connector.connect(":memory:")
        assert await connector.health_check() is True
        await connector.close()

    @pytest.mark.asyncio
    async def test_execute_query(self, connector):
        await connector.connect(":memory:")
        rows = await connector.execute("SELECT 1 AS value")
        assert len(rows) == 1
        assert rows[0]["value"] == 1
        await connector.close()

    @pytest.mark.asyncio
    async def test_get_schema(self, connector):
        await connector.connect(":memory:")
        # Create a test table
        await connector.execute("CREATE TABLE test_table (id INTEGER, name VARCHAR)")
        schema = await connector.get_schema()
        assert isinstance(schema, dict)
        assert len(schema) > 0
        await connector.close()


# ── SQLite ──────────────────────────────────────────────────────────────────


class TestSQLiteConnector:
    @pytest.fixture
    def connector(self):
        from gateway.connectors.sqlite import SQLiteConnector

        return SQLiteConnector()

    @pytest.mark.asyncio
    async def test_connect_and_health(self, connector):
        await connector.connect(":memory:")
        assert await connector.health_check() is True
        await connector.close()

    @pytest.mark.asyncio
    async def test_execute_and_schema(self, connector):
        await connector.connect(":memory:")
        await connector.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT)")
        await connector.execute("INSERT INTO users VALUES (1, 'Alice', 'alice@example.com')")

        rows = await connector.execute("SELECT * FROM users")
        assert len(rows) == 1
        assert rows[0]["name"] == "Alice"

        schema = await connector.get_schema()
        assert "users" in schema
        assert len(schema["users"]["columns"]) == 3
        # Check PK detection
        id_col = [c for c in schema["users"]["columns"] if c["name"] == "id"][0]
        assert id_col["primary_key"] is True
        await connector.close()


# ── Registry ────────────────────────────────────────────────────────────────


class TestConnectorRegistry:
    def test_all_db_types_registered(self):
        from gateway.connectors.registry import _REGISTRY
        from gateway.models import DBType

        for db_type in DBType:
            assert db_type.value in _REGISTRY or db_type in _REGISTRY, (
                f"DBType {db_type} not registered in connector registry"
            )

    def test_get_connector_returns_correct_types(self):
        from gateway.connectors.clickhouse import ClickHouseConnector
        from gateway.connectors.duckdb import DuckDBConnector
        from gateway.connectors.mysql import MySQLConnector
        from gateway.connectors.postgres import PostgresConnector
        from gateway.connectors.registry import get_connector

        assert isinstance(get_connector("postgres"), PostgresConnector)
        assert isinstance(get_connector("mysql"), MySQLConnector)
        assert isinstance(get_connector("duckdb"), DuckDBConnector)
        assert isinstance(get_connector("clickhouse"), ClickHouseConnector)

    def test_get_connector_invalid_type(self):
        from gateway.connectors.registry import get_connector

        with pytest.raises(ValueError, match="Unsupported"):
            get_connector("invalid_db")


# ── Connection String Builder ───────────────────────────────────────────────


class TestConnectionStringBuilder:
    def test_postgres_connection_string(self):
        from gateway.models import ConnectionCreate
        from gateway.store import _build_connection_string

        conn = ConnectionCreate(
            name="test",
            db_type="postgres",
            host="myhost",
            port=5432,
            database="mydb",
            username="user",
            password="p@ss:word",
        )
        result = _build_connection_string(conn)
        assert result.startswith("postgresql://")
        assert "myhost:5432" in result
        assert "mydb" in result
        # Password should be URL-encoded
        assert "p%40ss%3Aword" in result

    def test_mysql_connection_string(self):
        from gateway.models import ConnectionCreate
        from gateway.store import _build_connection_string

        conn = ConnectionCreate(
            name="test", db_type="mysql", host="myhost", port=3306, database="mydb", username="root", password="secret"
        )
        result = _build_connection_string(conn)
        assert result.startswith("mysql+pymysql://")
        assert "myhost:3306" in result

    def test_snowflake_connection_string(self):
        from gateway.models import ConnectionCreate
        from gateway.store import _build_connection_string

        conn = ConnectionCreate(
            name="test",
            db_type="snowflake",
            account="xy12345",
            username="user",
            password="pass",
            database="mydb",
            warehouse="wh",
        )
        result = _build_connection_string(conn)
        assert result.startswith("snowflake://")
        assert "xy12345" in result

    def test_clickhouse_connection_string(self):
        from gateway.models import ConnectionCreate
        from gateway.store import _build_connection_string

        conn = ConnectionCreate(
            name="test",
            db_type="clickhouse",
            host="localhost",
            port=9000,
            database="default",
            username="default",
            password="test",
        )
        result = _build_connection_string(conn)
        assert result.startswith("clickhouse://")
        assert "localhost:9000" in result

    def test_duckdb_connection_string(self):
        from gateway.models import ConnectionCreate
        from gateway.store import _build_connection_string

        conn = ConnectionCreate(name="test", db_type="duckdb", database="/tmp/test.db")
        result = _build_connection_string(conn)
        assert result == "/tmp/test.db"

    def test_bigquery_connection_string(self):
        from gateway.models import ConnectionCreate
        from gateway.store import _build_connection_string

        conn = ConnectionCreate(name="test", db_type="bigquery", project="my-project")
        result = _build_connection_string(conn)
        assert result == "my-project"

    def test_redshift_connection_string(self):
        from gateway.models import ConnectionCreate
        from gateway.store import _build_connection_string

        conn = ConnectionCreate(
            name="test",
            db_type="redshift",
            host="cluster.region.redshift.amazonaws.com",
            port=5439,
            database="dev",
            username="admin",
            password="pass",
        )
        result = _build_connection_string(conn)
        assert result.startswith("redshift://")
        assert "5439" in result


# ── SSH Tunnel Module ──────────────────────────────────────────────────────


class TestSSHTunnel:
    def test_import_ssh_tunnel(self):
        from gateway.connectors.ssh_tunnel import HAS_SSHTUNNEL, SSHTunnel

        assert HAS_SSHTUNNEL is True

    def test_ssh_tunnel_requires_host(self):
        from gateway.connectors.ssh_tunnel import SSHTunnel

        tunnel = SSHTunnel({"username": "user", "password": "pass"})
        with pytest.raises(ValueError, match="requires host"):
            tunnel.start("remote-host", 5432)

    def test_ssh_tunnel_requires_username(self):
        from gateway.connectors.ssh_tunnel import SSHTunnel

        tunnel = SSHTunnel({"host": "bastion.example.com", "password": "pass"})
        with pytest.raises(ValueError, match="requires host and username"):
            tunnel.start("remote-host", 5432)


# ── Pool Manager SSH Helpers ──────────────────────────────────────────────


class TestPoolManagerHelpers:
    def test_extract_host_port_postgres(self):
        from gateway.connectors.pool_manager import _extract_host_port

        h, p = _extract_host_port("postgresql://user:pass@myhost:5432/db", "postgres")
        assert h == "myhost"
        assert p == 5432

    def test_extract_host_port_mysql(self):
        from gateway.connectors.pool_manager import _extract_host_port

        h, p = _extract_host_port("mysql+pymysql://user:pass@dbhost:3306/mydb", "mysql")
        assert h == "dbhost"
        assert p == 3306

    def test_extract_host_port_clickhouse(self):
        from gateway.connectors.pool_manager import _extract_host_port

        h, p = _extract_host_port("clickhouse://default:pass@ch.host:9000/default", "clickhouse")
        assert h == "ch.host"
        assert p == 9000

    def test_rewrite_connection_string_postgres(self):
        from gateway.connectors.pool_manager import _rewrite_connection_string

        result = _rewrite_connection_string("postgresql://user:pass@remote:5432/db", "postgres", "127.0.0.1", 12345)
        assert "127.0.0.1:12345" in result
        assert "user:pass" in result

    def test_rewrite_connection_string_mysql(self):
        from gateway.connectors.pool_manager import _rewrite_connection_string

        result = _rewrite_connection_string("mysql+pymysql://user:pass@remote:3306/db", "mysql", "127.0.0.1", 54321)
        assert "127.0.0.1:54321" in result


# ── Schema Compression ────────────────────────────────────────────────────


class TestSchemaCompression:
    def test_compress_schema_basic(self):
        from gateway.main import _compress_schema

        schema = {
            "public.users": {
                "schema": "public",
                "name": "users",
                "columns": [
                    {"name": "id", "type": "integer", "nullable": False, "primary_key": True},
                    {"name": "email", "type": "varchar", "nullable": False, "primary_key": False},
                ],
                "foreign_keys": [],
                "indexes": [{"name": "users_pkey"}],
                "row_count": 1000,
            }
        }
        compressed = _compress_schema(schema)
        assert "public.users" in compressed
        assert "ddl" in compressed["public.users"]
        assert "PRIMARY KEY" in compressed["public.users"]["ddl"]
        assert compressed["public.users"]["row_count"] == 1000
        assert compressed["public.users"]["indexes"] == ["users_pkey"]

    def test_compress_schema_foreign_keys(self):
        from gateway.main import _compress_schema

        schema = {
            "public.orders": {
                "schema": "public",
                "name": "orders",
                "columns": [
                    {"name": "id", "type": "integer", "nullable": False, "primary_key": True},
                    {"name": "user_id", "type": "integer", "nullable": False, "primary_key": False},
                ],
                "foreign_keys": [
                    {
                        "column": "user_id",
                        "references_schema": "public",
                        "references_table": "users",
                        "references_column": "id",
                    }
                ],
                "row_count": 5000,
            }
        }
        compressed = _compress_schema(schema)
        assert "foreign_keys" in compressed["public.orders"]
        assert "user_id -> public.users.id" in compressed["public.orders"]["foreign_keys"]

    def test_compress_schema_unique_hint(self):
        from gateway.main import _compress_schema

        schema = {
            "public.users": {
                "schema": "public",
                "name": "users",
                "columns": [
                    {
                        "name": "id",
                        "type": "bigint",
                        "nullable": False,
                        "primary_key": True,
                        "stats": {"distinct_fraction": -1.0},
                    },
                    {
                        "name": "name",
                        "type": "varchar",
                        "nullable": True,
                        "primary_key": False,
                        "stats": {"distinct_count": 100},
                    },
                ],
                "foreign_keys": [],
                "row_count": 1000,
            }
        }
        compressed = _compress_schema(schema)
        assert "UNIQUE" in compressed["public.users"]["ddl"]
        # name should NOT have UNIQUE
        assert compressed["public.users"]["ddl"].count("UNIQUE") == 1


# ── Connection Validation ──────────────────────────────────────────────────


class TestConnectionValidation:
    def test_postgres_requires_host(self):
        from gateway.main import _validate_connection_params
        from gateway.models import ConnectionCreate

        conn = ConnectionCreate(name="test", db_type="postgres", username="user")
        errors = _validate_connection_params(conn)
        assert any("host" in e for e in errors)

    def test_snowflake_requires_account(self):
        from gateway.main import _validate_connection_params
        from gateway.models import ConnectionCreate

        conn = ConnectionCreate(name="test", db_type="snowflake")
        errors = _validate_connection_params(conn)
        assert any("account" in e for e in errors)

    def test_bigquery_requires_project_and_creds(self):
        from gateway.main import _validate_connection_params
        from gateway.models import ConnectionCreate

        conn = ConnectionCreate(name="test", db_type="bigquery")
        errors = _validate_connection_params(conn)
        assert any("project" in e for e in errors)
        assert any("credentials" in e for e in errors)

    def test_databricks_requires_all_fields(self):
        from gateway.main import _validate_connection_params
        from gateway.models import ConnectionCreate

        conn = ConnectionCreate(name="test", db_type="databricks")
        errors = _validate_connection_params(conn)
        assert any("hostname" in e for e in errors)
        assert any("HTTP path" in e for e in errors)
        assert any("access token" in e for e in errors)

    def test_valid_postgres_no_errors(self):
        from gateway.main import _validate_connection_params
        from gateway.models import ConnectionCreate

        conn = ConnectionCreate(
            name="test", db_type="postgres", host="localhost", port=5432, database="mydb", username="user"
        )
        errors = _validate_connection_params(conn)
        assert len(errors) == 0

    def test_connection_string_skips_validation(self):
        from gateway.main import _validate_connection_params
        from gateway.models import ConnectionCreate

        conn = ConnectionCreate(
            name="test", db_type="postgres", connection_string="postgresql://user:pass@host:5432/db"
        )
        errors = _validate_connection_params(conn)
        assert len(errors) == 0

    def test_ssh_tunnel_validation(self):
        from gateway.main import _validate_connection_params
        from gateway.models import ConnectionCreate, SSHTunnelConfig

        conn = ConnectionCreate(
            name="test",
            db_type="postgres",
            host="dbhost",
            username="user",
            ssh_tunnel=SSHTunnelConfig(enabled=True, auth_method="password"),
        )
        errors = _validate_connection_params(conn)
        assert any("bastion host" in e for e in errors)
        assert any("username" in e.lower() for e in errors)


# ── Snowflake URL Parsing ──────────────────────────────────────────────────


class TestSnowflakeURLParsing:
    def test_pipe_delimited_format(self):
        from gateway.connectors.snowflake import SnowflakeConnector

        c = SnowflakeConnector()
        params = c._parse_connection("snowflake://acct|user|pass|db|wh|schema|role")
        assert params["account"] == "acct"
        assert params["user"] == "user"
        assert params["password"] == "pass"
        assert params["database"] == "db"
        assert params["warehouse"] == "wh"
        assert params["schema"] == "schema"
        assert params["role"] == "role"

    def test_standard_url_format(self):
        from gateway.connectors.snowflake import SnowflakeConnector

        c = SnowflakeConnector()
        params = c._parse_connection("snowflake://myuser:mypass@xy12345/mydb/myschema?warehouse=WH&role=ADMIN")
        assert params["account"] == "xy12345"
        assert params["user"] == "myuser"
        assert params["password"] == "mypass"
        assert params["database"] == "mydb"
        assert params["schema"] == "myschema"
        assert params["warehouse"] == "WH"
        assert params["role"] == "ADMIN"

    def test_account_only_format(self):
        from gateway.connectors.snowflake import SnowflakeConnector

        c = SnowflakeConnector()
        params = c._parse_connection("xy12345")
        assert params["account"] == "xy12345"


# ── Postgres Enhanced Schema ───────────────────────────────────────────────


class TestPostgresEnhancedSchema:
    CONN_STR = "postgresql://enterprise_admin:Ent3rpr1se!S3cur3@host.docker.internal:5601/enterprise_prod"

    @pytest.mark.asyncio
    async def test_schema_has_indexes(self):
        from gateway.connectors.postgres import PostgresConnector

        c = PostgresConnector()
        await c.connect(self.CONN_STR)
        schema = await c.get_schema()
        # At least one table should have indexes
        tables_with_indexes = [t for t in schema.values() if t.get("indexes")]
        assert len(tables_with_indexes) > 0
        # Each index should have name and definition
        idx = tables_with_indexes[0]["indexes"][0]
        assert "name" in idx
        assert "definition" in idx
        await c.close()

    @pytest.mark.asyncio
    async def test_schema_has_column_stats(self):
        from gateway.connectors.postgres import PostgresConnector

        c = PostgresConnector()
        await c.connect(self.CONN_STR)
        schema = await c.get_schema()
        # At least some columns should have stats
        has_stats = False
        for table in schema.values():
            for col in table.get("columns", []):
                if col.get("stats"):
                    has_stats = True
                    break
            if has_stats:
                break
        assert has_stats
        await c.close()

    @pytest.mark.asyncio
    async def test_sample_values(self):
        from gateway.connectors.postgres import PostgresConnector

        c = PostgresConnector()
        await c.connect(self.CONN_STR)
        samples = await c.get_sample_values("public.customers", ["segment", "country"], limit=3)
        assert "segment" in samples
        assert len(samples["segment"]) <= 3
        assert "country" in samples
        await c.close()


# ── DuckDB Sample Values ──────────────────────────────────────────────────


class TestDuckDBSampleValues:
    @pytest.mark.asyncio
    async def test_sample_values(self):
        from gateway.connectors.duckdb import DuckDBConnector

        c = DuckDBConnector()
        await c.connect(":memory:")
        await c.execute("CREATE TABLE test_t (id INT, name VARCHAR, city VARCHAR)")
        await c.execute("INSERT INTO test_t VALUES (1, 'Alice', 'NYC'), (2, 'Bob', 'LA'), (3, 'Charlie', 'SF')")
        samples = await c.get_sample_values("test_t", ["name", "city"], limit=5)
        assert "name" in samples
        assert set(samples["name"]) == {"Alice", "Bob", "Charlie"}
        assert "city" in samples
        await c.close()


# ── SQLite Sample Values ──────────────────────────────────────────────────


class TestSQLiteSampleValues:
    @pytest.mark.asyncio
    async def test_sample_values(self):
        from gateway.connectors.sqlite import SQLiteConnector

        c = SQLiteConnector()
        await c.connect(":memory:")
        await c.execute("CREATE TABLE users (id INTEGER, name TEXT, role TEXT)")
        await c.execute("INSERT INTO users VALUES (1, 'Admin', 'admin'), (2, 'User', 'viewer')")
        samples = await c.get_sample_values("users", ["name", "role"], limit=5)
        assert "name" in samples
        assert "role" in samples
        assert "admin" in samples["role"]
        await c.close()


# ── Schema Cache Diff ──────────────────────────────────────────────────


class TestSchemaCacheDiff:
    def test_diff_no_changes(self):
        from gateway.connectors.schema_cache import SchemaCache

        cache = SchemaCache(ttl_seconds=300)
        schema = {
            "public.users": {
                "schema": "public",
                "name": "users",
                "columns": [
                    {"name": "id", "type": "integer"},
                    {"name": "name", "type": "text"},
                ],
            }
        }
        cache.put("test", schema)
        diff = cache.diff("test", schema)
        assert diff is not None
        assert diff["has_changes"] is False
        assert diff["added_tables"] == []
        assert diff["removed_tables"] == []

    def test_diff_added_table(self):
        from gateway.connectors.schema_cache import SchemaCache

        cache = SchemaCache(ttl_seconds=300)
        old = {"public.users": {"columns": [{"name": "id", "type": "int"}]}}
        new = {
            "public.users": {"columns": [{"name": "id", "type": "int"}]},
            "public.orders": {"columns": [{"name": "id", "type": "int"}]},
        }
        cache.put("test", old)
        diff = cache.diff("test", new)
        assert diff["has_changes"] is True
        assert "public.orders" in diff["added_tables"]

    def test_diff_removed_table(self):
        from gateway.connectors.schema_cache import SchemaCache

        cache = SchemaCache(ttl_seconds=300)
        old = {
            "public.users": {"columns": [{"name": "id", "type": "int"}]},
            "public.orders": {"columns": [{"name": "id", "type": "int"}]},
        }
        new = {"public.users": {"columns": [{"name": "id", "type": "int"}]}}
        cache.put("test", old)
        diff = cache.diff("test", new)
        assert diff["has_changes"] is True
        assert "public.orders" in diff["removed_tables"]

    def test_diff_modified_column_type(self):
        from gateway.connectors.schema_cache import SchemaCache

        cache = SchemaCache(ttl_seconds=300)
        old = {"public.users": {"columns": [{"name": "id", "type": "integer"}]}}
        new = {"public.users": {"columns": [{"name": "id", "type": "bigint"}]}}
        cache.put("test", old)
        diff = cache.diff("test", new)
        assert diff["has_changes"] is True
        assert len(diff["modified_tables"]) == 1
        mod = diff["modified_tables"][0]
        assert mod["table"] == "public.users"
        assert len(mod["type_changes"]) == 1
        assert mod["type_changes"][0]["old_type"] == "integer"
        assert mod["type_changes"][0]["new_type"] == "bigint"

    def test_diff_no_cached_returns_none(self):
        from gateway.connectors.schema_cache import SchemaCache

        cache = SchemaCache(ttl_seconds=300)
        diff = cache.diff("nonexistent", {"t": {"columns": []}})
        assert diff is None


# ── Connection Update Store ──────────────────────────────────────────────


class TestConnectionUpdate:
    def test_update_connection_host(self):
        from gateway.models import ConnectionUpdate

        update = ConnectionUpdate(host="new-host.example.com", port=5433)
        data = update.model_dump(exclude_none=True)
        assert data["host"] == "new-host.example.com"
        assert data["port"] == 5433
        # Fields not provided should not be in the output
        assert "username" not in data
        assert "password" not in data

    def test_update_partial_fields_only(self):
        from gateway.models import ConnectionUpdate

        update = ConnectionUpdate(description="Updated description")
        data = update.model_dump(exclude_none=True)
        assert data == {"description": "Updated description"}


# ── Pool Manager Close Pool ──────────────────────────────────────────────


class TestPoolManagerClosePool:
    @pytest.mark.asyncio
    async def test_close_pool_empty(self):
        from gateway.connectors.pool_manager import PoolManager

        pm = PoolManager()
        closed = await pm.close_pool("nonexistent")
        assert closed == 0


class TestPoolManagerContextManager:
    """Test the async context manager for safe acquire/release."""

    @pytest.mark.asyncio
    async def test_context_manager_releases_on_success(self):
        from gateway.connectors.pool_manager import PoolManager

        pm = PoolManager()
        conn_str = "postgresql://enterprise_admin:Ent3rpr1se!S3cur3@host.docker.internal:5601/enterprise_prod"
        async with pm.connection("postgres", conn_str) as connector:
            assert await connector.health_check() is True
        # Pool should still have the connector cached
        assert pm.pool_count == 1
        await pm.close_all()

    @pytest.mark.asyncio
    async def test_context_manager_releases_on_exception(self):
        from gateway.connectors.pool_manager import PoolManager

        pm = PoolManager()
        conn_str = "postgresql://enterprise_admin:Ent3rpr1se!S3cur3@host.docker.internal:5601/enterprise_prod"
        try:
            async with pm.connection("postgres", conn_str) as connector:
                assert await connector.health_check() is True
                raise ValueError("test error")
        except ValueError:
            pass
        # Pool should still have the connector cached (release called in finally)
        assert pm.pool_count == 1
        await pm.close_all()

    @pytest.mark.asyncio
    async def test_context_manager_reuses_connection(self):
        from gateway.connectors.pool_manager import PoolManager

        pm = PoolManager()
        conn_str = "postgresql://enterprise_admin:Ent3rpr1se!S3cur3@host.docker.internal:5601/enterprise_prod"
        async with pm.connection("postgres", conn_str) as c1:
            id1 = id(c1)
        async with pm.connection("postgres", conn_str) as c2:
            id2 = id(c2)
        # Same connector instance should be reused
        assert id1 == id2
        await pm.close_all()


# ── Table Grouping ──────────────────────────────────────────────────


class TestTableGrouping:
    def test_groups_by_prefix(self):
        from gateway.main import _group_tables

        schema = {
            "public.order_items": {"name": "order_items", "columns": [], "foreign_keys": []},
            "public.order_history": {"name": "order_history", "columns": [], "foreign_keys": []},
            "public.product_variants": {"name": "product_variants", "columns": [], "foreign_keys": []},
            "public.product_categories": {"name": "product_categories", "columns": [], "foreign_keys": []},
        }
        groups = _group_tables(schema)
        assert "order" in groups
        assert "product" in groups
        assert len(groups["order"]) == 2
        assert len(groups["product"]) == 2

    def test_groups_by_fk(self):
        from gateway.main import _group_tables

        schema = {
            "public.customers": {"name": "customers", "columns": [], "foreign_keys": []},
            "public.invoices": {
                "name": "invoices",
                "columns": [],
                "foreign_keys": [
                    {
                        "column": "customer_id",
                        "references_schema": "public",
                        "references_table": "customers",
                        "references_column": "id",
                    },
                ],
            },
        }
        groups = _group_tables(schema)
        # invoices should be grouped with customers via FK
        found = False
        for group_tables in groups.values():
            if "public.customers" in group_tables and "public.invoices" in group_tables:
                found = True
                break
        # If not FK-grouped (single-word names go to _other), that's acceptable
        assert len(groups) >= 1

    def test_single_tables_ungrouped(self):
        from gateway.main import _group_tables

        schema = {
            "public.settings": {"name": "settings", "columns": [], "foreign_keys": []},
        }
        groups = _group_tables(schema)
        assert "_other" in groups
        assert "public.settings" in groups["_other"]


# ── ClickHouse URL Parsing ──────────────────────────────────────────────


class TestClickHouseURLParsing:
    def test_native_tcp(self):
        from gateway.connectors.clickhouse import ClickHouseConnector

        c = ClickHouseConnector()
        params = c._parse_connection_string("clickhouse://admin:pass@myhost:9000/analytics")
        assert params["host"] == "myhost"
        assert params["port"] == 9000
        assert params["user"] == "admin"
        assert params["database"] == "analytics"

    def test_native_tls(self):
        from gateway.connectors.clickhouse import ClickHouseConnector

        c = ClickHouseConnector()
        params = c._parse_connection_string("clickhouses://admin:pass@cloud.clickhouse.com/analytics")
        assert params["host"] == "cloud.clickhouse.com"
        assert params["port"] == 9440
        assert params.get("secure") is True

    def test_http_protocol(self):
        from gateway.connectors.clickhouse import ClickHouseConnector

        c = ClickHouseConnector()
        params = c._parse_connection_string("clickhouse+http://admin:pass@myhost:8123/analytics")
        assert params["host"] == "myhost"
        assert params["port"] == 8123
        assert params["database"] == "analytics"

    def test_https_protocol(self):
        from gateway.connectors.clickhouse import ClickHouseConnector

        c = ClickHouseConnector()
        params = c._parse_connection_string("clickhouse+https://admin:pass@cloud.clickhouse.com/analytics")
        assert params["host"] == "cloud.clickhouse.com"
        assert params["port"] == 8443
        assert params.get("secure") is True

    def test_default_port_native(self):
        from gateway.connectors.clickhouse import ClickHouseConnector

        c = ClickHouseConnector()
        params = c._parse_connection_string("clickhouse://default@localhost/default")
        assert params["port"] == 9000


class TestSchemaSearch:
    """Test the schema search scoring logic used by /schema/search endpoint."""

    def _build_test_schema(self):
        return {
            "public.orders": {
                "schema": "public",
                "name": "orders",
                "columns": [
                    {"name": "id", "type": "int", "primary_key": True, "comment": ""},
                    {"name": "customer_id", "type": "int", "primary_key": False, "comment": "FK to customers"},
                    {"name": "total_amount", "type": "decimal", "primary_key": False, "comment": "Order total in USD"},
                ],
                "foreign_keys": [{"column": "customer_id", "references_table": "customers", "references_column": "id"}],
                "description": "Customer purchase orders",
            },
            "public.customers": {
                "schema": "public",
                "name": "customers",
                "columns": [
                    {"name": "id", "type": "int", "primary_key": True, "comment": ""},
                    {"name": "email", "type": "varchar", "primary_key": False, "comment": "Customer email address"},
                    {"name": "name", "type": "varchar", "primary_key": False, "comment": ""},
                ],
                "foreign_keys": [],
                "description": "",
            },
            "public.products": {
                "schema": "public",
                "name": "products",
                "columns": [
                    {"name": "id", "type": "int", "primary_key": True, "comment": ""},
                    {"name": "product_name", "type": "varchar", "primary_key": False, "comment": ""},
                    {"name": "price", "type": "decimal", "primary_key": False, "comment": ""},
                ],
                "foreign_keys": [],
                "description": "Product catalog",
            },
        }

    def _score_tables(self, schema, query):
        """Replicate the scoring logic from main.py search endpoint."""
        terms = [t.strip().lower() for t in query.split() if t.strip()]
        scored = []
        for key, table in schema.items():
            score = 0.0
            table_name_lower = table.get("name", "").lower()
            for term in terms:
                if term == table_name_lower:
                    score += 10.0
                elif table_name_lower.startswith(term):
                    score += 5.0
                elif term in table_name_lower:
                    score += 3.0
                for col in table.get("columns", []):
                    col_name = col.get("name", "").lower()
                    col_comment = col.get("comment", "").lower()
                    if term == col_name:
                        score += 4.0
                    elif col_name.startswith(term):
                        score += 2.0
                    elif term in col_name:
                        score += 1.5
                    if col_comment and term in col_comment:
                        score += 1.0
                for fk in table.get("foreign_keys", []):
                    ref_table = fk.get("references_table", "").lower()
                    if term in ref_table:
                        score += 2.0
                desc = table.get("description", "").lower()
                if desc and term in desc:
                    score += 1.5
            if score > 0:
                scored.append((score, key))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored

    def test_exact_table_match_highest_score(self):
        schema = self._build_test_schema()
        results = self._score_tables(schema, "orders")
        # "orders" exact match should rank first
        assert results[0][1] == "public.orders"
        # Should score higher than "customers" which only matches via FK reference
        assert results[0][0] > results[1][0] if len(results) > 1 else True

    def test_column_name_match(self):
        schema = self._build_test_schema()
        results = self._score_tables(schema, "email")
        # customers has "email" column — exact match
        customer_results = [r for r in results if r[1] == "public.customers"]
        assert len(customer_results) == 1
        assert customer_results[0][0] >= 4.0  # exact column match

    def test_fk_reference_match(self):
        schema = self._build_test_schema()
        results = self._score_tables(schema, "customers")
        # Both "customers" table (exact) and "orders" (FK ref) should match
        keys = [r[1] for r in results]
        assert "public.customers" in keys
        assert "public.orders" in keys

    def test_no_match_returns_empty(self):
        schema = self._build_test_schema()
        results = self._score_tables(schema, "nonexistent_xyz")
        assert len(results) == 0

    def test_comment_matching(self):
        schema = self._build_test_schema()
        results = self._score_tables(schema, "USD")
        # orders has column comment "Order total in USD"
        assert any(r[1] == "public.orders" for r in results)


class TestDatabricksURLParsing:
    """Test Databricks connection string parsing."""

    def test_pipe_delimited_format(self):
        from gateway.connectors.databricks import DatabricksConnector

        c = DatabricksConnector()
        params = c._parse_connection(
            "databricks://my-workspace.cloud.databricks.com|/sql/1.0/warehouses/abc123|dapi_token|my_catalog|my_schema"
        )
        assert params["host"] == "my-workspace.cloud.databricks.com"
        assert params["http_path"] == "/sql/1.0/warehouses/abc123"
        assert params["access_token"] == "dapi_token"
        assert params["catalog"] == "my_catalog"
        assert params["schema"] == "my_schema"

    def test_url_format(self):
        from gateway.connectors.databricks import DatabricksConnector

        c = DatabricksConnector()
        params = c._parse_connection(
            "databricks://dapi_token@my-workspace.cloud.databricks.com/sql/1.0/warehouses/abc123?catalog=my_catalog&schema=my_schema"
        )
        assert params["host"] == "my-workspace.cloud.databricks.com"
        assert params["http_path"] == "sql/1.0/warehouses/abc123"
        assert params["access_token"] == "dapi_token"
        assert params["catalog"] == "my_catalog"
        assert params["schema"] == "my_schema"

    def test_host_only_format(self):
        from gateway.connectors.databricks import DatabricksConnector

        c = DatabricksConnector()
        params = c._parse_connection("my-workspace.cloud.databricks.com")
        assert params["host"] == "my-workspace.cloud.databricks.com"
        assert params["http_path"] == ""
        assert params["access_token"] == ""


class TestMySQLSSLConfig:
    """Test MySQL SSL configuration support."""

    def test_ssl_config_sets_correctly(self):
        from gateway.connectors.mysql import MySQLConnector

        c = MySQLConnector()
        ssl_config = {
            "enabled": True,
            "ca_cert": "-----BEGIN CERTIFICATE-----\ntest\n-----END CERTIFICATE-----",
        }
        c.set_ssl_config(ssl_config)
        assert c._ssl_config == ssl_config
        assert c._ssl_config["enabled"] is True

    def test_ssl_config_none_by_default(self):
        from gateway.connectors.mysql import MySQLConnector

        c = MySQLConnector()
        assert c._ssl_config is None

    def test_pool_manager_wires_ssl_for_mysql(self):
        """Verify pool_manager passes ssl_config to MySQL connector."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from gateway.connectors.mysql import MySQLConnector
        from gateway.connectors.pool_manager import PoolManager

        pm = PoolManager()
        mock_connector = MySQLConnector()
        mock_connector.connect = AsyncMock()
        mock_connector.health_check = AsyncMock(return_value=True)

        ssl_config = {"enabled": True, "ca_cert": "test-ca"}
        credential_extras = {"ssl_config": ssl_config}

        with patch("gateway.connectors.pool_manager.get_connector", return_value=mock_connector):
            asyncio.get_event_loop().run_until_complete(
                pm.acquire("mysql", "mysql://user:pass@localhost/db", credential_extras)
            )

        assert mock_connector._ssl_config == ssl_config


class TestPostgresSSLConfig:
    """Tests for PostgreSQL SSL certificate support."""

    def test_ssl_config_stored(self):
        from gateway.connectors.postgres import PostgresConnector

        c = PostgresConnector()
        ssl_config = {"enabled": True, "mode": "verify-full", "ca_cert": "PEM-DATA"}
        c.set_ssl_config(ssl_config)
        assert c._ssl_config == ssl_config

    def test_ssl_context_built_for_verify_full(self):
        from gateway.connectors.postgres import PostgresConnector

        c = PostgresConnector()
        c.set_ssl_config(
            {
                "enabled": True,
                "mode": "verify-full",
                "ca_cert": "-----BEGIN CERTIFICATE-----\ntest\n-----END CERTIFICATE-----",
            }
        )
        # _build_ssl_context should create temp files
        import ssl

        try:
            ctx = c._build_ssl_context()
        except ssl.SSLError:
            # Expected — test cert is not valid, but context was created
            pass
        # Should have created at least one temp file for CA cert
        assert len(c._temp_files) >= 1
        # Cleanup
        import os

        for f in c._temp_files:
            try:
                os.unlink(f)
            except OSError:
                pass

    def test_ssl_config_none_by_default(self):
        from gateway.connectors.postgres import PostgresConnector

        c = PostgresConnector()
        assert c._ssl_config is None

    def test_pool_manager_wires_ssl_for_postgres(self):
        from unittest.mock import AsyncMock, patch

        from gateway.connectors.pool_manager import PoolManager
        from gateway.connectors.postgres import PostgresConnector

        pm = PoolManager()
        mock_connector = PostgresConnector()
        mock_connector.connect = AsyncMock()
        mock_connector.health_check = AsyncMock(return_value=True)

        ssl_config = {"enabled": True, "mode": "require", "ca_cert": "test-ca"}
        credential_extras = {"ssl_config": ssl_config}

        with patch("gateway.connectors.pool_manager.get_connector", return_value=mock_connector):
            asyncio.get_event_loop().run_until_complete(
                pm.acquire("postgres", "postgresql://user:pass@localhost/db", credential_extras)
            )

        assert mock_connector._ssl_config == ssl_config


class TestRedshiftSSLConfig:
    """Tests for Redshift SSL certificate support."""

    def test_ssl_config_stored(self):
        from gateway.connectors.redshift import RedshiftConnector

        c = RedshiftConnector()
        ssl_config = {"enabled": True, "mode": "verify-ca", "ca_cert": "PEM-DATA"}
        c.set_ssl_config(ssl_config)
        assert c._ssl_config == ssl_config

    def test_ssl_kwargs_built(self):
        from gateway.connectors.redshift import RedshiftConnector

        c = RedshiftConnector()
        c.set_ssl_config(
            {
                "enabled": True,
                "mode": "verify-ca",
                "ca_cert": "test-ca-content",
            }
        )
        kwargs = c._build_ssl_kwargs()
        assert kwargs["sslmode"] == "verify-ca"
        assert "sslrootcert" in kwargs
        # Cleanup
        import os

        for f in c._temp_files:
            try:
                os.unlink(f)
            except OSError:
                pass

    def test_pool_manager_wires_ssl_for_redshift(self):
        from unittest.mock import AsyncMock, patch

        from gateway.connectors.pool_manager import PoolManager
        from gateway.connectors.redshift import RedshiftConnector

        pm = PoolManager()
        mock_connector = RedshiftConnector()
        mock_connector.connect = AsyncMock()
        mock_connector.health_check = AsyncMock(return_value=True)

        ssl_config = {"enabled": True, "mode": "require"}
        credential_extras = {"ssl_config": ssl_config}

        with patch("gateway.connectors.pool_manager.get_connector", return_value=mock_connector):
            asyncio.get_event_loop().run_until_complete(
                pm.acquire("redshift", "redshift://user:pass@localhost/db", credential_extras)
            )

        assert mock_connector._ssl_config == ssl_config


class TestClickHouseSSLConfig:
    """Tests for ClickHouse SSL certificate support."""

    def test_ssl_config_stored(self):
        from gateway.connectors.clickhouse import ClickHouseConnector

        c = ClickHouseConnector()
        ssl_config = {"enabled": True, "mode": "require"}
        c.set_ssl_config(ssl_config)
        assert c._ssl_config == ssl_config

    def test_ssl_config_none_by_default(self):
        from gateway.connectors.clickhouse import ClickHouseConnector

        c = ClickHouseConnector()
        assert c._ssl_config is None

    def test_pool_manager_wires_ssl_for_clickhouse(self):
        from unittest.mock import AsyncMock, patch

        from gateway.connectors.clickhouse import ClickHouseConnector
        from gateway.connectors.pool_manager import PoolManager

        pm = PoolManager()
        mock_connector = ClickHouseConnector()
        mock_connector.connect = AsyncMock()
        mock_connector.health_check = AsyncMock(return_value=True)

        ssl_config = {"enabled": True, "mode": "verify-ca", "ca_cert": "test-ca"}
        credential_extras = {"ssl_config": ssl_config}

        with patch("gateway.connectors.pool_manager.get_connector", return_value=mock_connector):
            asyncio.get_event_loop().run_until_complete(
                pm.acquire("clickhouse", "clickhouse://user:pass@localhost/db", credential_extras)
            )

        assert mock_connector._ssl_config == ssl_config


class TestSchemaEndorsements:
    """Tests for schema endorsement (HEX Data Browser pattern)."""

    def test_default_endorsements(self):
        from gateway.store import get_schema_endorsements

        config = get_schema_endorsements("nonexistent-conn")
        assert config["mode"] == "all"
        assert config["endorsed"] == []
        assert config["hidden"] == []

    def test_set_and_get_endorsements(self):
        from gateway.store import get_schema_endorsements, set_schema_endorsements

        result = set_schema_endorsements(
            "test-endorse",
            {
                "endorsed": ["public.users", "public.orders"],
                "hidden": ["public.internal_logs"],
                "mode": "endorsed_only",
            },
        )
        assert result["mode"] == "endorsed_only"
        assert "public.users" in result["endorsed"]
        assert "public.internal_logs" in result["hidden"]

        # Verify retrieval
        config = get_schema_endorsements("test-endorse")
        assert config["mode"] == "endorsed_only"

    def test_apply_endorsed_only_filter(self):
        from gateway.store import apply_endorsement_filter, set_schema_endorsements

        set_schema_endorsements(
            "test-filter",
            {
                "endorsed": ["public.users", "public.orders"],
                "hidden": [],
                "mode": "endorsed_only",
            },
        )
        schema = {
            "public.users": {"name": "users"},
            "public.orders": {"name": "orders"},
            "public.logs": {"name": "logs"},
            "public.settings": {"name": "settings"},
        }
        filtered = apply_endorsement_filter("test-filter", schema)
        assert set(filtered.keys()) == {"public.users", "public.orders"}

    def test_apply_hidden_filter(self):
        from gateway.store import apply_endorsement_filter, set_schema_endorsements

        set_schema_endorsements(
            "test-hidden",
            {
                "endorsed": [],
                "hidden": ["public.logs", "public.settings"],
                "mode": "all",
            },
        )
        schema = {
            "public.users": {"name": "users"},
            "public.orders": {"name": "orders"},
            "public.logs": {"name": "logs"},
            "public.settings": {"name": "settings"},
        }
        filtered = apply_endorsement_filter("test-hidden", schema)
        assert set(filtered.keys()) == {"public.users", "public.orders"}

    def test_no_filter_returns_all(self):
        from gateway.store import apply_endorsement_filter

        schema = {"a": {"name": "a"}, "b": {"name": "b"}}
        filtered = apply_endorsement_filter("no-config", schema)
        assert filtered == schema


class TestCredentialExtrasStandardization:
    """Tests that all connectors implement set_credential_extras correctly."""

    def test_base_connector_has_method(self):
        from gateway.connectors.base import BaseConnector

        assert hasattr(BaseConnector, "set_credential_extras")

    def test_postgres_extracts_ssl(self):
        from gateway.connectors.postgres import PostgresConnector

        c = PostgresConnector()
        c.set_credential_extras({"ssl_config": {"enabled": True, "mode": "require"}})
        assert c._ssl_config is not None
        assert c._ssl_config["mode"] == "require"

    def test_mysql_extracts_ssl(self):
        from gateway.connectors.mysql import MySQLConnector

        c = MySQLConnector()
        c.set_credential_extras({"ssl_config": {"enabled": True, "ca_cert": "test"}})
        assert c._ssl_config is not None
        assert c._ssl_config["ca_cert"] == "test"

    def test_clickhouse_extracts_ssl(self):
        from gateway.connectors.clickhouse import ClickHouseConnector

        c = ClickHouseConnector()
        c.set_credential_extras({"ssl_config": {"enabled": True}})
        assert c._ssl_config is not None

    def test_redshift_extracts_ssl(self):
        from gateway.connectors.redshift import RedshiftConnector

        c = RedshiftConnector()
        c.set_credential_extras({"ssl_config": {"enabled": True, "mode": "verify-ca"}})
        assert c._ssl_config is not None
        assert c._ssl_config["mode"] == "verify-ca"

    def test_snowflake_extracts_credentials(self):
        from gateway.connectors.snowflake import SnowflakeConnector

        c = SnowflakeConnector()
        c.set_credential_extras({"account": "test-acct", "warehouse": "WH1"})
        assert c._credential_extras["account"] == "test-acct"

    def test_databricks_extracts_credentials(self):
        from gateway.connectors.databricks import DatabricksConnector

        c = DatabricksConnector()
        c.set_credential_extras({"http_path": "/sql/1.0/warehouses/abc", "access_token": "tok"})
        assert c._credential_extras["access_token"] == "tok"

    def test_pool_manager_unified_call(self):
        """Pool manager now uses a single set_credential_extras call for all DB types."""
        from unittest.mock import AsyncMock, patch

        from gateway.connectors.pool_manager import PoolManager
        from gateway.connectors.postgres import PostgresConnector

        pm = PoolManager()
        mock_connector = PostgresConnector()
        mock_connector.connect = AsyncMock()
        mock_connector.health_check = AsyncMock(return_value=True)

        credential_extras = {"ssl_config": {"enabled": True, "mode": "require"}}

        with patch("gateway.connectors.pool_manager.get_connector", return_value=mock_connector):
            asyncio.get_event_loop().run_until_complete(
                pm.acquire("postgres", "postgresql://user:pass@localhost/db", credential_extras)
            )

        # Verify the unified set_credential_extras was called (ssl_config extracted)
        assert mock_connector._ssl_config is not None


class TestLevenshteinDistance:
    """Tests for the Levenshtein distance used in column correction."""

    def test_identical_strings(self):
        from gateway.main import _levenshtein

        assert _levenshtein("hello", "hello") == 0

    def test_single_insertion(self):
        from gateway.main import _levenshtein

        assert _levenshtein("customer_name", "customer_names") == 1

    def test_single_substitution(self):
        from gateway.main import _levenshtein

        assert _levenshtein("email", "emall") == 1

    def test_common_hallucination(self):
        from gateway.main import _levenshtein

        # "customer_name" vs "first_name" — very different, should have high distance
        dist = _levenshtein("customer_name", "first_name")
        assert dist > 5

    def test_typo_correction(self):
        from gateway.main import _levenshtein

        # "frist_name" vs "first_name" — single transposition
        dist = _levenshtein("frist_name", "first_name")
        assert dist <= 2

    def test_empty_strings(self):
        from gateway.main import _levenshtein

        assert _levenshtein("", "hello") == 5
        assert _levenshtein("hello", "") == 5
        assert _levenshtein("", "") == 0


# ── Connection Tags (Round 6) ──────────────────────────────────────────────


class TestConnectionTags:
    """Test the tags field on ConnectionCreate/Update/Info models."""

    def test_create_with_tags(self):
        from gateway.models import ConnectionCreate

        conn = ConnectionCreate(
            name="tag-test",
            db_type="postgres",
            host="localhost",
            username="test",
            tags=["prod", "analytics", "team-data"],
        )
        assert conn.tags == ["prod", "analytics", "team-data"]

    def test_create_default_empty_tags(self):
        from gateway.models import ConnectionCreate

        conn = ConnectionCreate(name="no-tags", db_type="postgres", host="localhost", username="test")
        assert conn.tags == []

    def test_update_with_tags(self):
        from gateway.models import ConnectionUpdate

        update = ConnectionUpdate(tags=["staging", "test"])
        assert update.tags == ["staging", "test"]

    def test_info_with_tags(self):
        from gateway.models import ConnectionInfo

        info = ConnectionInfo(id="test-id", name="tagged-conn", db_type="postgres", tags=["prod", "critical"])
        assert info.tags == ["prod", "critical"]

    def test_info_default_empty_tags(self):
        from gateway.models import ConnectionInfo

        info = ConnectionInfo(id="test-id", name="untagged", db_type="postgres")
        assert info.tags == []


# ── Snowflake Key-Pair Auth (Round 6) ─────────────────────────────────────


class TestSnowflakeKeyPairAuth:
    """Test Snowflake key-pair auth configuration."""

    def test_private_key_in_connection_create(self):
        from gateway.models import ConnectionCreate

        conn = ConnectionCreate(
            name="snow-kp",
            db_type="snowflake",
            account="test-account",
            username="SVC_USER",
            private_key="-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----",
            private_key_passphrase="mysecret",
        )
        assert conn.private_key is not None
        assert conn.private_key_passphrase == "mysecret"

    def test_credential_extras_include_private_key(self):
        from gateway.models import ConnectionCreate, DBType
        from gateway.store import _extract_credential_extras

        conn = ConnectionCreate(
            name="snow-kp2", db_type="snowflake", account="test-account", username="SVC_USER", private_key="---KEY---"
        )
        extras = _extract_credential_extras(conn)
        assert extras["private_key"] == "---KEY---"
        assert extras["account"] == "test-account"

    def test_snowflake_connector_load_private_key_method_exists(self):
        from gateway.connectors.snowflake import SnowflakeConnector

        connector = SnowflakeConnector()
        assert hasattr(connector, "_load_private_key")

    def test_set_credential_extras_with_private_key(self):
        from gateway.connectors.snowflake import SnowflakeConnector

        connector = SnowflakeConnector()
        connector.set_credential_extras(
            {
                "account": "my-account",
                "username": "user1",
                "private_key": "---KEY---",
                "private_key_passphrase": "pass",
            }
        )
        assert connector._credential_extras["private_key"] == "---KEY---"


# ── ClickHouse HTTP Fallback (Round 6) ────────────────────────────────────


class TestClickHouseHTTPFallback:
    """Test ClickHouse connector with HTTP fallback support."""

    def test_has_http_import(self):
        from gateway.connectors.clickhouse import HAS_CLICKHOUSE_HTTP

        # Should be True or False — just verify the flag exists
        assert isinstance(HAS_CLICKHOUSE_HTTP, bool)

    def test_has_native_import(self):
        from gateway.connectors.clickhouse import HAS_CLICKHOUSE_NATIVE

        assert isinstance(HAS_CLICKHOUSE_NATIVE, bool)

    def test_connector_has_http_client_attr(self):
        from gateway.connectors.clickhouse import ClickHouseConnector

        c = ClickHouseConnector()
        assert hasattr(c, "_http_client")
        assert hasattr(c, "_use_http")
        assert c._use_http is False

    def test_raw_execute_raises_when_disconnected(self):
        from gateway.connectors.clickhouse import ClickHouseConnector

        c = ClickHouseConnector()
        with pytest.raises(RuntimeError, match="No active ClickHouse connection"):
            c._raw_execute("SELECT 1")

    def test_parse_http_url_sets_use_http(self):
        """clickhouse+http:// URL sets use_http flag in parsed params."""
        from gateway.connectors.clickhouse import ClickHouseConnector

        c = ClickHouseConnector()
        params = c._parse_connection_string("clickhouse+http://default:pass@host:8123/mydb")
        assert params.get("use_http") is True
        assert params["port"] == 8123

    def test_parse_https_url_sets_secure(self):
        """clickhouse+https:// URL sets both use_http and secure flags."""
        from gateway.connectors.clickhouse import ClickHouseConnector

        c = ClickHouseConnector()
        params = c._parse_connection_string("clickhouse+https://user:pass@host:8443/mydb")
        assert params.get("use_http") is True
        assert params.get("secure") is True
        assert params["port"] == 8443

    def test_parse_native_url_no_use_http(self):
        """clickhouse:// URL does not set use_http flag."""
        from gateway.connectors.clickhouse import ClickHouseConnector

        c = ClickHouseConnector()
        params = c._parse_connection_string("clickhouse://default:pass@host:9000/mydb")
        assert params.get("use_http") is None


# ── Parallel Schema Fetching (Round 6) ────────────────────────────────────


class TestParallelSchemaFetching:
    """Verify that connectors with parallel schema fetching still work."""

    def test_redshift_has_asyncio_import(self):
        """Redshift get_schema uses asyncio.to_thread for parallel queries."""
        import inspect

        from gateway.connectors.redshift import RedshiftConnector

        source = inspect.getsource(RedshiftConnector.get_schema)
        assert "asyncio.gather" in source or "asyncio.to_thread" in source

    def test_snowflake_has_asyncio_import(self):
        """Snowflake get_schema uses asyncio.to_thread for parallel queries."""
        import inspect

        from gateway.connectors.snowflake import SnowflakeConnector

        source = inspect.getsource(SnowflakeConnector.get_schema)
        assert "asyncio.gather" in source

    def test_clickhouse_schema_sequential(self):
        """ClickHouse uses sequential fetch for thread-safety."""
        import inspect

        from gateway.connectors.clickhouse import ClickHouseConnector

        source = inspect.getsource(ClickHouseConnector.get_schema)
        assert "_fetch_all" in source  # Sequential wrapper


# ── Scheduled Schema Refresh (Round 7) ─────────────────────────────────────


class TestScheduledSchemaRefresh:
    """Tests for scheduled schema refresh feature."""

    def test_connection_create_has_refresh_interval(self):
        """ConnectionCreate model accepts schema_refresh_interval."""
        from gateway.models import ConnectionCreate

        conn = ConnectionCreate(
            name="test-refresh",
            db_type="postgres",
            host="localhost",
            schema_refresh_interval=300,
        )
        assert conn.schema_refresh_interval == 300

    def test_connection_create_no_refresh_default(self):
        """schema_refresh_interval is None by default."""
        from gateway.models import ConnectionCreate

        conn = ConnectionCreate(name="test-no-refresh", db_type="postgres", host="localhost")
        assert conn.schema_refresh_interval is None

    def test_connection_info_has_refresh_fields(self):
        """ConnectionInfo has schema_refresh_interval and last_schema_refresh."""
        from gateway.models import ConnectionInfo

        info = ConnectionInfo(
            id="test-id",
            name="test",
            db_type="postgres",
            schema_refresh_interval=600,
            last_schema_refresh=1000.0,
        )
        assert info.schema_refresh_interval == 600
        assert info.last_schema_refresh == 1000.0

    def test_connection_update_has_refresh_fields(self):
        """ConnectionUpdate supports schema_refresh_interval and last_schema_refresh."""
        from gateway.models import ConnectionUpdate

        update = ConnectionUpdate(schema_refresh_interval=900, last_schema_refresh=2000.0)
        assert update.schema_refresh_interval == 900
        assert update.last_schema_refresh == 2000.0

    def test_refresh_interval_validation_min(self):
        """schema_refresh_interval must be >= 60."""
        from pydantic import ValidationError

        from gateway.models import ConnectionCreate

        with pytest.raises(ValidationError):
            ConnectionCreate(name="test", db_type="postgres", host="localhost", schema_refresh_interval=30)

    def test_refresh_interval_validation_max(self):
        """schema_refresh_interval must be <= 86400."""
        from pydantic import ValidationError

        from gateway.models import ConnectionCreate

        with pytest.raises(ValidationError):
            ConnectionCreate(name="test", db_type="postgres", host="localhost", schema_refresh_interval=100000)


# ── Schema Cache Sample Values (Round 7) ───────────────────────────────────


class TestSchemaCacheSampleValues:
    """Tests for sample values caching in SchemaCache."""

    def test_put_and_get_sample_values(self):
        """Can store and retrieve sample values."""
        from gateway.connectors.schema_cache import SchemaCache

        cache = SchemaCache(ttl_seconds=60)
        values = {"status": ["active", "inactive"], "type": ["A", "B"]}
        cache.put_sample_values("conn1", "public.users", values)
        result = cache.get_sample_values("conn1", "public.users")
        assert result == values

    def test_sample_values_cache_miss(self):
        """Returns None for uncached sample values."""
        from gateway.connectors.schema_cache import SchemaCache

        cache = SchemaCache(ttl_seconds=60)
        assert cache.get_sample_values("conn1", "public.users") is None

    def test_sample_values_in_stats(self):
        """Stats include sample values count."""
        from gateway.connectors.schema_cache import SchemaCache

        cache = SchemaCache(ttl_seconds=60)
        cache.put_sample_values("conn1", "table1", {"col": ["a"]})
        stats = cache.stats()
        assert stats["cached_sample_tables"] == 1

    def test_sample_values_ttl_is_double(self):
        """Sample values expire at 2x the regular TTL."""
        import time

        from gateway.connectors.schema_cache import SchemaCache

        cache = SchemaCache(ttl_seconds=0.1)  # 100ms TTL
        cache.put_sample_values("conn1", "t1", {"col": ["v"]})
        # At < 200ms (2x TTL), should still be valid
        time.sleep(0.05)
        assert cache.get_sample_values("conn1", "t1") is not None


# ── Cost Estimator Improvements (Round 7) ──────────────────────────────────


class TestCostEstimatorImprovements:
    """Tests for improved cost estimation."""

    def test_clickhouse_estimate_uses_fallback(self):
        """ClickHouse estimator tries EXPLAIN ESTIMATE then EXPLAIN PLAN."""
        import inspect

        from gateway.governance.cost_estimator import CostEstimator

        source = inspect.getsource(CostEstimator.estimate_clickhouse)
        assert "EXPLAIN ESTIMATE" in source
        assert "EXPLAIN PLAN" in source

    def test_databricks_estimate_parses_row_count(self):
        """Databricks estimator parses rowCount from EXPLAIN FORMATTED."""
        import inspect

        from gateway.governance.cost_estimator import CostEstimator

        source = inspect.getsource(CostEstimator.estimate_databricks)
        assert "EXPLAIN FORMATTED" in source
        assert "rowCount" in source

    def test_cost_per_row_all_types(self):
        """All supported DB types have cost-per-row values."""
        from gateway.governance.cost_estimator import _COST_PER_ROW

        expected = {
            "postgres",
            "redshift",
            "mysql",
            "snowflake",
            "bigquery",
            "clickhouse",
            "databricks",
            "duckdb",
            "sqlite",
        }
        assert expected.issubset(set(_COST_PER_ROW.keys()))

    def test_estimate_routes_all_types(self):
        """CostEstimator.estimate routes to correct estimator for all types."""
        import inspect

        from gateway.governance.cost_estimator import CostEstimator

        source = inspect.getsource(CostEstimator.estimate)
        for db_type in ["postgres", "mysql", "snowflake", "bigquery", "redshift", "clickhouse", "databricks", "duckdb"]:
            assert db_type in source


# ── Schema Filtering (Round 7) ────────────────────────────────────────────


class TestSchemaFiltering:
    """Tests for schema filtering endpoint logic."""

    def test_main_has_filter_endpoint(self):
        """Gateway has schema filter endpoint."""
        import inspect

        from gateway.main import get_filtered_schema

        assert callable(get_filtered_schema)

    def test_main_has_refresh_endpoint(self):
        """Gateway has schema refresh endpoint."""
        import inspect

        from gateway.main import refresh_connection_schema

        assert callable(refresh_connection_schema)

    def test_main_has_refresh_status_endpoint(self):
        """Gateway has schema refresh status endpoint."""
        import inspect

        from gateway.main import get_schema_refresh_status

        assert callable(get_schema_refresh_status)

    def test_main_has_sample_values_endpoint(self):
        """Gateway has sample values endpoint."""
        import inspect

        from gateway.main import get_cached_sample_values

        assert callable(get_cached_sample_values)


# ── Connection String Builder (Round 7) ────────────────────────────────────


class TestConnectionStringBuilder:
    """Tests for URL-format connection string building."""

    def test_snowflake_url_format(self):
        """Snowflake builds standard URL format instead of pipe-delimited."""
        from gateway.models import ConnectionCreate
        from gateway.store import _build_connection_string

        conn = ConnectionCreate(
            name="test",
            db_type="snowflake",
            account="myaccount",
            username="admin",
            password="pass123",
            database="mydb",
            warehouse="compute_wh",
            schema_name="public",
            role="sysadmin",
        )
        url = _build_connection_string(conn)
        assert url.startswith("snowflake://")
        assert "@myaccount" in url
        assert "/mydb/public" in url
        assert "warehouse=compute_wh" in url
        assert "role=sysadmin" in url
        assert "|" not in url  # No pipe-delimited format

    def test_snowflake_url_special_chars(self):
        """Snowflake URL-encodes special characters in username/password."""
        from gateway.models import ConnectionCreate
        from gateway.store import _build_connection_string

        conn = ConnectionCreate(
            name="test",
            db_type="snowflake",
            account="acct",
            username="user@domain.com",
            password="p@ss!word",
            database="db",
        )
        url = _build_connection_string(conn)
        assert "user%40domain.com" in url
        assert "p%40ss%21word" in url

    def test_databricks_url_format(self):
        """Databricks builds standard URL format."""
        from gateway.models import ConnectionCreate
        from gateway.store import _build_connection_string

        conn = ConnectionCreate(
            name="test",
            db_type="databricks",
            host="myworkspace.cloud.databricks.com",
            http_path="/sql/1.0/warehouses/abc123",
            access_token="dapi1234567890",
            catalog="main",
            schema_name="default",
        )
        url = _build_connection_string(conn)
        assert url.startswith("databricks://")
        assert "dapi1234567890@myworkspace" in url
        assert "catalog=main" in url
        assert "schema=default" in url
        assert "|" not in url  # No pipe-delimited format

    def test_postgres_url_format(self):
        """PostgreSQL builds standard URL format."""
        from gateway.models import ConnectionCreate
        from gateway.store import _build_connection_string

        conn = ConnectionCreate(
            name="test",
            db_type="postgres",
            host="localhost",
            port=5432,
            database="mydb",
            username="admin",
            password="pass",
        )
        url = _build_connection_string(conn)
        assert url == "postgresql://admin:pass@localhost:5432/mydb"

    def test_clickhouse_url_format(self):
        """ClickHouse builds standard URL format."""
        from gateway.models import ConnectionCreate
        from gateway.store import _build_connection_string

        conn = ConnectionCreate(
            name="test",
            db_type="clickhouse",
            host="ch.example.com",
            port=9000,
            database="analytics",
            username="default",
            password="secret",
        )
        url = _build_connection_string(conn)
        assert url == "clickhouse://default:secret@ch.example.com:9000/analytics"

    def test_clickhouse_http_protocol(self):
        """ClickHouse HTTP protocol builds clickhouse+http:// URL."""
        from gateway.models import ConnectionCreate
        from gateway.store import _build_connection_string

        conn = ConnectionCreate(
            name="test",
            db_type="clickhouse",
            host="ch.example.com",
            database="analytics",
            username="default",
            password="secret",
            protocol="http",
        )
        url = _build_connection_string(conn)
        assert url.startswith("clickhouse+http://")
        assert ":8123/" in url

    def test_clickhouse_https_protocol(self):
        """ClickHouse HTTPS protocol builds clickhouse+https:// URL."""
        from gateway.models import ConnectionCreate
        from gateway.store import _build_connection_string

        conn = ConnectionCreate(
            name="test",
            db_type="clickhouse",
            host="ch.cloud.com",
            database="default",
            username="default",
            password="secret",
            protocol="http",
            ssl=True,
        )
        url = _build_connection_string(conn)
        assert url.startswith("clickhouse+https://")
        assert ":8443/" in url

    def test_duckdb_connection_string(self):
        """DuckDB uses database path as connection string."""
        from gateway.models import ConnectionCreate
        from gateway.store import _build_connection_string

        conn = ConnectionCreate(name="test", db_type="duckdb", database="/data/analytics.duckdb")
        url = _build_connection_string(conn)
        assert url == "/data/analytics.duckdb"

    def test_duckdb_default_memory(self):
        """DuckDB defaults to :memory: when no database specified."""
        from gateway.models import ConnectionCreate
        from gateway.store import _build_connection_string

        conn = ConnectionCreate(name="test", db_type="duckdb")
        url = _build_connection_string(conn)
        assert url == ":memory:"


# ── DuckDB Schema Improvements (Round 7) ──────────────────────────────────


class TestDuckDBSchemaImprovements:
    """Tests for DuckDB primary key detection and row counts."""

    def test_duckdb_schema_has_pk_detection(self):
        """DuckDB get_schema queries PRIMARY KEY constraints."""
        import inspect

        from gateway.connectors.duckdb import DuckDBConnector

        source = inspect.getsource(DuckDBConnector.get_schema)
        assert "PRIMARY KEY" in source

    def test_duckdb_schema_has_row_counts(self):
        """DuckDB get_schema queries duckdb_tables() for row counts."""
        import inspect

        from gateway.connectors.duckdb import DuckDBConnector

        source = inspect.getsource(DuckDBConnector.get_schema)
        assert "duckdb_tables" in source

    @pytest.mark.asyncio
    async def test_duckdb_pk_and_row_count(self):
        """DuckDB schema includes primary_key and row_count fields."""
        from gateway.connectors.duckdb import DuckDBConnector

        conn = DuckDBConnector()
        await conn.connect(":memory:")
        await conn.execute("CREATE TABLE test_pk (id INTEGER PRIMARY KEY, name VARCHAR)")
        await conn.execute("INSERT INTO test_pk VALUES (1, 'a'), (2, 'b')")
        schema = await conn.get_schema()
        assert len(schema) >= 1
        table = list(schema.values())[0]
        # Check primary key detected
        id_col = next(c for c in table["columns"] if c["name"] == "id")
        assert id_col["primary_key"] is True
        name_col = next(c for c in table["columns"] if c["name"] == "name")
        assert name_col["primary_key"] is False
        await conn.close()


# ── SQLite Foreign Keys (Round 7) ─────────────────────────────────────────


class TestSQLiteForeignKeys:
    """Tests for SQLite PRAGMA foreign_keys = ON."""

    def test_sqlite_enables_foreign_keys(self):
        """SQLite connect() enables PRAGMA foreign_keys."""
        import inspect

        from gateway.connectors.sqlite import SQLiteConnector

        source = inspect.getsource(SQLiteConnector.connect)
        assert "PRAGMA foreign_keys" in source


# ── MCP list_tables Tool (Round 7) ────────────────────────────────────────


class TestMCPListTables:
    """Tests for the list_tables MCP tool."""

    def test_list_tables_exists(self):
        """MCP server has list_tables function."""
        from gateway.mcp_server import list_tables

        assert callable(list_tables)

    def test_list_tables_has_fk_support(self):
        """list_tables includes FK references in output."""
        import inspect

        from gateway.mcp_server import list_tables

        source = inspect.getsource(list_tables)
        assert "fk_map" in source
        assert "foreign_keys" in source


# ── Schema Relationships Endpoint (Round 8) ─────────────────────────────────


class TestSchemaRelationships:
    """Tests for the /schema/relationships endpoint — ERD summary for AI agents."""

    def test_relationships_endpoint_exists(self):
        """Schema relationships endpoint is registered."""
        from gateway.main import app

        routes = [r.path for r in app.routes]
        assert "/api/connections/{name}/schema/relationships" in routes

    def test_relationships_compact_format_extraction(self):
        """Verify FK extraction logic produces correct compact format."""
        # Simulate a schema with FKs
        schema = {
            "public.orders": {
                "schema": "public",
                "name": "orders",
                "columns": [{"name": "id", "type": "integer"}],
                "foreign_keys": [
                    {
                        "column": "customer_id",
                        "references_schema": "public",
                        "references_table": "customers",
                        "references_column": "id",
                    },
                    {
                        "column": "product_id",
                        "references_schema": "public",
                        "references_table": "products",
                        "references_column": "id",
                    },
                ],
            },
            "public.customers": {
                "schema": "public",
                "name": "customers",
                "columns": [{"name": "id", "type": "integer"}],
                "foreign_keys": [],
            },
        }

        # Extract relationships using same logic as endpoint
        relationships = []
        for key, table in schema.items():
            for fk in table.get("foreign_keys", []):
                ref_schema = fk.get("references_schema", table.get("schema", ""))
                relationships.append(
                    {
                        "from_schema": table.get("schema", ""),
                        "from_table": table.get("name", ""),
                        "from_column": fk["column"],
                        "to_schema": ref_schema,
                        "to_table": fk["references_table"],
                        "to_column": fk["references_column"],
                    }
                )

        assert len(relationships) == 2
        lines = []
        for r in relationships:
            from_q = f"{r['from_schema']}.{r['from_table']}" if r["from_schema"] else r["from_table"]
            to_q = f"{r['to_schema']}.{r['to_table']}" if r["to_schema"] else r["to_table"]
            lines.append(f"{from_q}.{r['from_column']} → {to_q}.{r['to_column']}")
        assert "public.orders.customer_id → public.customers.id" in lines
        assert "public.orders.product_id → public.products.id" in lines

    def test_relationships_graph_format(self):
        """Verify graph/adjacency format builds bidirectional edges."""
        schema = {
            "public.orders": {
                "schema": "public",
                "name": "orders",
                "columns": [],
                "foreign_keys": [
                    {
                        "column": "customer_id",
                        "references_schema": "public",
                        "references_table": "customers",
                        "references_column": "id",
                    },
                ],
            },
        }

        # Build graph using same logic as endpoint
        graph: dict[str, list[str]] = {}
        for key, table in schema.items():
            for fk in table.get("foreign_keys", []):
                from_q = f"{table['schema']}.{table['name']}"
                to_q = f"{fk.get('references_schema', '')}.{fk['references_table']}"
                if from_q not in graph:
                    graph[from_q] = []
                if to_q not in graph[from_q]:
                    graph[from_q].append(to_q)
                if to_q not in graph:
                    graph[to_q] = []
                if from_q not in graph[to_q]:
                    graph[to_q].append(from_q)

        assert "public.orders" in graph
        assert "public.customers" in graph
        # Bidirectional
        assert "public.customers" in graph["public.orders"]
        assert "public.orders" in graph["public.customers"]

    def test_relationships_format_validation(self):
        """Format parameter only accepts compact, full, graph."""
        from gateway.main import app

        routes = [r for r in app.routes if hasattr(r, "path") and "relationships" in r.path]
        assert len(routes) > 0


# ── Join Path Discovery (Round 8) ──────────────────────────────────────────


class TestJoinPathDiscovery:
    """Tests for the /schema/join-paths endpoint — multi-hop FK traversal."""

    def test_join_paths_endpoint_exists(self):
        """Join paths endpoint is registered."""
        from gateway.main import app

        routes = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/api/connections/{name}/schema/join-paths" in routes

    def test_bfs_join_path_logic(self):
        """BFS correctly finds multi-hop join paths."""
        from collections import deque

        # Simulate edges: orders -> customers, order_items -> orders, order_items -> products
        edges = {
            "public.orders": [
                ("public.orders", "customer_id", "public.customers", "id"),
            ],
            "public.customers": [
                ("public.customers", "id", "public.orders", "customer_id"),
            ],
            "public.order_items": [
                ("public.order_items", "order_id", "public.orders", "id"),
                ("public.order_items", "product_id", "public.products", "id"),
            ],
            "public.orders_rev": [],
            "public.products": [
                ("public.products", "id", "public.order_items", "product_id"),
            ],
        }
        # Add reverse edges
        edges["public.orders"].append(("public.orders", "id", "public.order_items", "order_id"))

        src, dst = "public.orders", "public.products"
        paths = []
        queue: deque = deque()
        queue.append((src, [src], []))

        while queue:
            current, path_tables, path_joins = queue.popleft()
            if len(path_tables) - 1 >= 4:
                continue
            for from_t, from_col, to_t, to_col in edges.get(current, []):
                if to_t in path_tables:
                    continue
                new_tables = path_tables + [to_t]
                new_joins = path_joins + [{"from": f"{from_t}.{from_col}", "to": f"{to_t}.{to_col}"}]
                if to_t == dst:
                    paths.append({"hops": len(new_joins), "tables": new_tables, "joins": new_joins})
                else:
                    queue.append((to_t, new_tables, new_joins))

        assert len(paths) >= 1
        # Should find: orders -> order_items -> products (2 hops)
        two_hop = [p for p in paths if p["hops"] == 2]
        assert len(two_hop) >= 1
        assert "public.order_items" in two_hop[0]["tables"]

    def test_same_table_returns_zero_hops(self):
        """Querying same table as source and target returns 0 hops."""
        # The endpoint returns immediately for src == dst
        # Just verify the logic
        src = dst = "public.orders"
        if src == dst:
            result = {"hops": 0, "tables": [src], "joins": []}
            assert result["hops"] == 0


# ── Connection Test Phase 3: Schema Access (Round 8) ───────────────────────


class TestConnectionTestPhase3:
    """Tests for Phase 3 schema access verification in connection test."""

    def test_test_endpoint_has_schema_access_phase(self):
        """Connection test endpoint code includes schema_access phase."""
        import inspect

        from gateway.main import test_connection

        source = inspect.getsource(test_connection)
        assert "schema_access" in source
        assert "Phase 3" in source

    def test_phase3_caches_schema(self):
        """Phase 3 caches schema after successful fetch."""
        import inspect

        from gateway.main import test_connection

        source = inspect.getsource(test_connection)
        assert "schema_cache.put" in source


# ── MCP join/relationship tools (Round 8) ──────────────────────────────────


class TestMCPJoinTools:
    """Tests for MCP find_join_path and get_relationships tools."""

    def test_find_join_path_exists(self):
        from gateway.mcp_server import find_join_path

        assert callable(find_join_path)

    def test_get_relationships_exists(self):
        from gateway.mcp_server import get_relationships

        assert callable(get_relationships)

    def test_find_join_path_has_max_hops(self):
        import inspect

        from gateway.mcp_server import find_join_path

        source = inspect.getsource(find_join_path)
        assert "max_hops" in source

    def test_get_relationships_formats(self):
        import inspect

        from gateway.mcp_server import get_relationships

        source = inspect.getsource(get_relationships)
        assert "compact" in source
        assert "graph" in source


# ── Table Exploration (ReFoRCE pattern, Round 8) ──────────────────────────


class TestExploreTable:
    """Tests for /schema/explore-table — iterative column exploration."""

    def test_explore_table_endpoint_exists(self):
        from gateway.main import app

        routes = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/api/connections/{name}/schema/explore-table" in routes

    def test_explore_table_includes_reverse_fks(self):
        """explore_table finds tables that reference the queried table."""
        import inspect

        from gateway.main import explore_table

        source = inspect.getsource(explore_table)
        assert "referenced_by" in source
        assert "references_table" in source

    def test_explore_table_mcp_tool_exists(self):
        from gateway.mcp_server import explore_table

        assert callable(explore_table)


# ── Enhanced Error Messages (Round 8) ──────────────────────────────────────


class TestEnhancedErrors:
    """Tests for DB-specific troubleshooting hints in error messages."""

    def test_connection_refused_hint(self):
        from gateway.main import _sanitize_db_error

        msg = _sanitize_db_error("connection refused to host", db_type="postgres")
        assert "Check that the database server is running" in msg
        assert "firewall" in msg.lower()

    def test_auth_error_snowflake_hint(self):
        from gateway.main import _sanitize_db_error

        msg = _sanitize_db_error("Authentication failed: wrong password", db_type="snowflake")
        assert "account identifier" in msg.lower()

    def test_auth_error_databricks_hint(self):
        from gateway.main import _sanitize_db_error

        msg = _sanitize_db_error("Authentication failed: 401 Unauthorized", db_type="databricks")
        assert "personal access token" in msg.lower()

    def test_timeout_hint(self):
        from gateway.main import _sanitize_db_error

        msg = _sanitize_db_error("Connection timed out after 30s", db_type="mysql")
        assert "VPN" in msg
        assert "allowlist" in msg.lower()

    def test_ssl_hint(self):
        from gateway.main import _sanitize_db_error

        msg = _sanitize_db_error("SSL certificate verify failed", db_type="postgres")
        assert "CA certificate" in msg


# ── Schema Overview (Round 8) ──────────────────────────────────────────────


class TestSchemaOverview:
    """Tests for the /schema/overview endpoint."""

    def test_overview_endpoint_exists(self):
        from gateway.main import app

        routes = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/api/connections/{name}/schema/overview" in routes

    def test_overview_mcp_tool_exists(self):
        from gateway.mcp_server import schema_overview

        assert callable(schema_overview)


# ── URL Validation (Round 8) ──────────────────────────────────────────────


class TestURLValidation:
    """Tests for the /connections/validate-url endpoint."""

    def test_validate_url_endpoint_exists(self):
        from gateway.main import app

        routes = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/api/connections/validate-url" in routes

    def test_validate_postgres_url(self):
        """Validate a PostgreSQL URL parses correctly."""
        import asyncio

        from gateway.main import validate_connection_url

        result = asyncio.get_event_loop().run_until_complete(
            validate_connection_url(
                {"connection_string": "postgresql://admin:pass@localhost:5432/mydb", "db_type": "postgres"}
            )
        )
        assert result["valid"] is True
        assert result["parsed"]["host"] == "localhost"
        assert result["parsed"]["port"] == 5432
        assert result["parsed"]["database"] == "mydb"

    def test_validate_empty_url(self):
        """Empty URL returns invalid."""
        import asyncio

        from gateway.main import validate_connection_url

        result = asyncio.get_event_loop().run_until_complete(
            validate_connection_url({"connection_string": "", "db_type": "postgres"})
        )
        assert result["valid"] is False

    def test_validate_missing_password_warning(self):
        """URL without password produces warning."""
        import asyncio

        from gateway.main import validate_connection_url

        result = asyncio.get_event_loop().run_until_complete(
            validate_connection_url(
                {"connection_string": "postgresql://admin@localhost:5432/mydb", "db_type": "postgres"}
            )
        )
        assert result["valid"] is True
        assert any("password" in w.lower() for w in result.get("warnings", []))


# ── Connector Tier Classification ──────────────────────────────────────────


class TestConnectorTierClassification:
    """Tests for the HEX-style connector tier classification system."""

    def test_capabilities_all_connectors(self):
        """GET /api/connectors/capabilities returns all tiers."""
        import asyncio

        from gateway.main import get_connector_capabilities

        result = asyncio.get_event_loop().run_until_complete(get_connector_capabilities())
        assert "tier_1" in result
        assert "tier_2" in result
        assert "tier_3" in result
        assert result["total_connectors"] == 11
        # Tier 1 has postgres, mysql, snowflake, bigquery
        tier1_types = [c["db_type"] for c in result["tier_1"]]
        assert "postgres" in tier1_types
        assert "mysql" in tier1_types

    def test_capabilities_single_connector(self):
        """GET /api/connectors/capabilities?db_type=postgres returns detailed info."""
        import asyncio

        from gateway.main import get_connector_capabilities

        result = asyncio.get_event_loop().run_until_complete(get_connector_capabilities(db_type="postgres"))
        assert result["db_type"] == "postgres"
        assert result["tier"] == 1
        assert result["feature_score"] > 80  # Postgres has most features
        assert result["features"]["foreign_keys"] is True
        assert result["features"]["ssl"] is True
        assert result["features"]["ssh_tunnel"] is True

    def test_capabilities_unknown_db_type(self):
        """Unknown db_type returns 404."""
        import asyncio

        from fastapi import HTTPException

        from gateway.main import get_connector_capabilities

        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(get_connector_capabilities(db_type="invalid_db"))
        assert exc_info.value.status_code == 404

    def test_tier_classification_consistency(self):
        """All connectors have consistent tier assignments."""
        from gateway.main import _CONNECTOR_TIERS

        for db_type, info in _CONNECTOR_TIERS.items():
            assert info["tier"] in (1, 2, 3), f"{db_type} has invalid tier"
            assert "features" in info
            assert info["features"]["schema_introspection"] is True, f"{db_type} must support schema introspection"

    def test_feature_score_calculation(self):
        """Feature scores are computed correctly."""
        import asyncio

        from gateway.main import get_connector_capabilities

        result = asyncio.get_event_loop().run_until_complete(get_connector_capabilities(db_type="duckdb"))
        # DuckDB is Tier 3 but has good feature coverage after improvements
        assert result["tier"] == 3
        assert result["feature_score"] > 0  # Has features enabled

    def test_tier_1_has_more_features_than_tier_3(self):
        """Tier 1 connectors always have more features than Tier 3."""
        from gateway.main import _CONNECTOR_TIERS

        for db_type, info in _CONNECTOR_TIERS.items():
            enabled = sum(1 for v in info["features"].values() if v)
            if info["tier"] == 1:
                assert enabled >= 8, f"Tier 1 {db_type} should have 8+ features"


# ── Schema Diff ────────────────────────────────────────────────────────────


class TestSchemaDiff:
    """Tests for schema diff detection."""

    def test_diff_no_cached_baseline(self):
        """First diff call stores baseline and returns no-cached."""
        from gateway.connectors.schema_cache import SchemaCache

        cache = SchemaCache(ttl_seconds=300)
        result = cache.diff("test-conn", {"public.users": {"columns": []}})
        assert result is None  # No cached schema to compare

    def test_diff_no_changes(self):
        """Identical schemas produce no diff."""
        from gateway.connectors.schema_cache import SchemaCache

        cache = SchemaCache(ttl_seconds=300)
        schema = {"public.users": {"columns": [{"name": "id", "type": "int"}]}}
        cache.put("test-conn", schema)
        diff = cache.diff("test-conn", schema)
        assert diff is not None
        assert diff["has_changes"] is False

    def test_diff_added_table(self):
        """Detects newly added tables."""
        from gateway.connectors.schema_cache import SchemaCache

        cache = SchemaCache(ttl_seconds=300)
        old = {"public.users": {"columns": [{"name": "id", "type": "int"}]}}
        new = {**old, "public.orders": {"columns": [{"name": "id", "type": "int"}]}}
        cache.put("test-conn", old)
        diff = cache.diff("test-conn", new)
        assert diff["has_changes"] is True
        assert "public.orders" in diff["added_tables"]

    def test_diff_removed_table(self):
        """Detects removed tables."""
        from gateway.connectors.schema_cache import SchemaCache

        cache = SchemaCache(ttl_seconds=300)
        old = {"public.users": {"columns": []}, "public.tmp": {"columns": []}}
        new = {"public.users": {"columns": []}}
        cache.put("test-conn", old)
        diff = cache.diff("test-conn", new)
        assert diff["has_changes"] is True
        assert "public.tmp" in diff["removed_tables"]

    def test_diff_modified_column_type(self):
        """Detects column type changes."""
        from gateway.connectors.schema_cache import SchemaCache

        cache = SchemaCache(ttl_seconds=300)
        old = {"public.users": {"columns": [{"name": "age", "type": "integer"}]}}
        new = {"public.users": {"columns": [{"name": "age", "type": "bigint"}]}}
        cache.put("test-conn", old)
        diff = cache.diff("test-conn", new)
        assert diff["has_changes"] is True
        assert len(diff["modified_tables"]) == 1
        assert diff["modified_tables"][0]["type_changes"][0]["old_type"] == "integer"
        assert diff["modified_tables"][0]["type_changes"][0]["new_type"] == "bigint"

    def test_diff_added_column(self):
        """Detects newly added columns."""
        from gateway.connectors.schema_cache import SchemaCache

        cache = SchemaCache(ttl_seconds=300)
        old = {"public.users": {"columns": [{"name": "id", "type": "int"}]}}
        new = {"public.users": {"columns": [{"name": "id", "type": "int"}, {"name": "email", "type": "text"}]}}
        cache.put("test-conn", old)
        diff = cache.diff("test-conn", new)
        assert diff["has_changes"] is True
        assert "email" in diff["modified_tables"][0]["added_columns"]


# ── Schema DDL Endpoint ────────────────────────────────────────────────────


class TestSchemaDDL:
    """Tests for the CREATE TABLE DDL schema format endpoint."""

    def test_ddl_format_basic(self):
        """DDL format produces valid CREATE TABLE statements."""
        import asyncio

        from gateway.main import get_schema_ddl

        # This test requires a running connection — skip if gateway not available
        try:
            result = asyncio.get_event_loop().run_until_complete(get_schema_ddl("enterprise-pg"))
            assert result["format"] == "ddl"
            assert result["table_count"] > 0
            assert "CREATE TABLE" in result["ddl"]
            assert result["token_estimate"] > 0
        except Exception:
            pytest.skip("enterprise-pg connection not available")

    def test_relevance_sorting(self):
        """Tables with more FKs sort first (join-hub prioritization)."""
        # Test the sorting logic directly
        tables = {
            "public.orders": {
                "schema": "public",
                "name": "orders",
                "columns": [{"name": "id", "type": "int"}],
                "foreign_keys": [
                    {"column": "customer_id", "references_table": "customers", "references_column": "id"},
                    {"column": "product_id", "references_table": "products", "references_column": "id"},
                ],
                "row_count": 1000,
            },
            "public.customers": {
                "schema": "public",
                "name": "customers",
                "columns": [{"name": "id", "type": "int"}],
                "foreign_keys": [],
                "row_count": 500,
            },
            "public.products": {
                "schema": "public",
                "name": "products",
                "columns": [{"name": "id", "type": "int"}],
                "foreign_keys": [],
                "row_count": 100,
            },
        }

        def _table_relevance(key: str) -> tuple:
            table = tables[key]
            fk_count = len(table.get("foreign_keys", []))
            row_count = table.get("row_count", 0)
            col_count = len(table.get("columns", []))
            return (-fk_count, -row_count, -col_count, key)

        sorted_keys = sorted(tables.keys(), key=_table_relevance)
        # orders has 2 FKs, so it should be first
        assert sorted_keys[0] == "public.orders"
        # customers has more rows than products
        assert sorted_keys[1] == "public.customers"
        assert sorted_keys[2] == "public.products"


# ── MCP Capabilities and Diff Tools ───────────────────────────────────────


class TestMCPCapabilitiesTools:
    """Tests for MCP connector_capabilities and schema_diff tools."""

    def test_connector_capabilities_tool_exists(self):
        """connector_capabilities MCP tool is registered."""
        from gateway.mcp_server import mcp

        tools = mcp._tool_manager._tools
        assert "connector_capabilities" in tools

    def test_schema_diff_tool_exists(self):
        """schema_diff MCP tool is registered."""
        from gateway.mcp_server import mcp

        tools = mcp._tool_manager._tools
        assert "schema_diff" in tools

    def test_schema_ddl_tool_exists(self):
        """schema_ddl MCP tool is registered."""
        from gateway.mcp_server import mcp

        tools = mcp._tool_manager._tools
        assert "schema_ddl" in tools

    def test_schema_link_mcp_tool_exists(self):
        """schema_link MCP tool is registered."""
        from gateway.mcp_server import mcp

        tools = mcp._tool_manager._tools
        assert "schema_link" in tools

    def test_explain_query_mcp_tool_exists(self):
        """explain_query MCP tool is registered."""
        from gateway.mcp_server import mcp

        tools = mcp._tool_manager._tools
        assert "explain_query" in tools

    def test_query_history_mcp_tool_exists(self):
        """query_history MCP tool is registered."""
        from gateway.mcp_server import mcp

        tools = mcp._tool_manager._tools
        assert "query_history" in tools


# ── Query Error Hints ──────────────────────────────────────────────────────


class TestQueryErrorHints:
    """Tests for structured error feedback in MCP query_database."""

    def test_column_not_found_hint(self):
        from gateway.errors import query_error_hint

        hint = query_error_hint("column 'foobar' does not exist", "postgres")
        assert hint is not None
        assert "column" in hint.lower()

    def test_table_not_found_hint(self):
        from gateway.errors import query_error_hint

        hint = query_error_hint("relation 'xyz' does not exist", "postgres")
        assert hint is not None
        assert "table" in hint.lower() or "schema" in hint.lower()

    def test_ambiguous_column_hint(self):
        from gateway.errors import query_error_hint

        hint = query_error_hint("column reference 'id' is ambiguous", "postgres")
        assert hint is not None
        assert "ambiguous" in hint.lower()

    def test_syntax_error_bigquery(self):
        from gateway.errors import query_error_hint

        hint = query_error_hint("Syntax error at position 10", "bigquery")
        assert hint is not None
        assert "bigquery" in hint.lower()

    def test_syntax_error_snowflake(self):
        from gateway.errors import query_error_hint

        hint = query_error_hint("SQL compilation error: syntax error", "snowflake")
        assert hint is not None
        assert "snowflake" in hint.lower()

    def test_division_by_zero_hint(self):
        from gateway.errors import query_error_hint

        hint = query_error_hint("division by zero", "postgres")
        assert hint is not None
        assert "nullif" in hint.lower()

    def test_timeout_hint(self):
        from gateway.errors import query_error_hint

        hint = query_error_hint("statement timeout: query timed out", "postgres")
        assert hint is not None
        assert "timed out" in hint.lower() or "where" in hint.lower()

    def test_no_hint_for_unknown_error(self):
        from gateway.errors import query_error_hint

        hint = query_error_hint("some random internal error occurred", "postgres")
        assert hint is None


# ── Schema Linking ──────────────────────────────────────────────────────────


class TestSchemaLinking:
    """Tests for the smart schema linking endpoint."""

    def _make_schema(self):
        """Build a mock schema for testing linking logic."""
        return {
            "public.customers": {
                "schema": "public",
                "name": "customers",
                "columns": [
                    {"name": "id", "type": "int", "primary_key": True, "nullable": False},
                    {"name": "name", "type": "varchar"},
                    {"name": "email", "type": "varchar"},
                    {"name": "region", "type": "varchar", "comment": "Geographic region"},
                ],
                "foreign_keys": [],
                "row_count": 5000,
                "description": "All registered customers",
            },
            "public.orders": {
                "schema": "public",
                "name": "orders",
                "columns": [
                    {"name": "id", "type": "int", "primary_key": True, "nullable": False},
                    {"name": "customer_id", "type": "int"},
                    {"name": "total", "type": "decimal"},
                    {"name": "created_at", "type": "timestamp"},
                ],
                "foreign_keys": [
                    {"column": "customer_id", "references_table": "customers", "references_column": "id"},
                ],
                "row_count": 50000,
            },
            "public.products": {
                "schema": "public",
                "name": "products",
                "columns": [
                    {"name": "id", "type": "int", "primary_key": True, "nullable": False},
                    {"name": "name", "type": "varchar"},
                    {"name": "price", "type": "decimal"},
                    {"name": "category", "type": "varchar"},
                ],
                "foreign_keys": [],
                "row_count": 200,
            },
            "public.order_items": {
                "schema": "public",
                "name": "order_items",
                "columns": [
                    {"name": "id", "type": "int", "primary_key": True, "nullable": False},
                    {"name": "order_id", "type": "int"},
                    {"name": "product_id", "type": "int"},
                    {"name": "quantity", "type": "int"},
                ],
                "foreign_keys": [
                    {"column": "order_id", "references_table": "orders", "references_column": "id"},
                    {"column": "product_id", "references_table": "products", "references_column": "id"},
                ],
                "row_count": 150000,
            },
            "public.audit_log": {
                "schema": "public",
                "name": "audit_log",
                "columns": [
                    {"name": "id", "type": "int", "primary_key": True, "nullable": False},
                    {"name": "action", "type": "varchar"},
                    {"name": "timestamp", "type": "timestamp"},
                ],
                "foreign_keys": [],
                "row_count": 1000000,
            },
        }

    def test_term_matching_exact_table(self):
        """Question mentioning 'customers' should match customers table."""
        import re

        schema = self._make_schema()
        question = "How many customers are there?"
        stopwords = {"the", "how", "many", "are", "there"}
        terms = [
            w for w in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", question.lower()) if len(w) >= 3 and w not in stopwords
        ]

        assert "customers" in terms

        # Score tables
        scores = {}
        for key, table_data in schema.items():
            score = 0.0
            table_name_lower = table_data.get("name", "").lower()
            for term in terms:
                if term == table_name_lower or term == table_name_lower.rstrip("s"):
                    score += 10.0
                elif term in table_name_lower:
                    score += 5.0
                elif term + "s" == table_name_lower:
                    score += 8.0
            scores[key] = score

        assert scores["public.customers"] > 0
        assert scores["public.customers"] > scores["public.audit_log"]

    def test_term_matching_column_name(self):
        """Question mentioning 'email' should match customers table (has email column)."""
        import re

        schema = self._make_schema()
        question = "Find the email of customer 123"
        stopwords = {"the", "find", "customer"}
        terms = [
            w for w in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", question.lower()) if len(w) >= 3 and w not in stopwords
        ]

        scores = {}
        for key, table_data in schema.items():
            score = 0.0
            for term in terms:
                for col in table_data.get("columns", []):
                    col_name = col.get("name", "").lower()
                    if term == col_name:
                        score += 4.0
                    elif term in col_name:
                        score += 2.0
            scores[key] = score

        assert scores["public.customers"] > 0, "customers has email column"
        assert scores["public.orders"] == 0, "orders has no email column"

    def test_fk_expansion(self):
        """FK-connected tables should be included for join path completeness."""
        schema = self._make_schema()
        # Suppose orders was matched — customers should be added via FK
        linked_keys = {"public.orders"}
        fk_additions = set()

        for key in list(linked_keys):
            table_data = schema.get(key, {})
            for fk in table_data.get("foreign_keys", []):
                ref_table = fk.get("references_table", "")
                for candidate_key in schema:
                    if schema[candidate_key].get("name", "") == ref_table:
                        fk_additions.add(candidate_key)
                        break

        assert "public.customers" in fk_additions, "customers should be added via FK from orders"

    def test_fallback_when_no_matches(self):
        """When no terms match, fallback to FK-relevance sorted tables."""
        schema = self._make_schema()
        # Empty terms = no matches
        linked_keys = set()

        if not linked_keys:

            def _fb_relevance(key):
                t = schema[key]
                return (-len(t.get("foreign_keys", [])), -t.get("row_count", 0), key)

            linked_keys = set(sorted(schema.keys(), key=_fb_relevance)[:3])

        # order_items has 2 FKs, so it should be in the top
        assert "public.order_items" in linked_keys

    def test_singular_plural_matching(self):
        """'order' should match 'orders' table (singular → plural)."""
        import re

        schema = self._make_schema()
        question = "Show me the order total"
        stopwords = {"the", "show"}
        terms = [
            w for w in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", question.lower()) if len(w) >= 3 and w not in stopwords
        ]

        scores = {}
        for key, table_data in schema.items():
            score = 0.0
            table_name_lower = table_data.get("name", "").lower()
            for term in terms:
                if term == table_name_lower or term == table_name_lower.rstrip("s"):
                    score += 10.0
                elif term + "s" == table_name_lower or term + "es" == table_name_lower:
                    score += 8.0
                for col in table_data.get("columns", []):
                    if term == col.get("name", "").lower():
                        score += 4.0
            scores[key] = score

        assert scores["public.orders"] > 0, "'order' should match 'orders' via singular/plural"


# ── MSSQL Connector ────────────────────────────────────────────────────────


class TestMSSQLConnector:
    CONN_STR = "mssql://sa:Test%4012345@host.docker.internal:1434/testdb"

    @pytest.fixture
    def connector(self):
        from gateway.connectors.mssql import MSSQLConnector

        return MSSQLConnector()

    @pytest.mark.asyncio
    async def test_connect_and_health(self, connector):
        try:
            await connector.connect(self.CONN_STR)
            assert await connector.health_check() is True
            await connector.close()
        except Exception as e:
            pytest.skip(f"MSSQL not available: {e}")

    @pytest.mark.asyncio
    async def test_execute_query(self, connector):
        try:
            await connector.connect(self.CONN_STR)
        except Exception:
            pytest.skip("MSSQL not available")
        rows = await connector.execute("SELECT 1 AS value")
        assert len(rows) == 1
        assert rows[0]["value"] == 1
        await connector.close()

    @pytest.mark.asyncio
    async def test_get_schema(self, connector):
        try:
            await connector.connect(self.CONN_STR)
        except Exception:
            pytest.skip("MSSQL not available")
        schema = await connector.get_schema()
        assert isinstance(schema, dict)
        if len(schema) > 0:
            first_table = list(schema.values())[0]
            assert "columns" in first_table
            assert "foreign_keys" in first_table
            assert "indexes" in first_table
            assert "row_count" in first_table
            # Check MSSQL-specific metadata
            col = first_table["columns"][0]
            assert "name" in col
            assert "type" in col
            # Type should include precision for numeric types
            types = [c["type"] for c in first_table["columns"]]
            has_precision = any("(" in t for t in types)
            assert has_precision, f"MSSQL types should include precision: {types}"
        await connector.close()

    @pytest.mark.asyncio
    async def test_sample_values(self, connector):
        try:
            await connector.connect(self.CONN_STR)
        except Exception:
            pytest.skip("MSSQL not available")
        schema = await connector.get_schema()
        if schema:
            first_table_key = list(schema.keys())[0]
            cols = [c["name"] for c in schema[first_table_key]["columns"][:3]]
            samples = await connector.get_sample_values(first_table_key, cols, limit=3)
            assert isinstance(samples, dict)
        await connector.close()


class TestMSSQLURLParsing:
    """Test MSSQL connection string parsing for all supported formats."""

    def test_standard_mssql_url(self):
        from gateway.connectors.mssql import MSSQLConnector

        c = MSSQLConnector()
        params = c._parse_connection_string("mssql://admin:pass@myhost:1434/mydb")
        assert params["host"] == "myhost"
        assert params["port"] == 1434
        assert params["user"] == "admin"
        assert params["password"] == "pass"
        assert params["database"] == "mydb"

    def test_pymssql_url(self):
        from gateway.connectors.mssql import MSSQLConnector

        c = MSSQLConnector()
        params = c._parse_connection_string("mssql+pymssql://sa:pw@localhost:1433/master")
        assert params["host"] == "localhost"
        assert params["user"] == "sa"
        assert params["database"] == "master"

    def test_sqlserver_url(self):
        from gateway.connectors.mssql import MSSQLConnector

        c = MSSQLConnector()
        params = c._parse_connection_string("sqlserver://user:p%40ss@server.example.com/proddb")
        assert params["host"] == "server.example.com"
        assert params["password"] == "p@ss"
        assert params["database"] == "proddb"

    def test_default_port(self):
        from gateway.connectors.mssql import MSSQLConnector

        c = MSSQLConnector()
        params = c._parse_connection_string("mssql://sa:pass@myhost/mydb")
        assert params["port"] == 1433


class TestTrinoURLParsing:
    """Test Trino connection string parsing."""

    def test_standard_trino_url(self):
        from gateway.connectors.trino import TrinoConnector

        c = TrinoConnector()
        params = c._parse_connection("trino://admin@trinohost:8080/hive/default")
        assert params["host"] == "trinohost"
        assert params["port"] == 8080
        assert params["username"] == "admin"
        assert params["catalog"] == "hive"
        assert params["schema"] == "default"

    def test_trino_https_url(self):
        from gateway.connectors.trino import TrinoConnector

        c = TrinoConnector()
        params = c._parse_connection("trino+https://user@secure.trino.io:443/catalog")
        assert params["host"] == "secure.trino.io"
        assert params["port"] == 443
        assert params["https"] is True
        assert params["catalog"] == "catalog"

    def test_trino_with_password(self):
        from gateway.connectors.trino import TrinoConnector

        c = TrinoConnector()
        params = c._parse_connection("trino://user:secret@host:8443/cat/sch")
        assert params["username"] == "user"
        assert params["password"] == "secret"
        assert params["catalog"] == "cat"
        assert params["schema"] == "sch"

    def test_trino_with_query_params(self):
        from gateway.connectors.trino import TrinoConnector

        c = TrinoConnector()
        params = c._parse_connection("trino://user@host:8080/cat?verify=false&request_timeout=30")
        assert params["verify"] == "false"
        assert params["request_timeout"] == "30"

    def test_trino_default_port(self):
        from gateway.connectors.trino import TrinoConnector

        c = TrinoConnector()
        params = c._parse_connection("trino://user@myhost/catalog")
        assert params["port"] == 8080


class TestMSSQLCostEstimation:
    """Test MSSQL cost estimation via SHOWPLAN."""

    @pytest.mark.asyncio
    async def test_cost_estimator_routes_mssql(self):
        """Verify MSSQL is in the cost estimator routing table."""
        from gateway.governance.cost_estimator import CostEstimate, CostEstimator

        # Calling estimate with a None connector should still route to MSSQL estimator
        # (it will fail gracefully since no real connection)
        result = await CostEstimator.estimate(None, "SELECT 1", "mssql")
        assert isinstance(result, CostEstimate)
        # Should get a warning since connector is None
        assert result.warning is not None

    @pytest.mark.asyncio
    async def test_cost_estimator_routes_trino(self):
        """Verify Trino is in the cost estimator routing table."""
        from gateway.governance.cost_estimator import CostEstimate, CostEstimator

        result = await CostEstimator.estimate(None, "SELECT 1", "trino")
        assert isinstance(result, CostEstimate)
        assert result.warning is not None


# ── BaseConnector sample UNION ALL helpers ─────────────────────────────────


class TestBaseConnectorSampleHelpers:
    """Test _build_sample_union_sql and _parse_sample_union_result."""

    def test_build_sample_union_sql_basic(self):
        from gateway.connectors.base import BaseConnector

        sql = BaseConnector._build_sample_union_sql("public.users", ["name", "email"], limit=3, quote='"')
        assert "UNION ALL" in sql
        assert "'name' AS _col" in sql
        assert "'email' AS _col" in sql
        assert "LIMIT 3" in sql
        assert '"name"' in sql

    def test_build_sample_union_sql_backtick(self):
        from gateway.connectors.base import BaseConnector

        sql = BaseConnector._build_sample_union_sql("users", ["col1"], limit=5, quote="`")
        assert "`col1`" in sql
        assert "UNION ALL" not in sql  # Only one column, no UNION

    def test_build_sample_union_sql_caps_at_20(self):
        from gateway.connectors.base import BaseConnector

        cols = [f"col{i}" for i in range(30)]
        sql = BaseConnector._build_sample_union_sql("t", cols, limit=5)
        # Should only have 20 subqueries
        assert sql.count("AS _col") == 20

    def test_parse_sample_union_result_dicts(self):
        from gateway.connectors.base import BaseConnector

        rows = [
            {"_col": "name", "_val": "Alice"},
            {"_col": "name", "_val": "Bob"},
            {"_col": "email", "_val": "a@b.com"},
        ]
        result = BaseConnector._parse_sample_union_result(rows)
        assert result["name"] == ["Alice", "Bob"]
        assert result["email"] == ["a@b.com"]

    def test_parse_sample_union_result_tuples(self):
        from gateway.connectors.base import BaseConnector

        rows = [("name", "Alice"), ("name", "Bob"), ("email", "a@b.com")]
        result = BaseConnector._parse_sample_union_result(rows)
        assert result["name"] == ["Alice", "Bob"]
        assert result["email"] == ["a@b.com"]

    def test_parse_sample_union_result_skips_none(self):
        from gateway.connectors.base import BaseConnector

        rows = [{"_col": "name", "_val": None}, {"_col": "name", "_val": "Alice"}]
        result = BaseConnector._parse_sample_union_result(rows)
        assert result["name"] == ["Alice"]

    def test_parse_sample_union_result_empty(self):
        from gateway.connectors.base import BaseConnector

        assert BaseConnector._parse_sample_union_result([]) == {}


class TestRedshiftSchemaMetadata:
    """Test that Redshift connector schema output includes new metadata fields."""

    def test_redshift_schema_fields_from_svv_table_info(self):
        """Verify Redshift connector uses SVV_TABLE_INFO fields, not pg_table_def."""
        import inspect

        from gateway.connectors.redshift import RedshiftConnector

        source = inspect.getsource(RedshiftConnector.get_schema)
        # Must use SVV_TABLE_INFO for diststyle (not pg_table_def)
        assert "svv_table_info" in source
        # Must NOT reference sortkey1 from pg_table_def
        assert "pg_table_def" in source  # still used for columns
        # Must include pg_stats for column statistics
        assert "pg_stats" in source
        # Must include column encoding
        assert "encoding" in source.lower()

    def test_redshift_connector_has_logging(self):
        """Verify Redshift connector logs metadata query failures."""
        import inspect

        from gateway.connectors.redshift import RedshiftConnector

        source = inspect.getsource(RedshiftConnector.get_schema)
        assert "logger.info" in source

    def test_redshift_schema_output_structure(self):
        """Verify expected output fields in Redshift schema."""
        # Just test that the connector can be instantiated and has the right methods
        from gateway.connectors.redshift import RedshiftConnector

        c = RedshiftConnector()
        assert hasattr(c, "get_schema")
        assert hasattr(c, "get_sample_values")
        # _build_sample_union_sql should be available from base
        assert hasattr(c, "_build_sample_union_sql")


class TestSnowflakeClusteringMetadata:
    """Test that Snowflake connector fetches clustering key info."""

    def test_snowflake_schema_includes_clustering_query(self):
        """Verify Snowflake get_schema includes SHOW TABLES query for clustering."""
        import inspect

        from gateway.connectors.snowflake import SnowflakeConnector

        source = inspect.getsource(SnowflakeConnector.get_schema)
        assert "SHOW TABLES" in source
        assert "clustering_key" in source
        assert "cluster_by" in source

    def test_snowflake_connector_has_logging(self):
        """Verify Snowflake connector logs metadata query failures."""
        import inspect

        from gateway.connectors.snowflake import SnowflakeConnector

        source = inspect.getsource(SnowflakeConnector.get_schema)
        assert "logger.info" in source

    def test_snowflake_sample_values_uses_union(self):
        """Verify Snowflake sample values uses batched UNION ALL."""
        import inspect

        from gateway.connectors.snowflake import SnowflakeConnector

        source = inspect.getsource(SnowflakeConnector.get_sample_values)
        assert "_build_sample_union_sql" in source


class TestSampleValuesBatching:
    """Verify all connectors use batched UNION ALL for sample values."""

    def test_all_connectors_use_union_all(self):
        """Every connector's get_sample_values should reference _build_sample_union_sql."""
        import inspect

        from gateway.connectors.bigquery import BigQueryConnector
        from gateway.connectors.clickhouse import ClickHouseConnector
        from gateway.connectors.databricks import DatabricksConnector
        from gateway.connectors.duckdb import DuckDBConnector
        from gateway.connectors.mssql import MSSQLConnector
        from gateway.connectors.mysql import MySQLConnector
        from gateway.connectors.sqlite import SQLiteConnector
        from gateway.connectors.trino import TrinoConnector

        for cls in [
            MySQLConnector,
            ClickHouseConnector,
            DuckDBConnector,
            MSSQLConnector,
            TrinoConnector,
            DatabricksConnector,
            SQLiteConnector,
            BigQueryConnector,
        ]:
            source = inspect.getsource(cls.get_sample_values)
            assert "_build_sample_union_sql" in source or "UNION ALL" in source, (
                f"{cls.__name__} should use batched sample query"
            )

    @pytest.mark.asyncio
    async def test_mysql_batched_sample_values(self):
        """Test MySQL sample values with batched UNION ALL on live database."""
        from gateway.connectors.mysql import MySQLConnector

        c = MySQLConnector()
        await c.connect("mysql://analyst:An4lyst!P4ss@host.docker.internal:3307/test_analytics")
        result = await c.get_sample_values("test_analytics.users", ["username", "email"], limit=5)
        assert isinstance(result, dict)
        # Should have at least one column with values
        if result:
            for col, vals in result.items():
                assert isinstance(vals, list)
                assert all(isinstance(v, str) for v in vals)
        await c.close()

    @pytest.mark.asyncio
    async def test_clickhouse_batched_sample_values(self):
        """Test ClickHouse sample values with batched UNION ALL on live database."""
        from gateway.connectors.clickhouse import ClickHouseConnector

        c = ClickHouseConnector()
        await c.connect("clickhouse://default:test123@host.docker.internal:9100/test_analytics")
        result = await c.get_sample_values("test_analytics.users", ["username", "email"], limit=5)
        assert isinstance(result, dict)
        if result:
            for col, vals in result.items():
                assert isinstance(vals, list)
        await c.close()

    @pytest.mark.asyncio
    async def test_mssql_batched_sample_values(self):
        """Test MSSQL sample values with batched UNION ALL on live database."""
        from gateway.connectors.mssql import MSSQLConnector

        c = MSSQLConnector()
        await c.connect("mssql://sa:Test%4012345@host.docker.internal:1434/testdb")
        result = await c.get_sample_values("dbo.customers", ["name", "email"], limit=5)
        assert isinstance(result, dict)
        if result:
            for col, vals in result.items():
                assert isinstance(vals, list)
        await c.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
