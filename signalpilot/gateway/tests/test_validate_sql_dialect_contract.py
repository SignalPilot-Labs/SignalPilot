"""Contract tests for validate_sql dialect handling and parse-error text.

Covers plan section G: parse errors name the dialect and the offending token,
ANSI underlines never leak, messages are capped, ``dialect`` is required, and
no production caller under api/, mcp/ or governance/ omits it.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest

from gateway.engine import validate_sql
from gateway.engine.dialects import sqlglot_dialect
from gateway.engine.validation import _PARSE_ERROR_CAP

GATEWAY_DIR = Path(__file__).resolve().parents[1] / "gateway"
# A call site: not an attribute (`mcp._validate_sql(`), not a definition
# (`def validate_sql(` is the MCP tool of the same name).
_CALL_RE = re.compile(r"(?<![\w.])(?<!def )validate_sql\(")

TSQL_CASES = [
    ("top", "SELECT TOP 5 * FROM t", "5"),
    ("top_in_cte", "WITH c AS (SELECT TOP 3 id FROM t) SELECT * FROM c", "3"),
    ("convert_style_23", "SELECT CONVERT(varchar(10), created_at, 23) FROM t", ")"),
]


def _calls_without_dialect(path: Path) -> list[tuple[int, str]]:
    """Return (line, snippet) for every validate_sql( call lacking dialect=."""
    text = path.read_text(encoding="utf-8")
    found: list[tuple[int, str]] = []
    for match in _CALL_RE.finditer(text):
        start = match.end()
        depth = 1
        idx = start
        while idx < len(text) and depth:
            char = text[idx]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            idx += 1
        args = text[start : idx - 1]
        if "dialect=" not in args:
            line = text.count("\n", 0, match.start()) + 1
            found.append((line, " ".join(args.split())[:80]))
    return found


class TestCallerContract:
    def test_every_api_mcp_governance_caller_passes_dialect(self):
        offenders: list[str] = []
        for package in ("api", "mcp", "governance"):
            for path in (GATEWAY_DIR / package).rglob("*.py"):
                for line, snippet in _calls_without_dialect(path):
                    offenders.append(f"{path.relative_to(GATEWAY_DIR)}:{line}: validate_sql({snippet})")
        assert not offenders, "validate_sql called without dialect=:\n" + "\n".join(offenders)

    def test_dialect_is_required_keyword(self):
        with pytest.raises(TypeError):
            validate_sql("SELECT 1")  # type: ignore[call-arg]
        with pytest.raises(TypeError):
            validate_sql("SELECT 1", None, "postgres")  # type: ignore[misc]

    def test_empty_dialect_is_a_programming_error(self):
        with pytest.raises(ValueError):
            validate_sql("SELECT 1", dialect="")

    def test_unknown_dialect_fails_closed_with_named_dialect(self):
        # SP-SEC-011: a name sqlglot does not know must block, never raise.
        result = validate_sql("SELECT 1", dialect="not-a-dialect")
        assert not result.ok
        assert (result.blocked_reason or "").startswith("SQL parse error (not-a-dialect)")


class TestDialectFallback:
    def test_known_types_map_silently(self, caplog):
        with caplog.at_level(logging.WARNING, logger="gateway.engine.dialects"):
            assert sqlglot_dialect("mssql") == "tsql"
            assert sqlglot_dialect("xata") == "postgres"
        assert not caplog.records

    def test_unknown_type_warns_and_falls_back(self, caplog):
        with caplog.at_level(logging.WARNING, logger="gateway.engine.dialects"):
            assert sqlglot_dialect("oracle") == "postgres"
            assert sqlglot_dialect(None) == "postgres"
        messages = [record.getMessage() for record in caplog.records]
        assert any("'oracle'" in message and "postgres" in message for message in messages)
        assert any("None" in message for message in messages)


class TestParseErrorText:
    @pytest.mark.parametrize(("name", "sql", "token"), TSQL_CASES, ids=[c[0] for c in TSQL_CASES])
    def test_tsql_parsed_as_postgres_names_dialect_and_token(self, name, sql, token):
        result = validate_sql(sql, dialect="postgres")
        assert not result.ok
        reason = result.blocked_reason or ""
        assert reason.startswith("SQL parse error (postgres): unexpected '" + token + "' at line 1 col ")
        assert "\x1b" not in reason
        assert "Traceback" not in reason

    @pytest.mark.parametrize(("name", "sql", "token"), TSQL_CASES, ids=[c[0] for c in TSQL_CASES])
    def test_tsql_cases_pass_in_tsql(self, name, sql, token):
        assert validate_sql(sql, dialect=sqlglot_dialect("mssql")).ok

    def test_parse_error_is_capped(self):
        sql = "SELECT " + "@" * 5000
        result = validate_sql(sql, dialect="postgres")
        assert not result.ok
        assert result.blocked_reason is not None
        assert result.blocked_reason.startswith("SQL parse error (postgres)")
        assert len(result.blocked_reason) <= _PARSE_ERROR_CAP
        assert "\x1b" not in result.blocked_reason
