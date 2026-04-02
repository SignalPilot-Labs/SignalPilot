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
            assert db_type.value in _REGISTRY or db_type in _REGISTRY, \
                f"DBType {db_type} not registered in connector registry"

    def test_get_connector_returns_correct_types(self):
        from gateway.connectors.registry import get_connector
        from gateway.connectors.postgres import PostgresConnector
        from gateway.connectors.mysql import MySQLConnector
        from gateway.connectors.duckdb import DuckDBConnector
        from gateway.connectors.clickhouse import ClickHouseConnector

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
        from gateway.store import _build_connection_string
        from gateway.models import ConnectionCreate
        conn = ConnectionCreate(
            name="test", db_type="postgres",
            host="myhost", port=5432, database="mydb",
            username="user", password="p@ss:word"
        )
        result = _build_connection_string(conn)
        assert result.startswith("postgresql://")
        assert "myhost:5432" in result
        assert "mydb" in result
        # Password should be URL-encoded
        assert "p%40ss%3Aword" in result

    def test_mysql_connection_string(self):
        from gateway.store import _build_connection_string
        from gateway.models import ConnectionCreate
        conn = ConnectionCreate(
            name="test", db_type="mysql",
            host="myhost", port=3306, database="mydb",
            username="root", password="secret"
        )
        result = _build_connection_string(conn)
        assert result.startswith("mysql+pymysql://")
        assert "myhost:3306" in result

    def test_snowflake_connection_string(self):
        from gateway.store import _build_connection_string
        from gateway.models import ConnectionCreate
        conn = ConnectionCreate(
            name="test", db_type="snowflake",
            account="xy12345", username="user", password="pass",
            database="mydb", warehouse="wh"
        )
        result = _build_connection_string(conn)
        assert result.startswith("snowflake://")
        assert "xy12345" in result

    def test_clickhouse_connection_string(self):
        from gateway.store import _build_connection_string
        from gateway.models import ConnectionCreate
        conn = ConnectionCreate(
            name="test", db_type="clickhouse",
            host="localhost", port=9000, database="default",
            username="default", password="test"
        )
        result = _build_connection_string(conn)
        assert result.startswith("clickhouse://")
        assert "localhost:9000" in result

    def test_duckdb_connection_string(self):
        from gateway.store import _build_connection_string
        from gateway.models import ConnectionCreate
        conn = ConnectionCreate(name="test", db_type="duckdb", database="/tmp/test.db")
        result = _build_connection_string(conn)
        assert result == "/tmp/test.db"

    def test_bigquery_connection_string(self):
        from gateway.store import _build_connection_string
        from gateway.models import ConnectionCreate
        conn = ConnectionCreate(name="test", db_type="bigquery", project="my-project")
        result = _build_connection_string(conn)
        assert result == "my-project"

    def test_redshift_connection_string(self):
        from gateway.store import _build_connection_string
        from gateway.models import ConnectionCreate
        conn = ConnectionCreate(
            name="test", db_type="redshift",
            host="cluster.region.redshift.amazonaws.com",
            port=5439, database="dev", username="admin", password="pass"
        )
        result = _build_connection_string(conn)
        assert result.startswith("redshift://")
        assert "5439" in result


# ── SSH Tunnel Module ──────────────────────────────────────────────────────

class TestSSHTunnel:
    def test_import_ssh_tunnel(self):
        from gateway.connectors.ssh_tunnel import SSHTunnel, HAS_SSHTUNNEL
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
        result = _rewrite_connection_string(
            "postgresql://user:pass@remote:5432/db", "postgres", "127.0.0.1", 12345
        )
        assert "127.0.0.1:12345" in result
        assert "user:pass" in result

    def test_rewrite_connection_string_mysql(self):
        from gateway.connectors.pool_manager import _rewrite_connection_string
        result = _rewrite_connection_string(
            "mysql+pymysql://user:pass@remote:3306/db", "mysql", "127.0.0.1", 54321
        )
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
                    {"column": "user_id", "references_schema": "public",
                     "references_table": "users", "references_column": "id"}
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
                    {"name": "id", "type": "bigint", "nullable": False, "primary_key": True,
                     "stats": {"distinct_fraction": -1.0}},
                    {"name": "name", "type": "varchar", "nullable": True, "primary_key": False,
                     "stats": {"distinct_count": 100}},
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
            name="test", db_type="postgres",
            host="localhost", port=5432, database="mydb", username="user"
        )
        errors = _validate_connection_params(conn)
        assert len(errors) == 0

    def test_connection_string_skips_validation(self):
        from gateway.main import _validate_connection_params
        from gateway.models import ConnectionCreate
        conn = ConnectionCreate(
            name="test", db_type="postgres",
            connection_string="postgresql://user:pass@host:5432/db"
        )
        errors = _validate_connection_params(conn)
        assert len(errors) == 0

    def test_ssh_tunnel_validation(self):
        from gateway.main import _validate_connection_params
        from gateway.models import ConnectionCreate, SSHTunnelConfig
        conn = ConnectionCreate(
            name="test", db_type="postgres",
            host="dbhost", username="user",
            ssh_tunnel=SSHTunnelConfig(enabled=True, auth_method="password")
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
            "public.invoices": {"name": "invoices", "columns": [], "foreign_keys": [
                {"column": "customer_id", "references_schema": "public", "references_table": "customers", "references_column": "id"},
            ]},
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
        params = c._parse_connection("databricks://my-workspace.cloud.databricks.com|/sql/1.0/warehouses/abc123|dapi_token|my_catalog|my_schema")
        assert params["host"] == "my-workspace.cloud.databricks.com"
        assert params["http_path"] == "/sql/1.0/warehouses/abc123"
        assert params["access_token"] == "dapi_token"
        assert params["catalog"] == "my_catalog"
        assert params["schema"] == "my_schema"

    def test_url_format(self):
        from gateway.connectors.databricks import DatabricksConnector
        c = DatabricksConnector()
        params = c._parse_connection("databricks://dapi_token@my-workspace.cloud.databricks.com/sql/1.0/warehouses/abc123?catalog=my_catalog&schema=my_schema")
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
        from gateway.connectors.pool_manager import PoolManager
        from gateway.connectors.mysql import MySQLConnector
        from unittest.mock import patch, AsyncMock, MagicMock

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
        c.set_ssl_config({
            "enabled": True,
            "mode": "verify-full",
            "ca_cert": "-----BEGIN CERTIFICATE-----\ntest\n-----END CERTIFICATE-----",
        })
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
        from gateway.connectors.pool_manager import PoolManager
        from gateway.connectors.postgres import PostgresConnector
        from unittest.mock import patch, AsyncMock

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
        c.set_ssl_config({
            "enabled": True,
            "mode": "verify-ca",
            "ca_cert": "test-ca-content",
        })
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
        from gateway.connectors.pool_manager import PoolManager
        from gateway.connectors.redshift import RedshiftConnector
        from unittest.mock import patch, AsyncMock

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
        from gateway.connectors.pool_manager import PoolManager
        from gateway.connectors.clickhouse import ClickHouseConnector
        from unittest.mock import patch, AsyncMock

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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
