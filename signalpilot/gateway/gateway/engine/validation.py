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


# sqlglot underlines the offending token with ANSI escapes in str(ParseError).
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_PARSE_ERROR_CAP = 300


def _strip_ansi(text: str) -> str:
    return _ANSI_ESCAPE.sub("", text)


def _parse_error_reason(exc: Exception, dialect: str) -> str:
    """Build a bounded, plain-text reason from a sqlglot parse failure.

    Uses the structured ``errors`` list on ``sqlglot.errors.ParseError`` so the
    message names the dialect, the offending token and its position. Falls back
    to the exception text (ANSI stripped) for any other exception type.
    """
    entries = getattr(exc, "errors", None)
    first = entries[0] if isinstance(entries, list) and entries and isinstance(entries[0], dict) else None
    if first is not None:
        description = _strip_ansi(str(first.get("description") or "")).strip() or "could not parse"
        highlight = _strip_ansi(str(first.get("highlight") or "")).strip()
        line = first.get("line")
        col = first.get("col")
        parts = [f"SQL parse error ({dialect}):"]
        if highlight:
            parts.append(f"unexpected '{highlight}'")
        if isinstance(line, int) and isinstance(col, int):
            parts.append(f"at line {line} col {col}")
        head = " ".join(parts)
        message = f"{head}: {description}" if len(parts) > 1 else f"{head} {description}"
    else:
        detail = " ".join(_strip_ansi(str(exc)).split()) or type(exc).__name__
        message = f"SQL parse error ({dialect}): {detail}"
    if len(message) > _PARSE_ERROR_CAP:
        message = message[: _PARSE_ERROR_CAP - 3] + "..."
    return message


@dataclass
class ValidationResult:
    ok: bool
    tables: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    blocked_reason: str | None = None


def validate_sql(
    sql: str,
    blocked_tables: list[str] | None = None,
    *,
    dialect: str,
) -> ValidationResult:
    """Validate a read-only query in the connection's sqlglot ``dialect``.

    ``dialect`` is keyword-only and required: callers must derive it from the
    connection (``gateway.engine.dialects.sqlglot_dialect``) so T-SQL, BigQuery
    and friends are never parsed with Postgres grammar by accident.
    """
    if not isinstance(dialect, str) or not dialect.strip():
        raise ValueError("validate_sql requires a non-empty sqlglot dialect")
    dialect = dialect.strip().lower()
    # Unknown dialect names are not rejected here: sqlglot raises for them and
    # the parse-error branch below fails closed (SP-SEC-011 contract).
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
        return ValidationResult(ok=False, blocked_reason=_parse_error_reason(e, dialect))

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

    # ── Data-modifying CTE / subquery check (SP-09) ──
    # `WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x` parses as a
    # top-level Select, so the statement-type check above does not see the DML.
    modifying_reason = _check_nested_modifications(stmt)
    if modifying_reason:
        return ValidationResult(ok=False, blocked_reason=modifying_reason)

    table_nodes = [t for t in stmt.find_all(exp.Table) if t.name]
    tables = [t.name.lower() for t in table_nodes]
    columns = [c.name.lower() for c in stmt.find_all(exp.Column) if c.name]

    if blocked_tables:
        blocked_lower = {t.lower().strip() for t in blocked_tables if t and t.strip()}
        for node in table_nodes:
            hit = _blocked_policy_match(node, blocked_lower)
            if hit:
                return ValidationResult(
                    ok=False,
                    blocked_reason=f"Table '{hit}' is blocked by policy",
                    tables=tables,
                    columns=columns,
                )

    return ValidationResult(ok=True, tables=tables, columns=columns)


_MODIFYING_NODE_TYPES: tuple[type, ...] = (exp.Insert, exp.Update, exp.Delete, exp.Merge) if HAS_SQLGLOT else ()


def _check_nested_modifications(stmt: exp.Expression) -> str | None:
    """Reject INSERT/UPDATE/DELETE/MERGE nodes nested inside a SELECT statement.

    Data-modifying CTEs (Postgres ``WITH x AS (DELETE ... RETURNING *)``) and
    similar constructs are DML wearing a SELECT wrapper.
    """
    for node in stmt.walk():
        if isinstance(node, _MODIFYING_NODE_TYPES):
            kind = type(node).__name__.upper()
            return f"Blocked: {kind} inside a SELECT (data-modifying CTE or subquery) is not allowed in read-only mode"
    return None


def _table_qualified_forms(table: exp.Table) -> list[str]:
    """Return the lowercased name forms a policy entry can match for a table.

    ``cat.private.my_secrets`` yields ``my_secrets``, ``private.my_secrets`` and
    ``cat.private.my_secrets``; an unqualified table yields only its basename.
    """
    name = (table.name or "").lower()
    db = (getattr(table, "db", "") or "").lower()
    catalog = (getattr(table, "catalog", "") or "").lower()
    forms = [name]
    if db:
        forms.append(f"{db}.{name}")
        if catalog:
            forms.append(f"{catalog}.{db}.{name}")
    return forms


def _blocked_policy_match(table: exp.Table, blocked_lower: set[str]) -> str | None:
    """Return the matching policy entry if ``table`` is blocked, else None.

    An unqualified policy entry (``my_secrets``) blocks that basename in any
    schema. A qualified entry (``private.my_secrets`` / ``cat.private.my_secrets``)
    blocks only when the table's schema (and catalog) parts match. Comparison is
    lowercased and unquoted on both sides.
    """
    for form in _table_qualified_forms(table):
        if form in blocked_lower:
            return form
    return None


__all__ = ["ValidationResult", "validate_sql"]
