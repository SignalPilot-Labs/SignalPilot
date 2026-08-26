"""Grammar + governance tests for the ``compare_join_types`` MCP tool.

Covers the SP-SEC fix in ``gateway/mcp/tools/model_verify.py``. Before the fix
``compare_join_types`` interpolated the free-text ``join_keys`` and
``where_clause`` arguments straight into a CTE template and executed the result
with NO governance at all — no ``validate_sql``, no ``inject_limit``, no
dangerous-function check. Any caller of the tool could smuggle arbitrary SQL.

After the fix:

* ``join_keys`` must match ``_JOIN_KEY_PAIR_RE`` — ``qual.col = qual.col``,
  comma-separated, unquoted ASCII identifiers only.
* ``where_clause`` is parsed by sqlglot ``into=exp.Condition``; statements,
  stacked statements, subqueries, EXISTS and comments are rejected and the
  dangerous-function walker is applied.
* The assembled SQL goes through ``gateway.engine.validate_sql`` and
  ``inject_limit`` before it reaches a connector.

The full-tool tests below drive the REAL tool function with a stubbed store and
a capturing connector, so the real template, the real ``validate_sql`` call and
the real ``inject_limit`` call all execute. Only the credential store and the
socket are faked.
"""

from __future__ import annotations

import contextlib
import types

import pytest

from gateway.engine import validate_sql
from gateway.mcp.tools import model_verify as mv

# ───────────────────────────────────────────────────────────────────────────────
# join_keys grammar
# ───────────────────────────────────────────────────────────────────────────────


class TestParseJoinKeys:
    ACCEPTED = [
        ("a.id = b.id", [("a.id", "b.id")]),
        ("a.id=b.id", [("a.id", "b.id")]),
        ("   a.id   =   b.id   ", [("a.id", "b.id")]),
        ("a.id = b.id, a.dt = b.dt", [("a.id", "b.id"), ("a.dt", "b.dt")]),
        (
            "orders.customer_id = customers.id, orders.order_date = customers.signup_date",
            [("orders.customer_id", "customers.id"), ("orders.order_date", "customers.signup_date")],
        ),
        (
            "a.k1 = b.k1, a.k2 = b.k2, a.k3 = b.k3",
            [("a.k1", "b.k1"), ("a.k2", "b.k2"), ("a.k3", "b.k3")],
        ),
        ("_a1.col_2 = _b3.col_4", [("_a1.col_2", "_b3.col_4")]),
    ]

    @pytest.mark.parametrize("raw,expected", ACCEPTED, ids=[r for r, _ in ACCEPTED])
    def test_valid_pairs_accepted(self, raw: str, expected: list[tuple[str, str]]) -> None:
        pairs, err = mv._parse_join_keys(raw)
        assert err is None, err
        assert pairs == expected

    def test_multi_key_pairs_are_anded_in_order(self) -> None:
        pairs, err = mv._parse_join_keys("a.id = b.id, a.dt = b.dt")
        assert err is None
        condition = " AND ".join(f"{lhs} = {rhs}" for lhs, rhs in pairs)
        assert condition == "a.id = b.id AND a.dt = b.dt"

    REJECTED = [
        # functions
        "lower(a.id) = b.id",
        "a.id = lower(b.id)",
        "md5(a.id) = md5(b.id)",
        "cast(a.id as text) = b.id",
        # quoted identifiers
        '"a"."id" = "b"."id"',
        "`a`.`id` = `b`.`id`",
        "[a].[id] = [b].[id]",
        "'a.id' = 'b.id'",
        # stacked statements
        "a.id = b.id; DROP TABLE x --",
        "1=1; DROP TABLE x --",
        "a.id = b.id; SELECT 1",
        # set operations / subqueries
        "a.id = b.id UNION SELECT 1",
        "a.id = b.id UNION ALL SELECT 1, 2",
        "a.id IN (SELECT id FROM secrets)",
        "a.id = (SELECT max(id) FROM secrets)",
        "EXISTS (SELECT 1 FROM secrets)",
        # comments
        "a.id = b.id --comment",
        "a.id = b.id /* comment */",
        "a.id /* x */ = b.id",
        # dangerous functions
        "a.id = pg_read_file('/etc/passwd')",
        "a.id = dblink('host=evil', 'SELECT 1')",
        "a.id = xp_cmdshell('dir')",
        "a.id = read_csv_auto('/etc/passwd')",
        # wrong shape
        "id = b.id",
        "a.id = id",
        "a.id > b.id",
        "a.id <> b.id",
        "a.id = b.id AND a.x = b.x",
        "a.id = b.id OR 1=1",
        "1 = 1",
        "a.b.c = d.e.f",
        "",
        "   ",
        ",",
        "a.id = b.id,",
        # unicode / whitespace smuggling
        "a.id = b.id\n; DROP TABLE x",
        "a.id\t=\tb.id; DROP TABLE x",
    ]

    @pytest.mark.parametrize("raw", REJECTED, ids=[repr(r) for r in REJECTED])
    def test_invalid_pairs_rejected(self, raw: str) -> None:
        pairs, err = mv._parse_join_keys(raw)
        assert err is not None, f"ACCEPTED a payload that must be rejected: {raw!r}"
        assert pairs == []

    def test_rejection_message_is_actionable(self) -> None:
        _, err = mv._parse_join_keys("lower(a.id) = b.id")
        assert err is not None
        assert "qualified-column equality" in err


# ───────────────────────────────────────────────────────────────────────────────
# where_clause predicate validation
# ───────────────────────────────────────────────────────────────────────────────


class TestValidateWherePredicate:
    ACCEPTED = [
        "a.status = 'paid'",
        "a.amount > 100",
        "a.amount > 100 AND b.flag IS NOT NULL",
        "a.status IN ('paid', 'open')",
        "a.created_at BETWEEN '2024-01-01' AND '2024-02-01'",
        "a.name LIKE 'Acme%'",
        "NOT a.deleted",
        "COALESCE(a.amount, 0) > 0",
    ]

    @pytest.mark.parametrize("raw", ACCEPTED, ids=ACCEPTED)
    def test_plain_predicates_accepted(self, raw: str) -> None:
        assert mv._validate_where_predicate(raw, "postgres") is None

    REJECTED = [
        # stacked statements / comments
        "1=1; DROP TABLE x --",
        "a.id = 1; SELECT 1",
        "a.id = 1 -- comment",
        "a.id = 1 /* comment */",
        # statements
        "DROP TABLE x",
        "SELECT 1",
        "INSERT INTO t VALUES (1)",
        "UPDATE t SET a = 1",
        # set operations
        "1=1 UNION SELECT 1",
        # subqueries / EXISTS
        "a.id IN (SELECT id FROM secrets)",
        "a.id = (SELECT max(id) FROM secrets)",
        "EXISTS (SELECT 1 FROM secrets)",
        "NOT EXISTS (SELECT 1 FROM secrets)",
        # dangerous functions
        "a.x = pg_read_file('/etc/passwd')",
        "a.x = dblink('host=evil', 'SELECT 1')",
        "pg_read_server_files('/etc/passwd') IS NOT NULL",
        "a.x = lo_import('/etc/passwd')",
        # parenthesis breakout
        "a.x = 1) OR (1=1",
    ]

    @pytest.mark.parametrize("raw", REJECTED, ids=[repr(r) for r in REJECTED])
    def test_dangerous_predicates_rejected(self, raw: str) -> None:
        assert mv._validate_where_predicate(raw, "postgres") is not None, (
            f"ACCEPTED a where_clause that must be rejected: {raw!r}"
        )

    @pytest.mark.parametrize(
        "raw,dialect",
        [
            ("a.x = xp_cmdshell('dir')", "tsql"),
            ("a.x = read_csv_auto('/etc/passwd')", "duckdb"),
            ("a.x = reflect('java.lang.Runtime', 'getRuntime')", "databricks"),
            ("a.x = load_file('/etc/passwd')", "mysql"),
        ],
    )
    def test_dialect_specific_dangerous_functions_rejected(self, raw: str, dialect: str) -> None:
        assert mv._validate_where_predicate(raw, dialect) is not None

    def test_subquery_rejection_message(self) -> None:
        assert "Subqueries are not allowed" in (mv._validate_where_predicate("a.id IN (SELECT 1)", "postgres") or "")

    def test_comment_rejection_message(self) -> None:
        msg = mv._validate_where_predicate("a.id = 1 -- x", "postgres") or ""
        assert "semicolons and comments" in msg


# ───────────────────────────────────────────────────────────────────────────────
# Full-tool tests: the real template + real validate_sql + real inject_limit
# ───────────────────────────────────────────────────────────────────────────────


class _FakeStore:
    async def get_connection(self, name: str):
        return types.SimpleNamespace(db_type="postgres", name=name)

    async def get_connection_string(self, name: str) -> str:
        return "postgresql://u:p@127.0.0.1:5432/d"

    async def get_credential_extras(self, name: str) -> dict:
        return {}

    async def list_connections(self) -> list:
        return []


_CANNED_ROW = {
    "left_rows": 10,
    "right_rows": 5,
    "inner_rows": 5,
    "left_join_rows": 10,
    "left_matched": 5,
    "left_unmatched": 5,
    "right_join_rows": 5,
    "right_matched": 5,
    "right_unmatched": 0,
    "full_join_rows": 10,
}


@pytest.fixture
def executed_sql(monkeypatch):
    """Drive the real tool, capturing the SQL handed to the connector."""
    captured: list[str] = []

    @contextlib.asynccontextmanager
    async def fake_store_session(*args, **kwargs):
        yield _FakeStore()

    class _FakeConnector:
        async def execute(self, sql: str, params=None):
            captured.append(sql)
            return [dict(_CANNED_ROW)]

    class _FakePool:
        @contextlib.asynccontextmanager
        async def connection(self, *args, **kwargs):
            yield _FakeConnector()

    import gateway.connectors.pool_manager as pool_module

    monkeypatch.setattr(mv, "_store_session", fake_store_session)
    monkeypatch.setattr(pool_module, "pool_manager", _FakePool())
    return captured


class TestConstructedSQLIsGoverned:
    async def test_single_key_join_executes_and_sql_is_governed(self, executed_sql) -> None:
        out = await mv.compare_join_types("conn1", "orders", "customers", "a.id = b.customer_id")
        assert "JOIN Impact Analysis" in out
        assert len(executed_sql) == 1
        sql = executed_sql[0]
        # The real governance layer must accept the constructed SQL ...
        assert validate_sql(sql, dialect="postgres").ok is True
        # ... and inject_limit must have capped it.
        assert "LIMIT 1000" in sql.upper()
        assert "a.id = b.customer_id" in sql

    async def test_multi_key_join_is_anded(self, executed_sql) -> None:
        out = await mv.compare_join_types("conn1", "orders", "customers", "a.id = b.cid, a.dt = b.dt")
        assert "ON a.id = b.cid AND a.dt = b.dt" in out
        sql = executed_sql[0]
        assert sql.count("a.id = b.cid AND a.dt = b.dt") == 4  # inner / left / right / full
        assert validate_sql(sql, dialect="postgres").ok is True
        assert "LIMIT 1000" in sql.upper()

    async def test_where_clause_is_applied_to_every_join_cte(self, executed_sql) -> None:
        await mv.compare_join_types("conn1", "orders", "customers", "a.id = b.cid", "a.status = 'paid'")
        sql = executed_sql[0]
        assert sql.count("a.status = 'paid'") == 4
        assert validate_sql(sql, dialect="postgres").ok is True
        assert "LIMIT 1000" in sql.upper()

    def _bad_join_keys() -> list[str]:
        return [
            "lower(a.id) = b.id",
            '"a"."id" = "b"."id"',
            "1=1; DROP TABLE x --",
            "a.id = b.id UNION SELECT 1",
            "a.id IN (SELECT id FROM secrets)",
            "EXISTS (SELECT 1 FROM secrets)",
            "a.id = b.id -- x",
            "a.id = pg_read_file('/etc/passwd')",
            "a.id = dblink('host=evil', 'SELECT 1')",
        ]

    @pytest.mark.parametrize("bad", _bad_join_keys(), ids=[repr(b) for b in _bad_join_keys()])
    async def test_bad_join_keys_never_reach_the_connector(self, executed_sql, bad: str) -> None:
        out = await mv.compare_join_types("conn1", "orders", "customers", bad)
        assert out.startswith("Error:"), out
        assert executed_sql == [], f"payload reached the database: {bad!r}"

    def _bad_where() -> list[str]:
        return [
            "1=1; DROP TABLE x --",
            "a.x = 1 UNION SELECT 1",
            "a.id IN (SELECT id FROM secrets)",
            "EXISTS (SELECT 1 FROM secrets)",
            "a.id = 1 -- x",
            "a.id = 1 /* x */",
            "a.x = pg_read_file('/etc/passwd')",
            "a.x = dblink('host=evil', 'SELECT 1')",
            "DROP TABLE x",
            "a.x = 1) OR (1=1",
        ]

    @pytest.mark.parametrize("bad", _bad_where(), ids=[repr(b) for b in _bad_where()])
    async def test_bad_where_clause_never_reaches_the_connector(self, executed_sql, bad: str) -> None:
        out = await mv.compare_join_types("conn1", "orders", "customers", "a.id = b.cid", bad)
        assert out.startswith("Error:"), out
        assert executed_sql == [], f"payload reached the database: {bad!r}"

    @pytest.mark.parametrize("bad_table", ["orders; DROP TABLE x", "orders'--", "a.b.c.d", "orders/../etc"])
    async def test_bad_table_names_never_reach_the_connector(self, executed_sql, bad_table: str) -> None:
        out = await mv.compare_join_types("conn1", bad_table, "customers", "a.id = b.cid")
        assert out.startswith("Error:"), out
        assert executed_sql == []
