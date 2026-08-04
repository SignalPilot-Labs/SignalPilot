"""Dangerous-function and statement-type denylist data + AST checker."""

from __future__ import annotations

import re

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
            "pg_stat_file",
            "pg_file_write",
            "pg_file_rename",
            "pg_file_unlink",
            # Executes a SQL string server-side, entirely outside AST governance
            "query_to_xml",
            "query_to_xmlschema",
            "query_to_xml_and_xmlschema",
            # Unbounded server-side sleep — denial of service
            "pg_sleep",
            "pg_sleep_for",
            "pg_sleep_until",
            # Discloses on-disk paths and other server configuration
            "current_setting",
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
            # Aliases of the readers above — same file access, different name
            "parquet_scan",
            "csv_scan",
            "read_ndjson",
            "read_ndjson_auto",
            "read_ndjson_objects",
            "read_json_objects",
            "read_json_objects_auto",
            "glob",
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
    "tsql": frozenset(
        {
            # External rowset / linked-server access (covers OPENROWSET(BULK ...))
            "openrowset",
            "opendatasource",
            "openquery",
            "openxml",
            # OS command execution / dynamic SQL
            "xp_cmdshell",
            "sp_executesql",
            "sp_oacreate",
            "sp_oamethod",
            "sp_addlinkedserver",
            # File-system / registry probes
            "xp_dirtree",
            "xp_fileexist",
            "xp_regread",
            "xp_regwrite",
        }
    ),
    "databricks": frozenset(
        {
            # File / external-location readers
            "read_files",
            "cloud_files",
            "read_kafka",
            # Arbitrary JVM execution
            "reflect",
            "java_method",
            # Secret access
            "secret",
        }
    ),
    "trino": frozenset(
        {
            # Polymorphic table functions that push raw queries to connectors
            "query",
            "raw_query",
            "native_query",
        }
    ),
}

# Redshift is postgres-derived; it inherits the postgres denylist (dblink family
# et al.).  COPY/UNLOAD external forms are already blocked as Command statements.
_DANGEROUS_FUNCTIONS["redshift"] = _DANGEROUS_FUNCTIONS["postgres"]

# Fail-closed fallback: a dialect without a reviewed policy gets the union of
# every known dialect's denylist rather than an empty set.
_ALL_DIALECT_FUNCTIONS: frozenset[str] = frozenset().union(*_DANGEROUS_FUNCTIONS.values())

# DuckDB treats file paths and URLs as table names (SELECT * FROM 'x.parquet').
# These heuristics flag identifiers that can only be paths, not table names.
_URL_SCHEME_PATTERN = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)
_DATA_FILE_EXTENSIONS: tuple[str, ...] = (
    ".csv",
    ".tsv",
    ".txt",
    ".parquet",
    ".json",
    ".jsonl",
    ".ndjson",
    ".gz",
    ".zst",
    ".xlsx",
    ".db",
    ".duckdb",
    ".sqlite",
)


# Dialects whose table syntax can address a file or URL directly.
_PATHLIKE_TABLE_DIALECTS: frozenset[str] = frozenset({"duckdb", "databricks", "spark", "hive"})

# Spark-family readers usable as `FROM <reader>.`<path>`` without a function call.
_SPARK_PATH_READERS: frozenset[str] = frozenset(
    {"parquet", "json", "csv", "orc", "avro", "text", "binaryfile", "delta"}
)


def _is_four_part_table_name(table: exp.Table) -> bool:
    """True if a table reference carries a fourth part (server.db.schema.object).

    sqlglot models at most three parts as catalog/db/name; a fourth part
    overflows into a Dot chain under ``this``.  T-SQL also permits omitted
    middle parts (``srv...tbl``), which drop out of ``Table.parts`` entirely but
    still leave the Dot chain behind, so both signals are checked.
    """
    if isinstance(table.args.get("this"), exp.Dot):
        return True
    return len(table.parts) >= 4


def _is_pathlike_table_name(name: str) -> bool:
    """True if a table identifier looks like a file path or URL."""
    normalized = name.strip().lower()
    if not normalized:
        return False
    if _URL_SCHEME_PATTERN.match(normalized):
        return True
    if "/" in normalized or "\\" in normalized:
        return True
    return normalized.endswith(_DATA_FILE_EXTENSIONS)


# Functions blocked regardless of dialect
_UNIVERSAL_BLOCKED_FUNCTIONS: frozenset[str] = frozenset(
    {
        "load_extension",
        "install_extension",
    }
)


def _dangerous_function_name(node: exp.Expression) -> str:
    """Return a normalized function/table-function name from a sqlglot AST node."""
    if isinstance(node, exp.Table):
        table_expr = getattr(node, "this", None)
        if isinstance(table_expr, exp.Expression):
            resolved = _dangerous_function_name(table_expr)
            if resolved:
                return resolved
            # A table function whose argument list sqlglot did not model as a
            # Func — e.g. ClickHouse `FROM file('/etc/passwd')` — parses as a
            # Table wrapping a bare Identifier, so the callable name has to come
            # off the Table itself. Only unqualified names qualify: a table
            # function never carries a schema or catalog, whereas a real table
            # like `catalog.system.query` does, and must not be mistaken for one.
            if not (getattr(node, "db", "") or getattr(node, "catalog", "")):
                return str(getattr(node, "name", "") or "")
            return ""
        return str(getattr(node, "name", "") or table_expr or "")

    if isinstance(node, exp.Anonymous):
        return str(getattr(node, "name", "") or getattr(node, "this", "") or "")

    if isinstance(node, exp.Func):
        try:
            sql_name = node.sql_name()
        except Exception:
            sql_name = ""
        if sql_name and sql_name.upper() not in {"ANONYMOUS", "FUNC"}:
            return sql_name
        return str(getattr(node, "name", "") or getattr(node, "this", "") or "")

    return ""


def _check_dangerous_functions(parsed: exp.Expression, dialect: str) -> str | None:  # type: ignore[name-defined]
    """Walk AST and reject queries containing dangerous functions.

    Returns a blocked_reason string if a dangerous function is found, or None
    if the query is safe.
    """
    # Normalize dialect name
    dialect_key = dialect.lower().replace("postgresql", "postgres").replace("mssql", "tsql")
    # Fail closed: unknown dialects get the union of every known denylist
    blocked_names = _DANGEROUS_FUNCTIONS.get(dialect_key, _ALL_DIALECT_FUNCTIONS)
    all_blocked = blocked_names | _UNIVERSAL_BLOCKED_FUNCTIONS

    for node in parsed.walk():
        # Check function calls (both named functions and anonymous/dialect-specific)
        if isinstance(node, (exp.Anonymous, exp.Func)):
            func_name = _dangerous_function_name(node)
            func_name_lower = func_name.lower().strip()
            if func_name_lower in all_blocked:
                return f"Blocked: function '{func_name}' is not permitted in governed read-only mode"
        # Check table-valued functions (e.g. FROM url(...), FROM read_csv(...))
        if isinstance(node, exp.Table):
            table_name = _dangerous_function_name(node)
            table_name_lower = (table_name or "").lower().strip()
            if table_name_lower in all_blocked:
                return f"Blocked: table function '{table_name}' is not permitted in governed read-only mode"
            # Path-as-table: DuckDB `FROM 'file.parquet'` / `FROM '/etc/passwd'`,
            # and the Spark family's `FROM parquet.\`/path\`` / `FROM json.\`s3://…\``,
            # where the reader name is the db qualifier rather than a function.
            if dialect_key in _PATHLIKE_TABLE_DIALECTS:
                for candidate in (node.name, getattr(node, "db", "") or ""):
                    if _is_pathlike_table_name(candidate):
                        return (
                            f"Blocked: file or URL table reference '{candidate}' "
                            "is not permitted in governed read-only mode"
                        )
                if (getattr(node, "db", "") or "").strip().lower() in _SPARK_PATH_READERS:
                    return (
                        f"Blocked: file table reference via '{node.db}' "
                        "is not permitted in governed read-only mode"
                    )
            # Four-part T-SQL name reaches a linked server without OPENQUERY and
            # so cannot be caught by the function denylist. Three-part names
            # (database.schema.object) are ordinary and must still pass.
            if dialect_key == "tsql" and _is_four_part_table_name(node):
                return (
                    f"Blocked: four-part table reference '{node.sql(dialect='tsql')}' "
                    "targets a linked server and is not permitted in governed read-only mode"
                )

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
    "_is_four_part_table_name",
    "_check_into_clause",
]
