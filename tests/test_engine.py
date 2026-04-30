"""
Tests for the SQL query engine — the governance gatekeeper.

Tests cover:
- SQL validation (read-only enforcement, DDL/DML blocking)
- Statement stacking detection (including comment bypass attempts)
- LIMIT injection and clamping
- Blocked tables enforcement
- Input length limits
- Empty/malformed query handling
"""

import pytest

from signalpilot.gateway.gateway.engine import validate_sql, inject_limit


class TestValidateSQL:
    """Tests for validate_sql() — the SQL governance validator."""

    # ── Basic SELECT queries (should pass) ──

    def test_simple_select(self):
        result = validate_sql("SELECT * FROM users")
        assert result.ok is True
        assert "users" in result.tables

    def test_select_with_where(self):
        result = validate_sql("SELECT id, name FROM users WHERE active = true")
        assert result.ok is True

    def test_select_with_join(self):
        result = validate_sql(
            "SELECT u.id, o.total FROM users u JOIN orders o ON u.id = o.user_id"
        )
        assert result.ok is True
        assert "users" in result.tables
        assert "orders" in result.tables

    def test_select_with_subquery(self):
        result = validate_sql(
            "SELECT * FROM users WHERE id IN (SELECT user_id FROM orders)"
        )
        assert result.ok is True

    def test_cte_query(self):
        result = validate_sql("""
            WITH active_users AS (
                SELECT * FROM users WHERE active = true
            )
            SELECT * FROM active_users
        """)
        assert result.ok is True

    def test_union_query(self):
        result = validate_sql(
            "SELECT id FROM users UNION ALL SELECT id FROM admins"
        )
        assert result.ok is True

    def test_select_with_aggregation(self):
        result = validate_sql(
            "SELECT department, COUNT(*) FROM employees GROUP BY department HAVING COUNT(*) > 5"
        )
        assert result.ok is True

    # ── DDL/DML blocking (should fail) ──

    def test_block_create_table(self):
        result = validate_sql("CREATE TABLE evil (id int)")
        assert result.ok is False
        assert "blocked" in result.blocked_reason.lower() or "Create" in result.blocked_reason

    def test_block_drop_table(self):
        result = validate_sql("DROP TABLE users")
        assert result.ok is False

    def test_block_alter_table(self):
        result = validate_sql("ALTER TABLE users ADD COLUMN pwned text")
        assert result.ok is False

    def test_block_insert(self):
        result = validate_sql("INSERT INTO users (name) VALUES ('attacker')")
        assert result.ok is False

    def test_block_update(self):
        result = validate_sql("UPDATE users SET role = 'admin' WHERE id = 1")
        assert result.ok is False

    def test_block_delete(self):
        result = validate_sql("DELETE FROM users WHERE id = 1")
        assert result.ok is False

    def test_block_truncate(self):
        result = validate_sql("TRUNCATE TABLE users")
        assert result.ok is False

    # ── Statement stacking detection ──

    def test_block_stacked_statements(self):
        result = validate_sql("SELECT 1; DROP TABLE users")
        assert result.ok is False
        assert "stacking" in result.blocked_reason.lower()

    def test_block_stacked_with_space(self):
        result = validate_sql("SELECT 1;  SELECT 2")
        assert result.ok is False

    def test_allow_trailing_semicolon(self):
        """A single trailing semicolon is allowed."""
        result = validate_sql("SELECT * FROM users;")
        assert result.ok is True

    def test_block_comment_bypass_attempt(self):
        """Statement stacking via SQL comments should be caught."""
        result = validate_sql("SELECT 1; --comment\nDROP TABLE users")
        assert result.ok is False

    def test_block_block_comment_bypass(self):
        """Statement stacking via block comments should be caught."""
        result = validate_sql("SELECT 1;/**/DROP TABLE users")
        assert result.ok is False

    # ── Blocked tables ──

    def test_blocked_table(self):
        result = validate_sql(
            "SELECT * FROM internal_credentials",
            blocked_tables=["internal_credentials"],
        )
        assert result.ok is False
        assert "blocked by policy" in result.blocked_reason.lower()

    def test_blocked_table_case_insensitive(self):
        result = validate_sql(
            "SELECT * FROM Internal_Credentials",
            blocked_tables=["internal_credentials"],
        )
        assert result.ok is False

    def test_non_blocked_table_passes(self):
        result = validate_sql(
            "SELECT * FROM users",
            blocked_tables=["internal_credentials"],
        )
        assert result.ok is True

    def test_blocked_table_in_join(self):
        result = validate_sql(
            "SELECT u.* FROM users u JOIN secrets s ON u.id = s.user_id",
            blocked_tables=["secrets"],
        )
        assert result.ok is False

    # ── Edge cases ──

    def test_empty_query(self):
        result = validate_sql("")
        assert result.ok is False

    def test_whitespace_only(self):
        result = validate_sql("   \n\t  ")
        assert result.ok is False

    def test_query_too_long(self):
        result = validate_sql("SELECT " + "x" * 100_001)
        assert result.ok is False
        assert "maximum length" in result.blocked_reason.lower()

    def test_invalid_sql(self):
        result = validate_sql("NOT VALID SQL AT ALL !@#$")
        assert result.ok is False

    def test_null_byte_injection(self):
        """Null bytes should be rejected to prevent stacking bypass (HIGH-04)."""
        result = validate_sql("SELECT 1\x00DROP TABLE users")
        assert result.ok is False
        assert "null" in result.blocked_reason.lower()

    # ── Column extraction ──

    def test_extracts_columns(self):
        result = validate_sql("SELECT id, email, name FROM users WHERE active = true")
        assert result.ok is True
        assert "id" in result.columns
        assert "email" in result.columns


class TestInjectLimit:
    """Tests for inject_limit() — the LIMIT injection/clamping engine."""

    def test_adds_limit_to_unlimited_query(self):
        result = inject_limit("SELECT * FROM users", max_rows=100)
        assert "100" in result
        assert "limit" in result.lower()

    def test_clamps_existing_high_limit(self):
        result = inject_limit("SELECT * FROM users LIMIT 999999", max_rows=1000)
        assert "999999" not in result

    def test_preserves_existing_low_limit(self):
        result = inject_limit("SELECT * FROM users LIMIT 10", max_rows=1000)
        assert "10" in result

    def test_strips_trailing_semicolon(self):
        result = inject_limit("SELECT * FROM users;", max_rows=100)
        assert result.endswith("100") or "LIMIT" in result.upper()

    def test_handles_subquery(self):
        sql = "SELECT * FROM (SELECT id FROM users) sub"
        result = inject_limit(sql, max_rows=50)
        assert "50" in result

    def test_default_limit(self):
        result = inject_limit("SELECT * FROM users")
        assert "10000" in result

    def test_cte_query_limit(self):
        sql = "WITH cte AS (SELECT * FROM users) SELECT * FROM cte"
        result = inject_limit(sql, max_rows=500)
        assert "500" in result


class TestCommentStripping:
    """Tests for SQL comment removal (security-critical for stacking detection)."""

    def test_single_line_comment_stripped(self):
        result = validate_sql("SELECT * FROM users -- this is a comment")
        assert result.ok is True

    def test_multiline_comment_stripped(self):
        result = validate_sql("SELECT /* comment */ * FROM users")
        assert result.ok is True

    def test_stacking_hidden_in_single_line_comment(self):
        """Stacking attempt where the malicious statement is after a comment line."""
        result = validate_sql("SELECT 1;\n-- harmless\nDROP TABLE x")
        assert result.ok is False

    def test_stacking_hidden_in_block_comment(self):
        result = validate_sql("SELECT 1;/* bypass */DROP TABLE x")
        assert result.ok is False
