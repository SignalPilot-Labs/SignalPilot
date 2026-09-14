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


def _resolve_limit_value(limit_node: exp.Expression) -> int | None:
    """Return the row count of a LIMIT/FETCH/TOP node, or None when unbounded.

    None means the node does not pin a concrete row count (LIMIT ALL, a
    parameter or expression, or a PERCENT form) and must be overwritten.
    """
    if isinstance(limit_node, exp.Limit):
        count_expr = limit_node.expression or limit_node.this
    elif isinstance(limit_node, exp.Fetch):
        count_expr = limit_node.args.get("count")
        if count_expr is None:
            # FETCH FIRST ROW ONLY — implicit count of 1
            return 1
    else:
        return None

    options = limit_node.args.get("limit_options")
    if options is not None and options.args.get("percent"):
        # TOP n PERCENT / FETCH ... PERCENT — not a row count
        return None

    if isinstance(count_expr, exp.Literal) and not count_expr.is_string:
        try:
            return int(count_expr.this)
        except (TypeError, ValueError):
            return None
    return None


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

    if dialect == "tsql" and isinstance(parsed, exp.SetOperation):
        return _limit_tsql_set_operation(parsed, max_rows)

    existing_limit = parsed.args.get("limit")
    current = _resolve_limit_value(existing_limit) if existing_limit is not None else None
    # Fail closed: any limit that is missing, unresolvable (LIMIT ALL, params,
    # PERCENT forms), or above the cap is overwritten with min(current, max_rows).
    if current is None or current > max_rows:
        parsed.set("limit", exp.Limit(expression=exp.Literal.number(max_rows)))

    return parsed.sql(dialect=dialect)


def _limit_tsql_set_operation(node: exp.SetOperation, max_rows: int) -> str:
    """Cap a T-SQL UNION / EXCEPT / INTERSECT without breaking its ORDER BY.

    T-SQL has no LIMIT on a set operation, so sqlglot wraps it as a derived
    table and puts TOP on an outer select. Trailing ORDER BY, OFFSET, and
    FETCH clauses then land inside the derived table, which SQL Server
    rejects (error 1033). sqlglot attaches those clauses either to the set
    operation node or to its right-most SELECT. Lift all of them onto the
    outer select, whose SELECT * exposes the set operation's output columns
    unchanged, so ORDER BY by name or ordinal keeps its meaning.

    The cap becomes TOP, or FETCH when an OFFSET is present (T-SQL forbids
    TOP together with OFFSET). An existing FETCH within the cap is kept.
    """
    tail: exp.Expression = node
    while isinstance(tail, exp.SetOperation):
        tail = tail.expression

    def take(name: str, *, only: type[exp.Expression] | None = None) -> exp.Expression | None:
        for holder in (node, tail):
            value = holder.args.get(name)
            if value is not None and (only is None or isinstance(value, only)):
                holder.set(name, None)
                return value
        return None

    with_clause = node.args.get("with")
    if with_clause is not None:
        node.set("with", None)
    order = take("order")
    offset = take("offset")
    # A trailing FETCH belongs to the whole set operation. A TOP on the tail
    # SELECT (an exp.Limit) belongs to that branch alone and must stay there.
    fetch = take("limit", only=exp.Fetch)
    current = _resolve_limit_value(fetch) if fetch is not None else None
    cap = current if current is not None and current <= max_rows else max_rows

    outer = exp.select("*").from_(
        exp.Subquery(this=node, alias=exp.TableAlias(this=exp.to_identifier("_sp_limit")))
    )
    if with_clause is not None:
        outer.set("with", with_clause)
    if order is not None:
        outer.set("order", order)
    if offset is not None:
        outer.set("offset", offset)
    outer.set("limit", exp.Limit(expression=exp.Literal.number(cap)))
    return outer.sql(dialect="tsql")


__all__ = ["inject_limit", "redact_sql_literals"]
