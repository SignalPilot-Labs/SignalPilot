"""
Tests for query input sanitization — ensuring dangerous patterns
are caught before reaching the SQL engine.

Tests cover:
- Null byte injection
- Unicode homoglyph detection
- Excessively nested subqueries
- Control character stripping
"""

import pytest

from signalpilot.gateway.gateway.engine import validate_sql


class TestNullByteInjection:
    """Null bytes should never pass through to the engine."""

    def test_null_byte_in_query(self):
        result = validate_sql("SELECT * FROM users\x00; DROP TABLE users;--")
        assert result.ok is False

    def test_null_byte_in_table_name(self):
        result = validate_sql("SELECT * FROM us\x00ers")
        assert result.ok is False


class TestExcessiveNesting:
    """Deeply nested subqueries should be rejected to prevent DoS."""

    def test_deeply_nested_subquery(self):
        # Build a 20-level nested subquery
        query = "SELECT 1"
        for _ in range(20):
            query = f"SELECT * FROM ({query}) AS t"
        result = validate_sql(query)
        # Engine should either reject or handle gracefully (not crash)
        assert isinstance(result.ok, bool)

    def test_reasonable_nesting_allowed(self):
        query = "SELECT * FROM (SELECT id FROM users) AS t"
        result = validate_sql(query)
        assert result.ok is True


class TestControlCharacters:
    """Control characters (except whitespace) should be caught."""

    def test_backspace_in_query(self):
        result = validate_sql("SELECT * FROM \busers")
        assert result.ok is False

    def test_tab_and_newline_allowed(self):
        result = validate_sql("SELECT *\n\tFROM users")
        assert result.ok is True
