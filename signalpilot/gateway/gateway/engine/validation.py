"""SQL validation: ValidationResult dataclass and validate_sql function."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ._sqlglot import HAS_SQLGLOT, exp, sqlglot
from .denylists import (
    _BLOCKED_STATEMENT_TYPES,
    _check_dangerous_functions,
    _check_into_clause,
)

# Statement stacking detection — strip SQL comments first, then check (HIGH-04 fix)
_SINGLE_LINE_COMMENT = re.compile(r"--[^\n]*")
_MULTI_LINE_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_STACKING_PATTERN = re.compile(r";\s*\w", re.IGNORECASE)

# Strip string literals to prevent false positives in regex-based checks
# (e.g. semicolons inside 'hello;world' should not trigger stacking detection).
_STRING_LITERAL = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"", re.DOTALL)


def _strip_sql_comments(sql: str) -> str:
    """Remove SQL comments to prevent stacking detection bypass."""
    result = _MULTI_LINE_COMMENT.sub(" ", sql)
    return _SINGLE_LINE_COMMENT.sub(" ", result)


def _strip_sql_literals(sql: str) -> str:
    """Replace string literals with empty placeholder to prevent false positives in regex checks."""
    return _STRING_LITERAL.sub("''", sql)


@dataclass
class ValidationResult:
    ok: bool
    tables: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    blocked_reason: str | None = None


def validate_sql(
    sql: str,
    blocked_tables: list[str] | None = None,
    dialect: str = "postgres",
) -> ValidationResult:
    sql = sql.strip()
    if not sql:
        return ValidationResult(ok=False, blocked_reason="Empty query")

    # Strip null bytes which could bypass stacking detection (HIGH-04 defense)
    if "\x00" in sql:
        return ValidationResult(ok=False, blocked_reason="Null bytes are not allowed in SQL queries")

    # Input length limit (MED-07)
    if len(sql) > 100_000:
        return ValidationResult(ok=False, blocked_reason="Query exceeds maximum length (100KB)")

    # Strip comments and string literals before stacking check (HIGH-04 fix + Issue #20)
    stripped = _strip_sql_comments(sql)
    stripped = _strip_sql_literals(stripped)
    if _STACKING_PATTERN.search(stripped.rstrip(";")):
        return ValidationResult(
            ok=False,
            blocked_reason="Statement stacking detected (multiple statements separated by ';')",
        )

    # Fail-closed: if sqlglot is not installed, block all queries (HIGH-03 fix)
    if not HAS_SQLGLOT:
        return ValidationResult(
            ok=False,
            blocked_reason="SQL validation engine (sqlglot) is not available. Cannot safely execute queries.",
        )

    try:
        statements = sqlglot.parse(sql, dialect=dialect)
    except Exception as e:
        return ValidationResult(ok=False, blocked_reason=f"SQL parse error: {str(e)[:100]}")

    if len(statements) > 1:
        return ValidationResult(
            ok=False,
            blocked_reason=f"Multiple statements ({len(statements)}) — only single SELECT allowed",
        )

    stmt = statements[0]
    if stmt is None:
        return ValidationResult(ok=False, blocked_reason="Could not parse SQL")

    stmt_type = type(stmt).__name__
    if stmt_type in _BLOCKED_STATEMENT_TYPES:
        return ValidationResult(
            ok=False,
            blocked_reason=f"Blocked: {stmt_type} statements are not allowed (read-only mode)",
        )

    if stmt_type not in ("Select", "With", "Union", "Intersect", "Except", "Subquery"):
        return ValidationResult(
            ok=False,
            blocked_reason=f"Blocked: only SELECT queries are allowed (got {stmt_type})",
        )

    # ── Dangerous function denylist (Issue #19) ──
    dangerous_reason = _check_dangerous_functions(stmt, dialect)
    if dangerous_reason:
        return ValidationResult(ok=False, blocked_reason=dangerous_reason)

    # ── SELECT INTO exfiltration check ──
    into_reason = _check_into_clause(stmt)
    if into_reason:
        return ValidationResult(ok=False, blocked_reason=into_reason)

    tables = [t.name.lower() for t in stmt.find_all(exp.Table) if t.name]
    columns = [c.name.lower() for c in stmt.find_all(exp.Column) if c.name]

    if blocked_tables:
        blocked_lower = {t.lower() for t in blocked_tables}
        for table in tables:
            if table in blocked_lower:
                return ValidationResult(
                    ok=False,
                    blocked_reason=f"Table '{table}' is blocked by policy",
                    tables=tables,
                    columns=columns,
                )

    return ValidationResult(ok=True, tables=tables, columns=columns)


__all__ = ["ValidationResult", "validate_sql"]
