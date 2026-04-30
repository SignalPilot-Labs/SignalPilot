"""Tests for MCP server input validation helpers."""

import pytest

from signalpilot.gateway.gateway.mcp_server import (
    _validate_connection_name,
    _validate_sql,
    _CONN_NAME_RE,
    _MAX_SQL_LENGTH,
    _MAX_CODE_LENGTH,
)


class TestConnectionNameValidation:
    """Tests for _validate_connection_name()."""

    def test_valid_simple_name(self):
        assert _validate_connection_name("mydb") is None

    def test_valid_with_hyphens(self):
        assert _validate_connection_name("my-database") is None

    def test_valid_with_underscores(self):
        assert _validate_connection_name("prod_analytics") is None

    def test_valid_with_numbers(self):
        assert _validate_connection_name("db123") is None

    def test_valid_mixed(self):
        assert _validate_connection_name("My_DB-v2") is None

    def test_empty_name(self):
        result = _validate_connection_name("")
        assert result is not None
        assert "Invalid" in result

    def test_too_long(self):
        result = _validate_connection_name("a" * 65)
        assert result is not None

    def test_max_length_ok(self):
        assert _validate_connection_name("a" * 64) is None

    def test_spaces_rejected(self):
        result = _validate_connection_name("my db")
        assert result is not None

    def test_special_chars_rejected(self):
        for char in ["@", "#", "$", "!", " ", "/", "\\", ".", ";"]:
            result = _validate_connection_name(f"name{char}test")
            assert result is not None, f"Should reject '{char}'"

    def test_sql_injection_attempt(self):
        result = _validate_connection_name("'; DROP TABLE users; --")
        assert result is not None

    def test_path_traversal_attempt(self):
        result = _validate_connection_name("../../../etc/passwd")
        assert result is not None


class TestSQLValidation:
    """Tests for _validate_sql()."""

    def test_valid_sql(self):
        assert _validate_sql("SELECT * FROM users") is None

    def test_empty_sql(self):
        result = _validate_sql("")
        assert result is not None
        assert "empty" in result.lower()

    def test_whitespace_only(self):
        result = _validate_sql("   ")
        assert result is not None

    def test_too_long(self):
        result = _validate_sql("SELECT " + "x" * (_MAX_SQL_LENGTH + 1))
        assert result is not None
        assert "length" in result.lower() or "100" in result

    def test_at_max_length(self):
        # Should be valid at exactly max length
        sql = "SELECT " + "x" * (_MAX_SQL_LENGTH - 7)
        assert _validate_sql(sql) is None


class TestRegexPattern:
    """Tests for the connection name regex pattern."""

    def test_pattern_matches_valid(self):
        assert _CONN_NAME_RE.match("test")
        assert _CONN_NAME_RE.match("a")
        assert _CONN_NAME_RE.match("A-b_C-123")

    def test_pattern_rejects_invalid(self):
        assert not _CONN_NAME_RE.match("")
        assert not _CONN_NAME_RE.match("a" * 65)
        assert not _CONN_NAME_RE.match("has space")


class TestConstants:
    """Tests for validation constants."""

    def test_max_sql_length(self):
        assert _MAX_SQL_LENGTH == 100_000

    def test_max_code_length(self):
        assert _MAX_CODE_LENGTH == 1_000_000
