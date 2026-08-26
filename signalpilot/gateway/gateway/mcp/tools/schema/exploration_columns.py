"""Schema exploration tool: explore_columns (tool 11)."""

from typing import Any

from gateway.errors.mcp import sanitize_mcp_error
from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _store_session
from gateway.mcp.server import mcp
from gateway.mcp.validation import _validate_connection_name

_NUMERIC_TYPES = {
    "integer",
    "int",
    "bigint",
    "smallint",
    "tinyint",
    "hugeint",
    "numeric",
    "decimal",
    "float",
    "double",
    "real",
    "number",
    "int4",
    "int8",
    "int2",
    "float4",
    "float8",
    "float32",
    "float64",
    "uint32",
    "uint64",
    "int32",
    "int64",
}


def _resolve_table(schema: dict[str, Any], table: str) -> tuple[str | None, dict | None]:
    """Resolve a user-supplied table name against a schema dict keyed 'schema.table'.

    Mirrors describe_table's resolution: accepts an optional schema prefix
    (e.g. 'main.fct_sales' or just 'fct_sales'), matches case-insensitively,
    and falls back to a bare-name match against each table's 'name'.
    """
    if table in schema:
        return table, schema[table]

    t_lower = table.lower()
    for key, tbl in schema.items():
        if key.lower() == t_lower:
            return key, tbl

    bare = t_lower.split(".")[-1]
    for key, tbl in schema.items():
        if tbl.get("name", "").lower() == bare:
            return key, tbl

    return None, None


def _identifier_quote_for(db_type: str) -> str:
    if db_type in ("mysql", "clickhouse", "databricks"):
        return "`"
    if db_type == "mssql":
        return "["
    return '"'


def _quote_ident(name: str, q: str) -> str:
    if q == "[":
        return "[" + name.replace("]", "]]") + "]"
    return q + name.replace(q, q + q) + q


def _quote_table(table: str, q: str) -> str:
    return ".".join(_quote_ident(p, q) for p in table.split("."))


async def _explore_columns_data(
    connector,
    db_type: str,
    table_key: str,
    table_info: dict[str, Any],
    columns: list[str] | None = None,
    include_stats: bool = True,
    include_values: bool = True,
    value_limit: int = 10,
) -> dict[str, Any]:
    """Gather column exploration data through a live connector (no HTTP, no cache lookup)."""
    all_columns = table_info.get("columns", [])
    if columns:
        col_set = {c.lower() for c in columns}
        explore_cols = [c for c in all_columns if c["name"].lower() in col_set]
    else:
        explore_cols = all_columns

    sample_values: dict[str, list] = {}
    if include_values:
        col_names = [c["name"] for c in explore_cols[:20]]
        try:
            sample_values = await connector.get_sample_values(table_key, col_names, value_limit)
        except Exception:
            pass

    numeric_stats: dict[str, dict] = {}
    if include_stats:
        num_cols = [
            c
            for c in explore_cols
            if c.get("type", "").lower().rstrip("()0123456789, ").split("(")[0] in _NUMERIC_TYPES
        ]
        if num_cols:
            q = _identifier_quote_for(db_type)
            stat_parts = []
            for c in num_cols[:15]:
                safe = _quote_ident(c["name"], q)
                stat_parts.append(f"MIN({safe})")
                stat_parts.append(f"MAX({safe})")
                stat_parts.append(f"AVG(CAST({safe} AS FLOAT))")
            try:
                q_table = _quote_table(table_key, q)
                stat_sql = f"SELECT {', '.join(stat_parts)} FROM {q_table}"
                if db_type == "mssql":
                    stat_sql = f"SELECT TOP 1000000 {', '.join(stat_parts)} FROM {q_table}"
                rows = await connector.execute(stat_sql, timeout=15)
                if rows:
                    vals = list(rows[0].values())
                    for i, c in enumerate(num_cols[:15]):
                        idx = i * 3
                        if idx + 2 < len(vals):
                            numeric_stats[c["name"]] = {
                                "min": vals[idx],
                                "max": vals[idx + 1],
                                "avg": round(float(vals[idx + 2]), 4) if vals[idx + 2] is not None else None,
                            }
            except Exception:
                pass

    result_cols: list[dict] = []
    for col in explore_cols:
        col_result: dict = {
            "name": col["name"],
            "type": col.get("type", ""),
            "nullable": col.get("nullable", True),
            "primary_key": col.get("primary_key", False),
        }
        if col.get("comment"):
            col_result["comment"] = col["comment"]
        if col.get("stats"):
            col_result["schema_stats"] = col["stats"]
        if col["name"] in numeric_stats:
            col_result["value_stats"] = numeric_stats[col["name"]]
        if col["name"] in sample_values:
            col_result["sample_values"] = sample_values[col["name"]]
        result_cols.append(col_result)

    return {
        "table": table_key,
        "table_type": table_info.get("type", "table"),
        "row_count": table_info.get("row_count", 0),
        "columns_explored": len(result_cols),
        "columns": result_cols,
    }


def _format_columns_report(data: dict[str, Any], include_stats: bool, include_samples: bool) -> str:
    explored_cols = data.get("columns", [])
    table = data.get("table", "")
    table_type = data.get("table_type", "table")
    rc = data.get("row_count", "?")
    lines = [
        f"{'View' if table_type == 'view' else 'Table'}: {table} ({rc:,} rows)"
        if isinstance(rc, int)
        else f"Table: {table} ({rc} rows)"
    ]
    lines.append("")

    for col in explored_cols:
        parts = [f"  {col['name']}: {col.get('type', 'unknown')}"]
        flags = []
        if col.get("primary_key"):
            flags.append("PK")
        if not col.get("nullable", True):
            flags.append("NOT NULL")
        if flags:
            parts.append(f"[{', '.join(flags)}]")
        if col.get("comment"):
            parts.append(f"-- {col['comment']}")
        lines.append(" ".join(parts))

        # Schema statistics (distinct count, cardinality)
        if include_stats and col.get("schema_stats"):
            stats = col["schema_stats"]
            stat_parts = []
            if stats.get("distinct_count"):
                stat_parts.append(f"distinct={stats['distinct_count']}")
            if stats.get("distinct_fraction"):
                frac = abs(stats["distinct_fraction"])
                stat_parts.append(f"uniqueness={frac:.2f}")
            if stat_parts:
                lines.append(f"    stats: {', '.join(stat_parts)}")

        # Numeric value stats (min/max/avg)
        if include_stats and col.get("value_stats"):
            vs = col["value_stats"]
            vs_parts = []
            if vs.get("min") is not None:
                vs_parts.append(f"min={vs['min']}")
            if vs.get("max") is not None:
                vs_parts.append(f"max={vs['max']}")
            if vs.get("avg") is not None:
                vs_parts.append(f"avg={vs['avg']}")
            if vs_parts:
                lines.append(f"    range: {', '.join(vs_parts)}")

        # Sample values
        if include_samples and col.get("sample_values"):
            vals = col["sample_values"][:10]
            lines.append(f"    values: {', '.join(repr(v) for v in vals)}")

    return "\n".join(lines)


@audited_tool(mcp)
async def explore_columns(
    connection_name: str,
    table: str,
    columns: list[str] | None = None,
    include_samples: bool = True,
    include_stats: bool = True,
) -> str:
    """
    Explore specific columns in a table — their types, statistics, and sample values.

    Use this for iterative column exploration (ReFoRCE pattern): first use
    schema_link to find relevant tables, then explore_columns to understand
    specific columns before writing SQL.

    Args:
        connection_name: Name of the database connection
        table: Table name, with or without schema prefix (e.g., "customers" or "public.customers")
        columns: Optional list of column names to explore. If None, explores all.
        include_samples: Whether to include sample distinct values
        include_stats: Whether to include column statistics

    Returns column details: type, nullable, primary_key, comment, stats, sample values
    """
    err = _validate_connection_name(connection_name)
    if err:
        return err

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

            # Resolve the table against the cached schema, exactly like describe_table.
            schema = schema_cache.get(connection_name)
            if schema is None:
                async with pool_manager.connection(
                    conn_info.db_type, conn_str, credential_extras=extras, connection_name=connection_name
                ) as connector:
                    schema = await connector.get_schema()
                schema_cache.put(connection_name, schema)

            table_key, table_info = _resolve_table(schema, table)
            if table_info is None:
                # The table may have been created after the schema was cached
                # (e.g. a freshly built model) — refresh once and retry.
                async with pool_manager.connection(
                    conn_info.db_type, conn_str, credential_extras=extras, connection_name=connection_name
                ) as connector:
                    schema = await connector.get_schema()
                schema_cache.put(connection_name, schema)
                table_key, table_info = _resolve_table(schema, table)

            if table_info is None:
                table_names = [v.get("name", k) for k, v in schema.items()]
                return f"Table '{table}' not found. Available tables:\n" + "\n".join(
                    f"  - {t}" for t in sorted(table_names)
                )

            async with pool_manager.connection(
                conn_info.db_type, conn_str, credential_extras=extras, connection_name=connection_name
            ) as connector:
                data = await _explore_columns_data(
                    connector,
                    conn_info.db_type,
                    table_key,
                    table_info,
                    columns=columns,
                    include_stats=include_stats,
                    include_values=include_samples,
                    value_limit=10,
                )

        return _format_columns_report(data, include_stats, include_samples)

    except Exception as e:
        return f"Error exploring columns: {sanitize_mcp_error(str(e))}"
