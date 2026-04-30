"""Dangerous-function and statement-type denylist data + AST checker."""

from __future__ import annotations

from ._sqlglot import exp

# DDL/DML statement types that must be blocked
_BLOCKED_STATEMENT_TYPES: set[str] = {
    "Create",
    "Drop",
    "Alter",
    "Insert",
    "Update",
    "Delete",
    "Truncate",
    "Merge",
    "Grant",
    "Revoke",
    "Comment",
    "Rename",
    "Replace",
    "Command",  # catches COPY, VACUUM, etc.
}

# ---------------------------------------------------------------------------
# Dangerous function denylist — per-dialect functions that can read files,
# make network requests, execute OS commands, or modify data even inside a
# SELECT statement.  This is the second layer of defence after the
# statement-type check.
# ---------------------------------------------------------------------------

_DANGEROUS_FUNCTIONS: dict[str, frozenset[str]] = {
    "postgres": frozenset(
        {
            # File-system read/write
            "pg_read_server_files",
            "pg_read_binary_file",
            "pg_read_file",
            "pg_ls_dir",
            "pg_ls_logdir",
            "pg_ls_waldir",
            "pg_ls_tmpdir",
            "pg_ls_archive_statusdir",
            "pg_file_write",
            "pg_file_rename",
            "pg_file_unlink",
            # Large-object smuggling
            "lo_import",
            "lo_export",
            "lo_from_bytea",
            "lo_put",
            # dblink — remote/out-of-band connections
            "dblink",
            "dblink_exec",
            "dblink_connect",
            "dblink_send_query",
            "dblink_get_result",
            "dblink_get_connections",
            # OS command execution
            "pg_execute_server_program",
            # Internal COPY helper
            "copy_file_internal",
            # Server management / DoS
            "pg_logfile_rotate",
            "pg_reload_conf",
            "pg_rotate_logfile",
            "pg_terminate_backend",
            "pg_cancel_backend",
            # Advisory locks (DoS vector)
            "pg_advisory_lock",
            "pg_advisory_xact_lock",
            # Configuration mutation
            "set_config",
        }
    ),
    "clickhouse": frozenset(
        {
            # Table functions that access external resources
            "file",
            "url",
            "s3",
            "s3cluster",
            "mysql",
            "postgresql",
            "remotesecure",
            "remote",
            "hdfs",
            "jdbc",
            "mongo",
            "redis",
            "sqlite",
            "odbc",
            "input",
            "generaterandom",
            "executable",
            "azureblobstorage",
            "deltalake",
            "hudi",
            "iceberg",
        }
    ),
    "bigquery": frozenset(
        {
            "external_query",
        }
    ),
    "snowflake": frozenset(
        {
            "system$execute_program",
            "system$stream_get",
            "system$pipe_force_resume",
            "system$cancel_all_queries",
        }
    ),
    "mysql": frozenset(
        {
            "load_file",
            "sys_exec",
            "sys_eval",
        }
    ),
    "duckdb": frozenset(
        {
            # File-system access
            "read_csv",
            "read_csv_auto",
            "read_parquet",
            "read_json",
            "read_json_auto",
            "read_blob",
            "read_text",
            # Network access
            "httpfs_get",
            "http_get",
            "http_post",
            # Cross-engine scanning
            "postgres_scan",
            "sqlite_scan",
            "mysql_scan",
            "iceberg_scan",
            "delta_scan",
            # Extension loading
            "load_extension",
            "install_extension",
        }
    ),
    "sqlite": frozenset(
        {
            "load_extension",
            "readfile",
            "writefile",
            "edit",
            "zipfile",
            "sqlar",
        }
    ),
}

# Functions blocked regardless of dialect
_UNIVERSAL_BLOCKED_FUNCTIONS: frozenset[str] = frozenset(
    {
        "load_extension",
        "install_extension",
    }
)


def _check_dangerous_functions(parsed: exp.Expression, dialect: str) -> str | None:  # type: ignore[name-defined]
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
                return f"Blocked: function '{func_name}' is not permitted in governed read-only mode"
        # Check table-valued functions (e.g. FROM url(...), FROM read_csv(...))
        if isinstance(node, exp.Table):
            table_name = ""
            if hasattr(node, "name"):
                table_name = node.name
            table_name_lower = (table_name or "").lower().strip()
            if table_name_lower in all_blocked:
                return f"Blocked: table function '{table_name}' is not permitted in governed read-only mode"

    return None


def _check_into_clause(parsed: exp.Expression) -> str | None:  # type: ignore[name-defined]
    """Reject SELECT ... INTO OUTFILE/DUMPFILE (data exfiltration in MySQL/MariaDB)."""
    for node in parsed.walk():
        if isinstance(node, exp.Into):
            return "Blocked: SELECT INTO is not permitted in governed read-only mode"
    return None


__all__ = [
    "_BLOCKED_STATEMENT_TYPES",
    "_DANGEROUS_FUNCTIONS",
    "_UNIVERSAL_BLOCKED_FUNCTIONS",
    "_check_dangerous_functions",
    "_check_into_clause",
]
