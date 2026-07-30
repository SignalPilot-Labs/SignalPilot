"""End-to-end tests for the Microsoft SQL Server connector against a live server.

Spin up the server with:

    docker run -d --name sp-mssql-test \
        -e ACCEPT_EULA=Y -e MSSQL_SA_PASSWORD='Str0ng!Passw0rd' -e MSSQL_PID=Developer \
        -p 1434:1433 mcr.microsoft.com/mssql/server:2022-latest

then seed it with tests/fixtures/seed_mssql.py. Every test skips when the
server is unreachable, so the suite stays green without Docker.

Covers the full request path: connection-string parsing, connect, health check,
governed validation + LIMIT injection (TOP rewriting for T-SQL), execution,
schema introspection, sample values, identifier quoting, and reconnect.
"""

from __future__ import annotations

import os

import pytest

MSSQL_HOST = os.environ.get("SP_TEST_MSSQL_HOST", "127.0.0.1")
MSSQL_PORT = os.environ.get("SP_TEST_MSSQL_PORT", "1434")
MSSQL_URL = f"mssql://sa:Str0ng%21Passw0rd@{MSSQL_HOST}:{MSSQL_PORT}/sp_test"
READER_URL = f"mssql://sp_reader:R3ader%21Pass@{MSSQL_HOST}:{MSSQL_PORT}/sp_test"

CUSTOMERS = "analytics.customers"
ORDERS = "analytics.orders"


def _server_available() -> bool:
    try:
        import pymssql
    except ImportError:
        return False
    try:
        conn = pymssql.connect(
            server=MSSQL_HOST,
            port=MSSQL_PORT,
            user="sa",
            password="Str0ng!Passw0rd",
            database="sp_test",
            login_timeout=3,
        )
        conn.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _server_available(), reason="SQL Server test container not reachable")


@pytest.fixture
async def connector():
    from gateway.connectors.drivers.mssql import MSSQLConnector

    c = MSSQLConnector()
    await c.connect(MSSQL_URL)
    yield c
    await c.close()


# ── Connection string parsing (no server needed, but grouped here) ──────────


class TestConnectionStringParsing:
    def _parse(self, url: str) -> dict:
        from gateway.connectors.drivers.mssql import MSSQLConnector

        return MSSQLConnector()._parse_connection_string(url)

    @pytest.mark.parametrize("prefix", ["mssql://", "mssql+pymssql://", "sqlserver://"])
    def test_all_url_schemes_accepted(self, prefix):
        p = self._parse(f"{prefix}usr:pwd@dbhost:1433/mydb")
        assert p["host"] == "dbhost"
        assert p["port"] == 1433
        assert p["user"] == "usr"
        assert p["password"] == "pwd"
        assert p["database"] == "mydb"

    def test_percent_encoded_password_is_decoded(self):
        # A password containing '!' and '@' must survive URL decoding intact.
        p = self._parse("mssql://sa:P%40ss%21word@host:1433/db")
        assert p["password"] == "P@ss!word"

    def test_defaults_when_omitted(self):
        p = self._parse("mssql://host")
        assert p["port"] == 1433
        assert p["database"] == "master"

    def test_named_instance_query_param(self):
        p = self._parse("mssql://sa:pw@host:1433/db?instance=SQLEXPRESS")
        assert p["host"] == "host\\SQLEXPRESS"

    def test_encrypt_query_param(self):
        assert self._parse("mssql://sa:pw@h:1433/db?encrypt=true").get("encrypt") is True
        assert self._parse("mssql://sa:pw@h:1433/db").get("encrypt") is not True


# ── Connect / health ────────────────────────────────────────────────────────


class TestConnectAndHealth:
    @pytest.mark.asyncio
    async def test_connect_and_health_check(self, connector):
        assert await connector.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_false_before_connect(self):
        from gateway.connectors.drivers.mssql import MSSQLConnector

        assert await MSSQLConnector().health_check() is False

    @pytest.mark.asyncio
    async def test_bad_password_raises_auth_error(self):
        from gateway.connectors.drivers.mssql import MSSQLConnector

        c = MSSQLConnector()
        with pytest.raises(RuntimeError, match="Authentication failed"):
            await c.connect(f"mssql://sa:wrong-password@{MSSQL_HOST}:{MSSQL_PORT}/sp_test")

    @pytest.mark.asyncio
    async def test_missing_database_raises_clear_error(self):
        from gateway.connectors.drivers.mssql import MSSQLConnector

        c = MSSQLConnector()
        with pytest.raises(RuntimeError, match="Database not found|SQL Server connection error"):
            await c.connect(f"mssql://sa:Str0ng%21Passw0rd@{MSSQL_HOST}:{MSSQL_PORT}/no_such_db")

    @pytest.mark.asyncio
    async def test_reconnect_after_dropped_connection(self, connector):
        # Simulate a server-side drop; _ensure_connected must transparently recover.
        connector._conn.close()
        rows = await connector.execute("SELECT 1 AS ok")
        assert rows[0]["ok"] == 1


# ── Query execution ─────────────────────────────────────────────────────────


class TestExecute:
    @pytest.mark.asyncio
    async def test_scalar_select(self, connector):
        rows = await connector.execute("SELECT 1 AS value")
        assert rows == [{"value": 1}]

    @pytest.mark.asyncio
    async def test_rows_returned_as_dicts(self, connector):
        rows = await connector.execute(f"SELECT name, region FROM {CUSTOMERS} ORDER BY customer_id")
        assert len(rows) == 5
        assert all(isinstance(r, dict) for r in rows)
        assert rows[0]["name"] == "Acme Corp"
        assert rows[0]["region"] == "NORTH"

    @pytest.mark.asyncio
    async def test_parameterized_query_uses_placeholders(self, connector):
        rows = await connector.execute(
            f"SELECT name FROM {CUSTOMERS} WHERE region = %s ORDER BY name", params=["NORTH"]
        )
        assert [r["name"] for r in rows] == ["Acme Corp", "Initech"]

    @pytest.mark.asyncio
    async def test_parameterized_query_blocks_injection(self, connector):
        # The injection payload must be treated as a literal, matching zero rows.
        rows = await connector.execute(f"SELECT name FROM {CUSTOMERS} WHERE region = %s", params=["NORTH' OR '1'='1"])
        assert rows == []

    @pytest.mark.asyncio
    async def test_join_and_aggregate(self, connector):
        rows = await connector.execute(
            f"SELECT c.name, SUM(o.amount) AS total FROM {CUSTOMERS} c "
            f"JOIN {ORDERS} o ON o.customer_id = c.customer_id "
            "GROUP BY c.name ORDER BY total DESC"
        )
        assert rows[0]["name"] == "Stark Ind"
        assert float(rows[0]["total"]) == 15000.00

    @pytest.mark.asyncio
    async def test_tsql_specific_syntax(self, connector):
        rows = await connector.execute(
            f"SELECT TOP 2 name, DATEDIFF(day, '2024-01-01', created_at) AS age_days "
            f"FROM {CUSTOMERS} ORDER BY customer_id"
        )
        assert len(rows) == 2
        assert rows[0]["age_days"] == 14

    @pytest.mark.asyncio
    async def test_empty_resultset(self, connector):
        rows = await connector.execute(f"SELECT name FROM {CUSTOMERS} WHERE 1 = 0")
        assert rows == []

    @pytest.mark.asyncio
    async def test_null_values_preserved(self, connector):
        rows = await connector.execute("SELECT CAST(NULL AS INT) AS empty")
        assert rows[0]["empty"] is None

    @pytest.mark.asyncio
    async def test_query_error_is_wrapped(self, connector):
        with pytest.raises(RuntimeError, match="SQL Server query error"):
            await connector.execute("SELECT * FROM analytics.does_not_exist")

    @pytest.mark.asyncio
    async def test_unicode_roundtrip(self, connector):
        rows = await connector.execute("SELECT N'こんにちは — café' AS text")
        assert rows[0]["text"] == "こんにちは — café"


# ── Schema introspection ────────────────────────────────────────────────────


class TestSchemaIntrospection:
    @pytest.fixture
    async def schema(self, connector):
        return await connector.get_schema()

    @pytest.mark.asyncio
    async def test_user_tables_present_system_tables_absent(self, schema):
        assert CUSTOMERS in schema
        assert ORDERS in schema
        assert not any(k.startswith(("sys.", "INFORMATION_SCHEMA.")) for k in schema)

    @pytest.mark.asyncio
    async def test_table_shape(self, schema):
        t = schema[CUSTOMERS]
        assert t["schema"] == "analytics"
        assert t["name"] == "customers"
        assert t["type"] == "table"
        for key in ("columns", "foreign_keys", "indexes", "row_count", "size_mb", "description"):
            assert key in t

    @pytest.mark.asyncio
    async def test_views_detected_as_views(self, schema):
        v = schema["analytics.v_customer_totals"]
        assert v["type"] == "view"
        assert {c["name"] for c in v["columns"]} == {"customer_id", "name", "total_amount"}

    @pytest.mark.asyncio
    async def test_row_counts_from_partition_stats(self, schema):
        assert schema[CUSTOMERS]["row_count"] == 5
        assert schema[ORDERS]["row_count"] == 7

    @pytest.mark.asyncio
    async def test_primary_key_and_identity_flags(self, schema):
        cols = {c["name"]: c for c in schema[CUSTOMERS]["columns"]}
        assert cols["customer_id"]["primary_key"] is True
        assert cols["customer_id"].get("identity") is True
        assert cols["name"]["primary_key"] is False

    @pytest.mark.asyncio
    async def test_nullability(self, schema):
        cols = {c["name"]: c for c in schema[CUSTOMERS]["columns"]}
        assert cols["name"]["nullable"] is False
        assert cols["region"]["nullable"] is True

    @pytest.mark.asyncio
    async def test_data_types_include_precision(self, schema):
        cols = {c["name"]: c for c in schema[CUSTOMERS]["columns"]}
        # nvarchar max_length is in bytes; the driver halves it back to characters.
        assert cols["name"]["type"] == "nvarchar(100)"
        assert cols["region"]["type"] == "varchar(50)"
        assert cols["lifetime_value"]["type"] == "decimal(12,2)"

    @pytest.mark.asyncio
    async def test_extended_properties_become_comments(self, schema):
        assert schema[CUSTOMERS]["description"] == "Customer master table"
        cols = {c["name"]: c for c in schema[CUSTOMERS]["columns"]}
        assert cols["region"]["comment"] == "Sales region code"

    @pytest.mark.asyncio
    async def test_foreign_keys_resolved(self, schema):
        fks = schema[ORDERS]["foreign_keys"]
        assert len(fks) == 1
        assert fks[0]["column"] == "customer_id"
        assert fks[0]["references_schema"] == "analytics"
        assert fks[0]["references_table"] == "customers"
        assert fks[0]["references_column"] == "customer_id"

    @pytest.mark.asyncio
    async def test_indexes_with_ordered_columns(self, schema):
        idx = {i["name"]: i for i in schema[ORDERS]["indexes"]}
        assert "ix_orders_customer" in idx
        assert idx["ix_orders_customer"]["columns"] == "customer_id, status"
        assert idx["ix_orders_customer"]["unique"] is False

    @pytest.mark.asyncio
    async def test_unique_pk_index_marks_cardinality(self, schema):
        cols = {c["name"]: c for c in schema[CUSTOMERS]["columns"]}
        # -1.0 is the driver's sentinel for "column is unique".
        assert cols["customer_id"].get("stats", {}).get("distinct_fraction") == -1.0

    @pytest.mark.asyncio
    async def test_defaults_captured(self, schema):
        cols = {c["name"]: c for c in schema[CUSTOMERS]["columns"]}
        assert cols["lifetime_value"]["default"] is not None


# ── Sample values ───────────────────────────────────────────────────────────


class TestSampleValues:
    @pytest.mark.asyncio
    async def test_batched_sample_values(self, connector):
        result = await connector.get_sample_values(CUSTOMERS, ["name", "region"], limit=5)
        assert set(result) == {"name", "region"}
        assert "Acme Corp" in result["name"]
        assert set(result["region"]) <= {"NORTH", "SOUTH", "WEST", "EAST"}

    @pytest.mark.asyncio
    async def test_sample_values_respect_limit(self, connector):
        result = await connector.get_sample_values(CUSTOMERS, ["region"], limit=2)
        assert len(result["region"]) <= 2

    @pytest.mark.asyncio
    async def test_sample_values_exclude_nulls(self, connector):
        result = await connector.get_sample_values(ORDERS, ["status"], limit=10)
        assert all(v is not None and v != "None" for v in result["status"])

    @pytest.mark.asyncio
    async def test_empty_columns_returns_empty(self, connector):
        assert await connector.get_sample_values(CUSTOMERS, []) == {}


# ── Identifier quoting ──────────────────────────────────────────────────────


class TestQuoting:
    @pytest.fixture
    def c(self):
        from gateway.connectors.drivers.mssql import MSSQLConnector

        return MSSQLConnector()

    def test_bracket_quoting(self, c):
        assert c.quote_identifier("order") == "[order]"

    def test_closing_bracket_is_escaped(self, c):
        assert c.quote_identifier("we]ird") == "[we]]ird]"

    def test_schema_qualified_table(self, c):
        assert c.quote_table("analytics.customers") == "[analytics].[customers]"

    @pytest.mark.asyncio
    async def test_quoted_reserved_word_column_executes(self, connector):
        # [name] is not reserved, but the bracket form must still round-trip.
        rows = await connector.execute(
            f"SELECT {connector.quote_identifier('name')} FROM {connector.quote_table(CUSTOMERS)} ORDER BY customer_id"
        )
        assert rows[0]["name"] == "Acme Corp"


# ── Governance: validation + LIMIT injection on the T-SQL dialect ───────────


class TestGovernance:
    DIALECT = "tsql"

    def _validate(self, sql: str):
        from gateway.engine import validate_sql

        return validate_sql(sql, dialect=self.DIALECT)

    def _limit(self, sql: str, max_rows: int = 100) -> str:
        from gateway.engine import inject_limit

        return inject_limit(sql, max_rows=max_rows, dialect=self.DIALECT)

    def test_dialect_mapping(self):
        from gateway.engine import sqlglot_dialect

        assert sqlglot_dialect("mssql") == "tsql"

    @pytest.mark.parametrize(
        "sql",
        [
            "DROP TABLE analytics.customers",
            "DELETE FROM analytics.customers",
            "UPDATE analytics.customers SET name = 'x'",
            "INSERT INTO analytics.customers (name) VALUES ('x')",
            "CREATE TABLE t (id INT)",
            "SELECT 1; DROP TABLE analytics.customers",
        ],
    )
    def test_write_statements_blocked(self, sql):
        assert self._validate(sql).ok is False

    def test_select_allowed(self):
        assert self._validate(f"SELECT * FROM {CUSTOMERS}").ok is True

    def test_limit_injected_as_top(self):
        assert self._limit(f"SELECT * FROM {CUSTOMERS}") == f"SELECT TOP 100 * FROM {CUSTOMERS}"

    def test_existing_smaller_top_preserved(self):
        assert self._limit(f"SELECT TOP 5 * FROM {CUSTOMERS}") == f"SELECT TOP 5 * FROM {CUSTOMERS}"

    def test_oversized_top_clamped(self):
        assert self._limit(f"SELECT TOP 50000 * FROM {CUSTOMERS}") == f"SELECT TOP 100 * FROM {CUSTOMERS}"

    @pytest.mark.asyncio
    async def test_injected_top_executes_and_caps_rows(self, connector):
        governed = self._limit(f"SELECT * FROM {CUSTOMERS}", max_rows=3)
        assert "TOP 3" in governed
        rows = await connector.execute(governed)
        assert len(rows) == 3

    @pytest.mark.asyncio
    async def test_governed_pipeline_end_to_end(self, connector):
        sql = f"SELECT name, region FROM {CUSTOMERS} ORDER BY customer_id"
        result = self._validate(sql)
        assert result.ok is True
        rows = await connector.execute(self._limit(sql, max_rows=2))
        assert len(rows) == 2

    def test_literals_redacted_for_audit(self):
        from gateway.engine import redact_sql_literals

        out = redact_sql_literals(f"SELECT * FROM {CUSTOMERS} WHERE name = 'Acme Corp'", dialect=self.DIALECT)
        assert "Acme Corp" not in out
        assert "REDACTED" in out


# ── Database-level read-only enforcement (defense in depth) ─────────────────


class TestReadOnlyLogin:
    @pytest.fixture
    async def reader(self):
        from gateway.connectors.drivers.mssql import MSSQLConnector

        c = MSSQLConnector()
        await c.connect(READER_URL)
        yield c
        await c.close()

    @pytest.mark.asyncio
    async def test_reader_can_select(self, reader):
        rows = await reader.execute(f"SELECT COUNT(*) AS n FROM {CUSTOMERS}")
        assert rows[0]["n"] == 5

    @pytest.mark.asyncio
    async def test_reader_cannot_write(self, reader):
        # Even if governance were bypassed, the DB principal must refuse the write.
        with pytest.raises(RuntimeError):
            await reader.execute(f"DELETE FROM {CUSTOMERS}")

    @pytest.mark.asyncio
    async def test_reader_cannot_create(self, reader):
        with pytest.raises(RuntimeError):
            await reader.execute("CREATE TABLE analytics.should_not_exist (id INT)")

    @pytest.mark.asyncio
    async def test_reader_can_introspect_schema(self, reader):
        schema = await reader.get_schema()
        assert CUSTOMERS in schema


# ── Registry / pool wiring ──────────────────────────────────────────────────


class TestWiring:
    def test_registry_returns_mssql_connector(self):
        from gateway.connectors.drivers.mssql import MSSQLConnector
        from gateway.connectors.registry import get_connector
        from gateway.models import DBType

        assert isinstance(get_connector(DBType.mssql), MSSQLConnector)

    def test_default_port(self):
        from gateway.connectors.pool_manager import _DEFAULT_PORTS

        assert _DEFAULT_PORTS["mssql"] == 1433

    def test_url_prefixes_registered(self):
        from gateway.connectors.pool_manager import _URI_SCHEMES

        assert set(_URI_SCHEMES["mssql"]) == {"mssql://", "mssql+pymssql://", "sqlserver://"}

    def test_ssh_tunnel_capable(self):
        from gateway.connectors.pool_manager import _TUNNEL_CAPABLE_DB_TYPES

        assert "mssql" in _TUNNEL_CAPABLE_DB_TYPES


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
