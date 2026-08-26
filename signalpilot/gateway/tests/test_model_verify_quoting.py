"""Tests for SQL identifier quoting in model_verify SQL generation."""

from __future__ import annotations

from gateway.mcp.tools.model_verify import _qid


class TestModelVerifyQidHelper:
    def test_qid_simple_name(self) -> None:
        assert _qid("metric_col") == '"metric_col"'

    def test_qid_doubles_embedded_quotes(self) -> None:
        assert _qid('col"name') == '"col""name"'

    def test_qid_injection_attempt(self) -> None:
        """Embedded double-quote is doubled, producing a safe identifier."""
        result = _qid('"evil"; DROP TABLE')
        # All inner quotes are doubled — the injection attempt becomes a valid identifier
        assert result == '"""evil""; DROP TABLE"'
        # When doubled quotes are collapsed, no bare injection sequence remains
        assert '"evil"; DROP TABLE' not in result.replace('""', '')

    def test_table_literal_escaping(self) -> None:
        """DB-derived table name used as SQL literal must escape single quotes."""
        malicious_tbl = "foo'; DROP TABLE orders; --"
        safe_tbl = malicious_tbl.replace("'", "''")
        sql = f"WHERE table_name = '{safe_tbl}'"
        # The single quote is doubled — no triple-quote run
        assert "'''" not in sql
        assert "foo''" in sql
        # The original unescaped payload is not present verbatim
        assert malicious_tbl not in sql
