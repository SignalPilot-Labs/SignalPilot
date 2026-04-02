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
        result = validate_sql(
            "SELECT u.name, o.total FROM users u JOIN orders o ON u.id = o.user_id"
        )
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

    # ─── Null byte injection (HIGH-04) ─────────────────────────────
    def test_null_byte_rejected(self):
        result = validate_sql("SELECT 1\x00; DROP TABLE users")
        assert not result.ok
        assert "Null bytes" in (result.blocked_reason or "")

    def test_null_byte_mid_query_rejected(self):
        result = validate_sql("SELECT \x00* FROM users")
        assert not result.ok

    # ─── Comment injection (HIGH-04) ─────────────────────────────
    def test_block_comment_hiding_stacking(self):
        result = validate_sql("SELECT 1; /* hidden */ INSERT INTO users VALUES (1)")
        assert not result.ok

    def test_nested_block_comments(self):
        result = validate_sql("SELECT 1 /* outer /* inner */ ; DROP TABLE users */")
        assert not result.ok

    def test_line_comment_hiding_stacking(self):
        result = validate_sql("SELECT 1 -- safe\n; DELETE FROM users")
        assert not result.ok

    def test_comment_only_no_stacking_allowed(self):
        result = validate_sql("SELECT /* comment */ 1")
        assert result.ok

    # ─── Unicode / encoding tricks ──────────────────────────────
    def test_unicode_fullwidth_semicolon(self):
        """Fullwidth semicolon (U+FF1B) should not bypass stacking detection."""
        # sqlglot won't parse this as a separator, so it should either be
        # a valid single statement or a parse error — not two statements
        result = validate_sql("SELECT 1\uff1b DROP TABLE users")
        # Should not be ok — either parse error or blocked
        # The key thing: it must NOT succeed as two statements
        if result.ok:
            assert "users" not in [t.lower() for t in result.tables]

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
