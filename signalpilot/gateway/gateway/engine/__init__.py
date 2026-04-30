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

# ---------------------------------------------------------------------------
# Dangerous function denylist — per-dialect functions that can read files,
# make network requests, execute OS commands, or modify data even inside a
# SELECT statement.  This is the second layer of defence after the
# statement-type check.
# ---------------------------------------------------------------------------

_DANGEROUS_FUNCTIONS: dict[str, frozenset[str]] = {
    "postgres": frozenset({
        # File-system read/write
        "pg_read_server_files", "pg_read_binary_file", "pg_read_file",
        "pg_ls_dir", "pg_ls_logdir", "pg_ls_waldir", "pg_ls_tmpdir",
        "pg_ls_archive_statusdir",
        "pg_file_write", "pg_file_rename", "pg_file_unlink",
        # Large-object smuggling
        "lo_import", "lo_export", "lo_from_bytea", "lo_put",
        # dblink — remote/out-of-band connections
        "dblink", "dblink_exec", "dblink_connect", "dblink_send_query",
        "dblink_get_result", "dblink_get_connections",
        # OS command execution
        "pg_execute_server_program",
        # Internal COPY helper
        "copy_file_internal",
        # Server management / DoS
        "pg_logfile_rotate",
        "pg_reload_conf", "pg_rotate_logfile",
        "pg_terminate_backend", "pg_cancel_backend",
        # Advisory locks (DoS vector)
        "pg_advisory_lock", "pg_advisory_xact_lock",
        # Configuration mutation
        "set_config",
    }),
    "clickhouse": frozenset({
        # Table functions that access external resources
        "file", "url", "s3", "s3cluster", "mysql", "postgresql",
        "remotesecure", "remote", "hdfs", "jdbc", "mongo", "redis",
        "sqlite", "odbc", "input", "generaterandom",
        "executable", "azureblobstorage", "deltalake", "hudi", "iceberg",
    }),
    "bigquery": frozenset({
        "external_query",
    }),
    "snowflake": frozenset({
        "system$execute_program", "system$stream_get",
        "system$pipe_force_resume", "system$cancel_all_queries",
    }),
    "mysql": frozenset({
        "load_file", "sys_exec", "sys_eval",
    }),
    "duckdb": frozenset({
        # File-system access
        "read_csv", "read_csv_auto", "read_parquet", "read_json", "read_json_auto",
        "read_blob", "read_text",
        # Network access
        "httpfs_get", "http_get", "http_post",
        # Cross-engine scanning
        "postgres_scan", "sqlite_scan", "mysql_scan",
        "iceberg_scan", "delta_scan",
        # Extension loading
        "load_extension", "install_extension",
    }),
    "sqlite": frozenset({
        "load_extension", "readfile", "writefile",
        "edit", "zipfile", "sqlar",
    }),
}

# Functions blocked regardless of dialect
_UNIVERSAL_BLOCKED_FUNCTIONS: frozenset[str] = frozenset({
    "load_extension", "install_extension",
})


def _check_dangerous_functions(parsed: "exp.Expression", dialect: str) -> str | None:
    """Walk AST and reject queries containing dangerous functions.

    Returns a blocked_reason string if a dangerous function is found, or None
    if the query is safe.
    """
    # Normalize dialect name
    dialect_key = dialect.lower().replace("postgresql", "postgres")
    blocked_names = _DANGEROUS_FUNCTIONS.get(dialect_key, frozenset())
    all_blocked = blocked_names | _UNIVERSAL_BLOCKED_FUNCTIONS

    if not all_blocked:
        return None

    for node in parsed.walk():
        # Check function calls (both named functions and anonymous/dialect-specific)
        if isinstance(node, (exp.Anonymous, exp.Func)):
            func_name = ""
            if hasattr(node, "name"):
                func_name = node.name
            elif hasattr(node, "this") and isinstance(node.this, str):
                func_name = node.this
            # sqlglot may also store the SQL name on .sql_name()
            if not func_name and hasattr(node, "sql_name"):
                try:
                    func_name = node.sql_name()
                except Exception:
                    pass
            func_name_lower = func_name.lower().strip()
            if func_name_lower in all_blocked:
                return (
                    f"Blocked: function '{func_name}' is not permitted "
                    f"in governed read-only mode"
                )
        # Check table-valued functions (e.g. FROM url(...), FROM read_csv(...))
        if isinstance(node, exp.Table):
            table_name = ""
            if hasattr(node, "name"):
                table_name = node.name
            table_name_lower = (table_name or "").lower().strip()
            if table_name_lower in all_blocked:
                return (
                    f"Blocked: table function '{table_name}' is not permitted "
                    f"in governed read-only mode"
                )

    return None


def _check_into_clause(parsed: "exp.Expression") -> str | None:
    """Reject SELECT ... INTO OUTFILE/DUMPFILE (data exfiltration in MySQL/MariaDB)."""
    for node in parsed.walk():
        if isinstance(node, exp.Into):
            return "Blocked: SELECT INTO is not permitted in governed read-only mode"
    return None

# Statement stacking detection — strip SQL comments first, then check (HIGH-04 fix)
_SINGLE_LINE_COMMENT = re.compile(r"--[^\n]*")
_MULTI_LINE_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_STACKING_PATTERN = re.compile(r";\s*\w", re.IGNORECASE)


def _strip_sql_comments(sql: str) -> str:
    """Remove SQL comments to prevent stacking detection bypass."""
    result = _MULTI_LINE_COMMENT.sub(" ", sql)
    result = _SINGLE_LINE_COMMENT.sub(" ", result)
    return result


# Strip string literals to prevent false positives in regex-based checks
# (e.g. semicolons inside 'hello;world' should not trigger stacking detection).
_STRING_LITERAL = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"", re.DOTALL)


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
        raise ValueError(
            f"SQL passed validation but could not be parsed for LIMIT injection: {exc}"
        ) from exc

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
