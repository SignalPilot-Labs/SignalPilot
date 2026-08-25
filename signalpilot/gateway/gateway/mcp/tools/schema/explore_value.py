"""Schema exploration tool: explore_column (tool 13)."""

from gateway.errors.mcp import sanitize_mcp_error
from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _store_session
from gateway.mcp.server import mcp
from gateway.mcp.tools.schema.exploration_columns import (
    _identifier_quote_for,
    _quote_ident,
    _quote_table,
    _resolve_table,
)
from gateway.mcp.validation import _validate_connection_name

_PARAM_PLACEHOLDER = {
    "postgres": "$1",
    "redshift": "%s",
    "mysql": "%s",
    "mssql": "%s",
    "snowflake": "%s",
    "clickhouse": "%s",
    "databricks": "%s",
    "duckdb": "?",
    "sqlite": "?",
    # Trino's connector doesn't pass params to cursor.execute — fall back
    # to manual escaping (backslash + quote-doubling) for safety.
}


@audited_tool(mcp)
async def explore_column(
    connection_name: str,
    table: str,
    column: str,
    limit: int = 20,
    filter_pattern: str = "",
) -> str:
    """
    Explore distinct values in a specific column — useful for predicate and category discovery.

    ReFoRCE-style iterative column exploration: probe actual column values
    to resolve ambiguity when the question uses domain terminology not in
    column names. Returns top distinct values with counts and NULL stats.

    Args:
        connection_name: Database connection to query.
        table: Table name, with or without schema prefix (e.g., 'users' or 'public.users').
        column: Column name to explore.
        limit: Max distinct values to return (default 20).
        filter_pattern: Optional LIKE pattern to filter values (e.g., '%active%').
    """
    err = _validate_connection_name(connection_name)
    if err:
        return err

    limit = max(1, min(int(limit), 100))

    try:
        from gateway.connectors.pool_manager import pool_manager
        from gateway.connectors.schema_cache import schema_cache

        async with _store_session() as store:
            conn_info = await store.get_connection(connection_name)
            if not conn_info:
                available = [c.name for c in await store.list_connections()]
                return f"Error: Connection '{connection_name}' not found. Available: {available}"

            conn_str = await store.get_connection_string(connection_name)
            if not conn_str:
                return "Error: No credentials stored for this connection"

            extras = await store.get_credential_extras(connection_name)
            db_type = conn_info.db_type

            # Resolve the table against the cached schema, exactly like describe_table
            # (optional schema prefix, case-insensitive). Fall back to the name as
            # given if the schema cannot resolve it.
            schema = schema_cache.get(connection_name)
            if schema is None:
                try:
                    async with pool_manager.connection(
                        db_type, conn_str, credential_extras=extras, connection_name=connection_name
                    ) as connector:
                        schema = await connector.get_schema()
                    schema_cache.put(connection_name, schema)
                except Exception:
                    schema = {}
            table_key, _table_info = _resolve_table(schema, table)
            if table_key is None:
                table_key = table

            q = _identifier_quote_for(db_type)
            q_col = _quote_ident(column, q)
            q_table = _quote_table(table_key, q)

            where_clause = ""
            explore_params: list | None = None
            if filter_pattern:
                like_op = "ILIKE" if db_type in ("postgres", "redshift", "snowflake") else "LIKE"
                placeholder = _PARAM_PLACEHOLDER.get(db_type)
                if placeholder:
                    where_clause = f"WHERE {q_col} {like_op} {placeholder}"
                    explore_params = [filter_pattern]
                else:
                    # Manual escaping for connectors without param support (Trino).
                    safe_pattern = filter_pattern.replace("\\", "\\\\").replace("'", "''")
                    where_clause = f"WHERE {q_col} {like_op} '{safe_pattern}'"

            if db_type == "mssql":
                explore_sql = (
                    f"SELECT TOP {limit} {q_col} AS value, COUNT(*) AS [count] "
                    f"FROM {q_table} {where_clause} GROUP BY {q_col} ORDER BY [count] DESC"
                )
            else:
                explore_sql = (
                    f"SELECT {q_col} AS value, COUNT(*) AS count "
                    f"FROM {q_table} {where_clause} GROUP BY {q_col} ORDER BY count DESC LIMIT {limit}"
                )

            null_sql = (
                f"SELECT COUNT(*) AS total_rows, "
                f"SUM(CASE WHEN {q_col} IS NULL THEN 1 ELSE 0 END) AS null_count, "
                f"COUNT(DISTINCT {q_col}) AS distinct_count "
                f"FROM {q_table}"
            )

            async with pool_manager.connection(
                db_type, conn_str, credential_extras=extras, connection_name=connection_name
            ) as connector:
                values_rows = await connector.execute(explore_sql, params=explore_params, timeout=30)
                stats_rows = await connector.execute(null_sql, timeout=30)

        stats = stats_rows[0] if stats_rows else {}
        total_rows = stats.get("total_rows", 0) or 0
        null_count = stats.get("null_count", 0) or 0
        null_pct = round(null_count / max(total_rows, 1) * 100, 1)

        lines = [f"Column: {table_key}.{column}"]
        lines.append(f"Total rows: {total_rows:,}")
        lines.append(f"Distinct values: {stats.get('distinct_count', 0) or 0:,}")
        lines.append(f"NULL: {null_count:,} ({null_pct}%)")

        if filter_pattern:
            lines.append(f"Filter: LIKE '{filter_pattern}'")

        lines.append("")
        if values_rows:
            lines.append("Top values:")
            for v in values_rows:
                val_str = str(v.get("value")) if v.get("value") is not None else "NULL"
                lines.append(f"  {val_str}: {v.get('count', 0):,}")
        else:
            lines.append("No values found.")

        return "\n".join(lines)

    except Exception as e:
        return f"Error: {sanitize_mcp_error(str(e))}"
