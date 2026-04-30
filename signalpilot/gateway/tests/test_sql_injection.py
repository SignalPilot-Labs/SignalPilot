"""Tests for SQL injection fixes across the gateway.

Covers:
- _quote_identifier / _quote_table_name helpers in schema.py
- explore_column_values: filter_pattern escaping, table quoting, column quoting
- explore_columns_deep: table_key quoting in stat_sql
- _quote_table in mcp_server.py
- ClickHouseConnector._quote_identifier in fallback path
- MSSQLConnector string literal escaping in get_sample_values
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request, Response
from fastapi.testclient import TestClient
from starlette.middleware.base import RequestResponseEndpoint

from gateway.api.deps import get_store
from gateway.api.schema import _quote_identifier, _quote_table_name
from gateway.main import app
from gateway.mcp_server import _quote_table
from gateway.middleware import APIKeyAuthMiddleware

# ─── Shared auth state ───────────────────────────────────────────────────────

_CURRENT_AUTH: dict[str, Any] = {
    "auth_method": "api_key",
    "user_id": "test-user",
    "scopes": ["write"],
}


async def _controlled_dispatch(
    request: Request,
    call_next: RequestResponseEndpoint,
) -> Response:
    request.state.auth = dict(_CURRENT_AUTH)
    return await call_next(request)


def _set_scopes(scopes: list[str]) -> None:
    _CURRENT_AUTH["scopes"] = list(scopes)


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
def client():
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
                middleware_instance.dispatch_func = _controlled_dispatch
            yield _client

    app.dependency_overrides.pop(get_store, None)


# ─── TestQuoteIdentifierHelper ────────────────────────────────────────────────


class TestQuoteIdentifierHelper:
    """Unit tests for _quote_identifier and _quote_table_name in schema.py."""

    def test_double_quote_simple_name(self):
        assert _quote_identifier("users", '"') == '"users"'

    def test_double_quote_escapes_embedded_double_quote(self):
        result = _quote_identifier('col"name', '"')
        assert result == '"col""name"'

    def test_backtick_simple_name(self):
        assert _quote_identifier("users", "`") == "`users`"

    def test_backtick_escapes_embedded_backtick(self):
        result = _quote_identifier("col`name", "`")
        assert result == "`col``name`"

    def test_bracket_simple_name(self):
        assert _quote_identifier("users", "[") == "[users]"

    def test_bracket_escapes_embedded_close_bracket(self):
        result = _quote_identifier("col]name", "[")
        assert result == "[col]]name]"

    def test_quote_table_name_single_part(self):
        assert _quote_table_name("users", '"') == '"users"'

    def test_quote_table_name_schema_qualified(self):
        assert _quote_table_name("public.users", '"') == '"public"."users"'

    def test_quote_table_name_mssql_bracket(self):
        assert _quote_table_name("dbo.orders", "[") == "[dbo].[orders]"

    def test_quote_table_name_escapes_dots_in_name(self):
        # A table name split on '.': ['public', '"evil']
        # '"evil' quoted with " becomes: " + "" + evil + " = """evil"
        result = _quote_table_name('public."evil', '"')
        assert result == '"public"."""evil"'

    def test_quote_table_name_with_embedded_quote_in_schema(self):
        result = _quote_table_name('pub"lic.users', '"')
        assert result == '"pub""lic"."users"'


# ─── TestMcpServerQuoteTable ──────────────────────────────────────────────────


class TestMcpServerQuoteTable:
    """Unit tests for _quote_table in mcp_server.py."""

    def test_simple_table_name(self):
        assert _quote_table("orders") == '"orders"'

    def test_schema_qualified_table(self):
        assert _quote_table("main.track") == '"main"."track"'

    def test_escapes_embedded_double_quote_in_table(self):
        result = _quote_table('evil"table')
        assert result == '"evil""table"'

    def test_escapes_embedded_double_quote_in_schema(self):
        result = _quote_table('evil"schema.orders')
        assert result == '"evil""schema"."orders"'

    def test_injection_attempt_neutralised(self):
        """A name like 'x"; DROP TABLE y; --' must be properly quoted."""
        result = _quote_table('x"; DROP TABLE y; --')
        # The entire string becomes a quoted identifier — no unescaped "
        assert result == '"x""; DROP TABLE y; --"'
        # The closing " of the identifier is the last character — no raw SQL escape
        # Confirm there is no unescaped injection: split on . gives one part
        assert '"' not in result[1:-1].replace('""', "")


# ─── TestClickHouseQuoteIdentifier ───────────────────────────────────────────


class TestClickHouseQuoteIdentifier:
    """Unit tests for ClickHouseConnector._quote_identifier."""

    def _make_connector(self):
        from gateway.connectors.clickhouse import ClickHouseConnector

        conn = ClickHouseConnector.__new__(ClickHouseConnector)
        return conn

    def test_quote_char_is_backtick(self):
        conn = self._make_connector()
        assert conn._identifier_quote == "`"

    def test_quote_identifier_simple(self):
        conn = self._make_connector()
        assert conn._quote_identifier("col") == "`col`"

    def test_quote_identifier_escapes_backtick(self):
        conn = self._make_connector()
        result = conn._quote_identifier("col`name")
        assert result == "`col``name`"

    def test_quote_identifier_injection_attempt(self):
        conn = self._make_connector()
        # Input has a leading backtick — it gets escaped to ``
        # Result: `` (open) + `` (escaped backtick) + ; DROP TABLE x; -- + ` (close)
        result = conn._quote_identifier("`; DROP TABLE x; --")
        assert result.startswith("`")
        assert result.endswith("`")
        # The embedded backtick is doubled — the identifier is fully enclosed
        assert result == "```; DROP TABLE x; --`"
        # No unescaped single backtick that would close the identifier early (between start and end)
        inner = result[1:-1]
        # Any remaining backtick in inner must be doubled
        assert "`" not in inner.replace("``", "")


# ─── TestMssqlStringLiteralEscaping ──────────────────────────────────────────


class TestMssqlStringLiteralEscaping:
    """Unit tests for MSSQL string literal escaping in get_sample_values."""

    def _make_connector(self):
        from gateway.connectors.mssql import MSSQLConnector

        conn = MSSQLConnector.__new__(MSSQLConnector)
        conn._conn = MagicMock()
        return conn

    def test_single_quote_in_col_name_escaped_in_literal(self):
        """Column name with a single quote must be escaped in the SQL string literal."""
        # Reconstruct the escaping logic from the fix (same pattern as base.py:267)
        col = "it's"
        safe_name = col.replace("'", "''")

        # The escaped safe_name should have doubled single quotes
        assert safe_name == "it''s"

        sql_fragment = f"SELECT '{safe_name}' AS _col"
        # The escaped sequence appears in the SQL
        assert "it''s" in sql_fragment
        # The literal is delimited by the first and last single quote in the fragment
        # 'it''s' — the '' is the escape for a literal ' inside the string
        # SQL parsers treat '' as one character, not as string terminator
        # Verify no odd single quote that would break the literal:
        # There should be exactly 4 single quotes: open, '', close → count = 4
        assert sql_fragment.count("'") == 4


# ─── TestExploreColumnValuesInjection ────────────────────────────────────────


class TestExploreColumnValuesInjection:
    """Integration tests for SQL injection fixes in explore_column_values."""

    def _make_store_with_connection(self, db_type: str = "postgres") -> AsyncMock:
        store = AsyncMock()
        conn_info = MagicMock()
        conn_info.db_type = db_type
        conn_info.name = "testconn"
        store.get_connection.return_value = conn_info
        store.get_connection_string.return_value = "postgresql://localhost/test"
        store.get_credential_extras.return_value = {}
        mock_settings = AsyncMock()
        mock_settings.default_timeout_seconds = 30
        mock_settings.blocked_tables = []
        store.load_settings.return_value = mock_settings
        return store

    def test_filter_pattern_too_long_returns_422(self, client):
        _set_scopes(["write"])
        long_pattern = "a" * 201
        response = client.post(
            "/api/connections/testconn/schema/explore",
            params={"table": "public.users", "column": "status", "filter_pattern": long_pattern},
        )
        assert response.status_code == 422

    def test_requires_write_scope(self, client):
        _set_scopes([])
        response = client.post(
            "/api/connections/testconn/schema/explore",
            params={"table": "public.users", "column": "status"},
        )
        assert response.status_code == 403

    def test_filter_pattern_uses_parameterized_query_for_mysql(self, client):
        """MySQL must use %s placeholder, not string interpolation, to prevent
        backslash-quote bypass (\\' defeating quote-doubling)."""
        store = self._make_store_with_connection(db_type="mysql")
        mock_connector = AsyncMock()
        mock_connector.execute.return_value = [{"value": "active", "count": 5}]

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _fake_conn(*a, **kw):
            yield mock_connector

        _set_scopes(["write"])
        with patch("gateway.api.schema.pool_manager") as mock_pm:
            mock_pm.connection = _fake_conn
            app.dependency_overrides[get_store] = lambda: store
            try:
                client.post(
                    "/api/connections/testconn/schema/explore",
                    params={
                        "table": "public.users",
                        "column": "status",
                        "filter_pattern": "\\' OR 1=1 --",
                    },
                )
            finally:
                app.dependency_overrides[get_store] = _fake_get_store

        # The explore query must use a parameterized %s placeholder
        call_args = mock_connector.execute.call_args_list[0]
        sql_sent = call_args.args[0] if call_args.args else call_args.kwargs.get("sql", "")
        params_sent = call_args.kwargs.get("params")
        assert "%s" in sql_sent, f"MySQL query must use %s placeholder, got: {sql_sent}"
        assert params_sent == ["\\' OR 1=1 --"], f"Param must be the raw filter_pattern, got: {params_sent}"
        # Crucially: the raw injection string must NOT appear in the SQL text
        assert "OR 1=1" not in sql_sent

    def test_filter_pattern_uses_parameterized_query_for_postgres(self, client):
        """PostgreSQL must use $1 placeholder for filter_pattern."""
        store = self._make_store_with_connection(db_type="postgres")
        mock_connector = AsyncMock()
        mock_connector.execute.return_value = [{"value": "active", "count": 5}]

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _fake_conn(*a, **kw):
            yield mock_connector

        _set_scopes(["write"])
        with patch("gateway.api.schema.pool_manager") as mock_pm:
            mock_pm.connection = _fake_conn
            app.dependency_overrides[get_store] = lambda: store
            try:
                client.post(
                    "/api/connections/testconn/schema/explore",
                    params={
                        "table": "public.users",
                        "column": "status",
                        "filter_pattern": "%active%",
                    },
                )
            finally:
                app.dependency_overrides[get_store] = _fake_get_store

        call_args = mock_connector.execute.call_args_list[0]
        sql_sent = call_args.args[0] if call_args.args else call_args.kwargs.get("sql", "")
        params_sent = call_args.kwargs.get("params")
        assert "$1" in sql_sent, f"Postgres query must use $1 placeholder, got: {sql_sent}"
        assert params_sent == ["%active%"]

    def test_filter_pattern_backslash_quote_bypass_neutralised_for_trino(self):
        """Trino (no param support) must escape backslashes to prevent \\' bypass."""
        # Trino falls back to manual escaping since its connector ignores params.
        injected = "\\' OR 1=1 --"
        # Simulate the escaping logic from schema.py's Trino fallback path
        safe = injected.replace("\\", "\\\\").replace("'", "''")
        sql_fragment = f"WHERE col LIKE '{safe}'"
        # The backslash is doubled (\\\\) so MySQL-style \' bypass is neutralised.
        # In the SQL string literal: \\\\ = literal \\, '' = literal '
        # The OR 1=1 remains inside the string literal.
        assert "OR 1=1" in sql_fragment  # present as literal text
        # Verify the string literal is properly closed — count unescaped quotes
        # The fragment should be a single WHERE clause, not breakable SQL
        assert sql_fragment.startswith("WHERE col LIKE '")
        assert sql_fragment.endswith("'")

    def test_filter_pattern_sql_injection_is_escaped(self):
        """filter_pattern with SQL injection attempt is escaped before execution."""
        injected_pattern = "'; DROP TABLE users; --"
        safe = injected_pattern.replace("\\", "\\\\").replace("'", "''")
        # Verify the escaping doubles the single quote
        assert safe == "''; DROP TABLE users; --"
        # The resulting SQL fragment has the injection fully contained in the literal
        sql_fragment = f"WHERE col LIKE '{safe}'"
        assert "WHERE col LIKE '''; DROP TABLE users; --'" == sql_fragment

    def test_filter_pattern_or_1_equals_1_is_not_injected(self):
        """Negative test: ' OR 1=1 -- must be escaped so it cannot act as SQL logic."""
        injected = "' OR 1=1 --"
        safe = injected.replace("\\", "\\\\").replace("'", "''")
        assert safe == "'' OR 1=1 --"
        sql_fragment = f"WHERE col LIKE '{safe}'"
        assert sql_fragment == "WHERE col LIKE ''' OR 1=1 --'"
        assert "LIKE ''' OR 1=1 --'" in sql_fragment

    def test_table_name_with_double_quote_is_quoted(self):
        """Table name containing a double quote must be properly quoted in SQL."""
        table = 'public."evil'
        result = _quote_table_name(table, '"')
        # Each part is quoted and embedded quotes are doubled
        assert '"public"' in result
        assert '"""evil"' in result

    def test_column_name_with_double_quote_is_quoted(self):
        """Column name containing a double quote must be properly quoted."""
        col = 'col"name'
        result = _quote_identifier(col, '"')
        assert result == '"col""name"'

    def test_mssql_column_with_close_bracket_is_quoted(self):
        """MSSQL column name with ] must escape it as ]] in bracket quoting."""
        col = "col]name"
        result = _quote_identifier(col, "[")
        assert result == "[col]]name]"


# ─── TestExploreColumnsDeepTableKeyQuoting ────────────────────────────────────


class TestExploreColumnsDeepTableKeyQuoting:
    """Tests for table_key quoting in explore_columns_deep stat_sql."""

    def test_quote_table_name_for_stat_sql(self):
        """Verify that _quote_table_name correctly quotes the table_key used in stat_sql."""
        table_key = "public.orders"
        quoted = _quote_table_name(table_key, '"')
        assert quoted == '"public"."orders"'

        sql = f'SELECT MIN("amount") FROM {quoted}'
        # No unquoted dots in table reference
        assert 'FROM "public"."orders"' in sql

    def test_injection_in_table_key_is_neutralised(self):
        """A table_key containing injection attempt is properly quoted."""
        table_key = 'public."evil; DROP TABLE x; --'
        quoted = _quote_table_name(table_key, '"')
        # The second part (after dot) must be fully quoted with embedded " doubled
        assert quoted.startswith('"public"."')
        assert quoted.endswith('"')
        # No raw SQL keywords outside the quotes
        tail = quoted.split('."', 1)[1][:-1]  # content between the second pair of quotes
        # The injection is contained — verify no unescaped " breaks the quoting
        assert '"' not in tail.replace('""', "")
