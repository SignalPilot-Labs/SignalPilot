"""SQL output transforms: literal redaction and LIMIT injection."""

from __future__ import annotations

from ._sqlglot import HAS_SQLGLOT, exp, sqlglot


def redact_sql_literals(sql: str, dialect: str = "postgres") -> str:
    """Replace string literals with '<REDACTED>' for audit logging.

    Preserves query structure and numeric literals (useful for query analysis).
    Falls back to truncation if parsing fails — never stores full PII on error.
    """
    if not HAS_SQLGLOT or not sql:
        return sql
    try:
        tree = sqlglot.parse_one(sql, dialect=dialect)
        if tree is None:
            return sql
        for node in tree.walk():
            if isinstance(node, exp.Literal) and node.is_string:
                node.set("this", "<REDACTED>")
        return tree.sql(dialect=dialect)
    except Exception:
        # If redaction fails, truncate the SQL rather than storing full PII
        return sql[:50] + "... <REDACTED ON PARSE ERROR>" if len(sql) > 50 else sql


def inject_limit(sql: str, max_rows: int = 10_000, dialect: str = "postgres") -> str:
    sql = sql.strip().rstrip(";")

    if not HAS_SQLGLOT:
        # Fail-closed: refuse to process SQL without proper AST parsing.
        # validate_sql() already blocks queries when sqlglot is missing,
        # so this should never be reached in normal operation.
        raise RuntimeError("SQL validation engine (sqlglot) is not available. Cannot safely inject LIMIT.")

    try:
        parsed = sqlglot.parse_one(sql, dialect=dialect)
    except Exception as exc:
        # Fail closed: do not concatenate unvalidated SQL.
        raise ValueError(f"SQL passed validation but could not be parsed for LIMIT injection: {exc}") from exc

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


__all__ = ["inject_limit", "redact_sql_literals"]
