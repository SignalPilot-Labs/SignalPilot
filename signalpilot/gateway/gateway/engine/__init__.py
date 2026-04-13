"""
SQL Query Engine — the gatekeeper between AI agents and databases.

Pipeline:
1. Parse SQL to AST (sqlglot)
2. Validate: read-only, no stacking, no blocked tables
3. Inject LIMIT if missing
4. Execute with timeout
5. Return governed result
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

try:
    import sqlglot
    import sqlglot.expressions as exp

    HAS_SQLGLOT = True
except ImportError:
    HAS_SQLGLOT = False
    import warnings
    warnings.warn(
        "sqlglot is not installed — SQL validation is DISABLED. "
        "Install it with: pip install sqlglot>=25.0.0",
        RuntimeWarning,
        stacklevel=2,
    )

# DDL/DML statement types that must be blocked
_BLOCKED_STATEMENT_TYPES = {
    "Create", "Drop", "Alter", "Insert", "Update", "Delete", "Truncate",
    "Merge", "Grant", "Revoke", "Comment", "Rename", "Replace",
    "Command",  # catches COPY, VACUUM, etc.
}

# Statement stacking detection — strip SQL comments first, then check (HIGH-04 fix)
_SINGLE_LINE_COMMENT = re.compile(r"--[^\n]*")
_MULTI_LINE_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_STACKING_PATTERN = re.compile(r";\s*\w", re.IGNORECASE)


def _strip_sql_comments(sql: str) -> str:
    """Remove SQL comments to prevent stacking detection bypass."""
    result = _MULTI_LINE_COMMENT.sub(" ", sql)
    result = _SINGLE_LINE_COMMENT.sub(" ", result)
    return result


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

    # Strip comments before stacking check (HIGH-04 fix)
    stripped = _strip_sql_comments(sql)
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
        return ValidationResult(ok=False, blocked_reason=f"SQL parse error: {e}")

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


def inject_limit(sql: str, max_rows: int = 10_000, dialect: str = "postgres") -> str:
    sql = sql.strip().rstrip(";")

    if not HAS_SQLGLOT:
        # Fail-closed: refuse to process SQL without proper AST parsing.
        # validate_sql() already blocks queries when sqlglot is missing,
        # so this should never be reached in normal operation.
        raise RuntimeError("SQL validation engine (sqlglot) is not available. Cannot safely inject LIMIT.")

    try:
        parsed = sqlglot.parse_one(sql, dialect=dialect)
    except Exception:
        return f"{sql} LIMIT {max_rows}"

    if parsed is None:
        return sql

    existing_limit = parsed.args.get("limit")
    if existing_limit:
        try:
            # sqlglot stores limit value as either .this.this or .expression.this
            limit_expr = existing_limit.expression or existing_limit.this
            current = int(limit_expr.this) if limit_expr else None
            if current is not None and current > max_rows:
                parsed.set(
                    "limit",
                    exp.Limit(expression=exp.Literal.number(max_rows)),
                )
        except Exception:
            pass
    else:
        parsed.set("limit", exp.Limit(expression=exp.Literal.number(max_rows)))

    return parsed.sql(dialect=dialect)
