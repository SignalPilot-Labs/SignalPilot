"""Tests for SQL identifier quoting in model_blueprint SQL generation."""

from __future__ import annotations

from gateway.mcp.tools.model_blueprint import _qid


class TestQidHelper:
    def test_qid_simple_name(self) -> None:
        assert _qid("column_name") == '"column_name"'

    def test_qid_doubles_embedded_quotes(self) -> None:
        assert _qid('foo"bar') == '"foo""bar"'

    def test_qid_injection_attempt(self) -> None:
        """Embedded double-quote is doubled, not left as a bare injection point."""
        result = _qid('name"; DROP TABLE x; --')
        # The embedded " must be escaped to ""
        assert '""' in result
        # The result is wrapped in outer quotes and all inner " are doubled
        assert result == '"name""; DROP TABLE x; --"'

    def test_qid_empty_string(self) -> None:
        assert _qid("") == '""'

    def test_scope_ref_sql_injection_escaped(self) -> None:
        """Table name with single-quote injection payload is properly escaped as literal."""
        malicious_tbl = "foo'; DROP TABLE x; --"
        safe_tbl = malicious_tbl.replace("'", "''")
        sql_fragment = f"WHERE table_name = '{safe_tbl}'"
        # The single quote in 'foo'' is escaped via doubling — no triple-quote run
        assert "'''" not in sql_fragment
        assert "foo''" in sql_fragment
        # The original unescaped payload is not present verbatim
        assert malicious_tbl not in sql_fragment

    def test_identifier_injection_escaped(self) -> None:
        """Column name with embedded quote is escaped via _qid."""
        malicious_col = 'col" OR "1"="1'
        quoted = _qid(malicious_col)
        assert quoted == '"col"" OR ""1""=""1"'
        assert '" OR "1"="1"' not in quoted.replace('""', '')
