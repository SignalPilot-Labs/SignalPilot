"""Tests for the SQL validation engine — the core security boundary."""

import pytest

from gateway.engine import ValidationResult, inject_limit, validate_sql


class TestValidateSQL:
    """Test the SQL validation pipeline."""

    def test_empty_query_blocked(self):
        result = validate_sql("")
        assert not result.ok
        assert "Empty" in (result.blocked_reason or "")

    def test_whitespace_only_blocked(self):
        result = validate_sql("   \n  ")
        assert not result.ok

    def test_simple_select_allowed(self):
        result = validate_sql("SELECT 1")
        assert result.ok
        assert result.blocked_reason is None

    def test_select_from_table(self):
        result = validate_sql("SELECT id, name FROM users WHERE active = true")
        assert result.ok
        assert "users" in result.tables
        assert "id" in result.columns
        assert "name" in result.columns

    def test_select_with_join(self):
        result = validate_sql("SELECT u.name, o.total FROM users u JOIN orders o ON u.id = o.user_id")
        assert result.ok
        assert "users" in result.tables
        assert "orders" in result.tables

    def test_cte_allowed(self):
        result = validate_sql(
            "WITH active_users AS (SELECT * FROM users WHERE active) SELECT count(*) FROM active_users"
        )
        assert result.ok

    def test_union_allowed(self):
        result = validate_sql("SELECT id FROM users UNION SELECT id FROM admins")
        assert result.ok

    # ─── DDL/DML blocking ─────────────────────────────────────────────
    def test_insert_blocked(self):
        result = validate_sql("INSERT INTO users (name) VALUES ('test')")
        assert not result.ok
        assert "Insert" in (result.blocked_reason or "")

    def test_update_blocked(self):
        result = validate_sql("UPDATE users SET name = 'test' WHERE id = 1")
        assert not result.ok

    def test_delete_blocked(self):
        result = validate_sql("DELETE FROM users WHERE id = 1")
        assert not result.ok

    def test_drop_table_blocked(self):
        result = validate_sql("DROP TABLE users")
        assert not result.ok

    def test_alter_table_blocked(self):
        result = validate_sql("ALTER TABLE users ADD COLUMN email text")
        assert not result.ok

    def test_create_table_blocked(self):
        result = validate_sql("CREATE TABLE evil (id int)")
        assert not result.ok

    def test_truncate_blocked(self):
        result = validate_sql("TRUNCATE TABLE users")
        assert not result.ok

    def test_grant_blocked(self):
        result = validate_sql("GRANT ALL ON users TO public")
        assert not result.ok

    # ─── Statement stacking ──────────────────────────────────────────
    def test_statement_stacking_blocked(self):
        result = validate_sql("SELECT 1; DROP TABLE users")
        assert not result.ok
        assert "stacking" in (result.blocked_reason or "").lower()

    def test_stacking_with_comment_bypass_blocked(self):
        """HIGH-04: stacking hidden in comments should still be caught."""
        result = validate_sql("SELECT 1; /* comment */ DROP TABLE users")
        assert not result.ok

    def test_stacking_with_line_comment_bypass_blocked(self):
        """HIGH-04: stacking hidden behind line comments."""
        result = validate_sql("SELECT 1 -- comment\n; DROP TABLE users")
        assert not result.ok

    def test_trailing_semicolon_allowed(self):
        """A single trailing semicolon is fine."""
        result = validate_sql("SELECT 1;")
        assert result.ok

    # ─── Blocked tables ──────────────────────────────────────────────
    def test_blocked_table_rejected(self):
        result = validate_sql(
            "SELECT * FROM secret_table",
            blocked_tables=["secret_table"],
        )
        assert not result.ok
        assert "blocked by policy" in (result.blocked_reason or "").lower()

    def test_blocked_table_case_insensitive(self):
        result = validate_sql(
            "SELECT * FROM SECRET_TABLE",
            blocked_tables=["secret_table"],
        )
        assert not result.ok

    def test_non_blocked_table_allowed(self):
        result = validate_sql(
            "SELECT * FROM public_table",
            blocked_tables=["secret_table"],
        )
        assert result.ok

    # ─── Input limits ────────────────────────────────────────────────
    def test_query_length_limit(self):
        """MED-07: queries over 100KB should be rejected."""
        long_sql = "SELECT " + "a, " * 50001 + "b FROM t"
        result = validate_sql(long_sql)
        assert not result.ok
        assert "length" in (result.blocked_reason or "").lower()


class TestInjectLimit:
    """Test LIMIT injection/clamping."""

    def test_no_limit_gets_injected(self):
        result = inject_limit("SELECT * FROM users")
        assert "LIMIT" in result.upper()
        assert "10000" in result

    def test_existing_small_limit_preserved(self):
        result = inject_limit("SELECT * FROM users LIMIT 50")
        assert "50" in result

    def test_existing_large_limit_clamped(self):
        result = inject_limit("SELECT * FROM users LIMIT 999999", max_rows=10000)
        assert "999999" not in result
        assert "10000" in result

    def test_custom_max_rows(self):
        result = inject_limit("SELECT * FROM users", max_rows=500)
        assert "500" in result

    def test_semicolon_stripped(self):
        result = inject_limit("SELECT * FROM users;")
        assert not result.rstrip().endswith(";")


class TestTsqlSetOperationLimit:
    """T-SQL cannot LIMIT a set operation directly. sqlglot wraps it as a
    derived table; a trailing ORDER BY / OFFSET / FETCH inside that table is
    SQL Server error 1033. Those clauses must move to the outer select, the
    cap must be TOP (or FETCH when an OFFSET exists), and a branch's own TOP
    must stay on its branch."""

    @pytest.mark.parametrize(
        ("sql", "expected"),
        [
            (
                "select 'x' as d, a from t union all select 'y', a from u order by d, a desc",
                "SELECT TOP 100 * FROM (SELECT 'x' AS d, a FROM t UNION ALL SELECT 'y', a FROM u) AS _sp_limit ORDER BY d, a DESC",
            ),
            (
                "select a from t union all select a from u union all select a from v order by a",
                "SELECT TOP 100 * FROM (SELECT a FROM t UNION ALL SELECT a FROM u UNION ALL SELECT a FROM v) AS _sp_limit ORDER BY a",
            ),
            (
                "select a from t except select a from u order by a",
                "SELECT TOP 100 * FROM (SELECT a FROM t EXCEPT SELECT a FROM u) AS _sp_limit ORDER BY a",
            ),
            (
                "select a from t intersect select a from u",
                "SELECT TOP 100 * FROM (SELECT a FROM t INTERSECT SELECT a FROM u) AS _sp_limit",
            ),
            (
                "select a, b from t union all select a, b from u order by 2 desc, 1",
                "SELECT TOP 100 * FROM (SELECT a, b FROM t UNION ALL SELECT a, b FROM u) AS _sp_limit ORDER BY 2 DESC, 1",
            ),
            (
                "select a from t union select a from u order by a",
                "SELECT TOP 100 * FROM (SELECT a FROM t UNION SELECT a FROM u) AS _sp_limit ORDER BY a",
            ),
            (
                "select a from t union all select a from u",
                "SELECT TOP 100 * FROM (SELECT a FROM t UNION ALL SELECT a FROM u) AS _sp_limit",
            ),
            (
                "with c as (select a, n from t) select 'x' as d, a, n from c union all select 'y', a, n from u order by d, n desc",
                "WITH c AS (SELECT a AS a, n AS n FROM t) SELECT TOP 100 * FROM (SELECT 'x' AS d, a, n FROM c UNION ALL SELECT 'y', a, n FROM u) AS _sp_limit ORDER BY d, n DESC",
            ),
            (
                "select a from t union all select top 3 a from u order by a",
                "SELECT TOP 100 * FROM (SELECT a FROM t UNION ALL SELECT TOP 3 a FROM u) AS _sp_limit ORDER BY a",
            ),
            (
                "(select top 5 a from t order by a) union all (select top 5 a from u order by a) order by a",
                "SELECT TOP 100 * FROM ((SELECT TOP 5 a FROM t ORDER BY a) UNION ALL (SELECT TOP 5 a FROM u ORDER BY a)) AS _sp_limit ORDER BY a",
            ),
            (
                "select a from t union all select a from u order by a offset 5 rows fetch next 10 rows only",
                "SELECT * FROM (SELECT a FROM t UNION ALL SELECT a FROM u) AS _sp_limit ORDER BY a OFFSET 5 ROWS FETCH FIRST 10 ROWS ONLY",
            ),
            (
                "select a from t union all select a from u order by a offset 0 rows fetch next 999999 rows only",
                "SELECT * FROM (SELECT a FROM t UNION ALL SELECT a FROM u) AS _sp_limit ORDER BY a OFFSET 0 ROWS FETCH FIRST 100 ROWS ONLY",
            ),
        ],
        ids=[
            "union-order",
            "three-way-union",
            "except-order",
            "intersect-no-order",
            "order-by-ordinal",
            "union-distinct",
            "no-order-no-limit",
            "cte-hoisted-out",
            "tail-branch-top-stays",
            "parenthesised-branches",
            "offset-fetch-within-cap",
            "fetch-over-cap",
        ],
    )
    def test_tsql_set_operations(self, sql, expected):
        assert inject_limit(sql, 100, dialect="tsql") == expected

    def test_order_by_never_lands_inside_the_derived_table(self):
        out = inject_limit(
            "select a from t union all select a from u order by a", 100, dialect="tsql"
        )
        inner = out[out.index("(") + 1 : out.rindex(") AS _sp_limit")]
        assert "ORDER BY" not in inner

    @pytest.mark.parametrize(
        ("sql", "expected"),
        [
            ("select a from t order by a", "SELECT TOP 100 a FROM t ORDER BY a"),
            ("select top 3 a from t order by a", "SELECT TOP 3 a FROM t ORDER BY a"),
            ("select top 999999 a from t order by a", "SELECT TOP 100 a FROM t ORDER BY a"),
            (
                "with c as (select a from t) select a from c order by a",
                "WITH c AS (SELECT a AS a FROM t) SELECT TOP 100 a FROM c ORDER BY a",
            ),
            (
                "select a from t order by a offset 5 rows fetch next 10 rows only",
                "SELECT a FROM t ORDER BY a OFFSET 5 ROWS FETCH NEXT 10 ROWS ONLY",
            ),
            (
                "select a from t order by a offset 5 rows fetch next 999999 rows only",
                "SELECT a FROM t ORDER BY a OFFSET 5 ROWS FETCH FIRST 100 ROWS ONLY",
            ),
        ],
        ids=["plain", "top-under-cap", "top-over-cap", "cte", "offset-fetch-under-cap", "offset-fetch-over-cap"],
    )
    def test_tsql_plain_selects(self, sql, expected):
        assert inject_limit(sql, 100, dialect="tsql") == expected

    def test_postgres_set_operations_keep_a_plain_limit(self):
        out = inject_limit("select a from t union all select a from u order by a", 100, dialect="postgres")
        assert out == "SELECT a FROM t UNION ALL SELECT a FROM u ORDER BY a LIMIT 100"
