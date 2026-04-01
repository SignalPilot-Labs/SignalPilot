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

import sqlglot
import sqlglot.expressions as exp

# DDL/DML statement types that must be blocked
_BLOCKED_STATEMENT_TYPES = {
    "Create", "Drop", "Alter", "Insert", "Update", "Delete", "Truncate",
    "Merge", "Grant", "Revoke", "Comment", "Rename", "Replace",
    "Command",  # catches COPY, VACUUM, etc.
}

# Statement stacking detection (simple regex for belt-and-suspenders)
_STACKING_PATTERN = re.compile(r";\s*\w", re.IGNORECASE)


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

    if "\x00" in sql:
        return ValidationResult(ok=False, blocked_reason="Null bytes are not allowed in SQL")

    if len(sql) > 100_000:
        return ValidationResult(ok=False, blocked_reason="Query exceeds maximum length (100KB)")

    if _STACKING_PATTERN.search(sql.rstrip(";")):
        return ValidationResult(
            ok=False,
            blocked_reason="Statement stacking detected (multiple statements separated by ';')",
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

    try:
        parsed = sqlglot.parse_one(sql, dialect=dialect)
    except Exception:
        return f"{sql} LIMIT {max_rows}"

    if parsed is None:
        return sql

    existing_limit = parsed.args.get("limit")
    if existing_limit:
        limit_expr = existing_limit.expression
        if limit_expr is not None:
            try:
                current = int(limit_expr.this)
                if current > max_rows:
                    limit_expr.set("this", str(max_rows))
            except (ValueError, TypeError):
                pass
    else:
        parsed.set("limit", exp.Limit(expression=exp.Literal.number(max_rows)))

    return parsed.sql(dialect=dialect)
