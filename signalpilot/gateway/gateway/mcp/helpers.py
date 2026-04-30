"""Shared helper functions for MCP tool implementations."""

from __future__ import annotations

from dataclasses import dataclass

from gateway.mcp.context import _store_session
from gateway.mcp.validation import _quote_table


async def _get_column_names(connector, db_type: str, table_name: str, connection_name: str | None = None) -> list[str]:
    """Get column names for a table, using the correct SQL for the database dialect."""
    if db_type in ("sqlite", "duckdb"):
        rows = await connector.execute(f"PRAGMA table_info('{table_name}')")
        return [r.get("name", "") for r in rows if r.get("name")]
    parts = table_name.split(".")
    if len(parts) == 2:
        schema, tbl = parts
    else:
        schema, tbl = "public", parts[0]
    sql = (
        f"SELECT column_name FROM information_schema.columns "
        f"WHERE table_schema = '{schema}' AND table_name = '{tbl}' "
        f"ORDER BY ordinal_position"
    )
    rows = await connector.execute(sql)
    return [r.get("column_name", "") for r in rows if r.get("column_name")]


def _format_health_stats(stats: dict) -> str:
    """Format health stats dict into readable text."""
    lines = [
        f"Connection: {stats['connection_name']} ({stats['db_type']})",
        f"Status: {stats['status'].upper()}",
        f"Samples: {stats['sample_count']} (last {stats['window_seconds']}s)",
    ]
    if stats.get("successes") is not None:
        lines.append(f"Success/Fail: {stats['successes']}/{stats['failures']}")
    if stats.get("error_rate") is not None:
        lines.append(f"Error Rate: {stats['error_rate'] * 100:.1f}%")
    if stats.get("latency_p50_ms") is not None:
        lines.append(
            f"Latency: p50={stats['latency_p50_ms']:.0f}ms  p95={stats['latency_p95_ms']:.0f}ms  p99={stats['latency_p99_ms']:.0f}ms"
        )
    if stats.get("last_error"):
        lines.append(f"Last Error: {stats['last_error']}")
    return "\n".join(lines)


@dataclass
class _DateBoundaryResult:
    """Structured result from the internal date-boundary query."""

    global_max: str | None
    largest_table: str | None
    largest_table_row_count: int
    largest_table_max: str | None
    table_max: dict[str, str]
    table_row_count: dict[str, int]
    found_any: bool
    error: str | None
    # Per-table detail: {full_name: {col_name: (min, max)}}
    table_col_results: dict[str, dict[str, tuple[str | None, str | None]]]
    db_type: str


async def _fetch_date_boundaries(connection_name: str) -> _DateBoundaryResult:
    """Shared internal function that queries date column boundaries for a connection.

    Returns a structured _DateBoundaryResult. Both get_date_boundaries and
    fix_date_spine_hazards call this to avoid duplicating the query logic.

    Raises ValueError if the connection name or credentials are invalid.
    """
    from gateway.connectors.pool_manager import pool_manager
    from gateway.connectors.schema_cache import schema_cache

    async with _store_session() as store:
        conn_info = await store.get_connection(connection_name)
        if not conn_info:
            available = [c.name for c in await store.list_connections()]
            raise ValueError(f"Connection '{connection_name}' not found. Available: {available}")

        conn_str = await store.get_connection_string(connection_name)
        if not conn_str:
            raise ValueError("No credentials stored for this connection")

        extras = await store.get_credential_extras(connection_name)

    schema = schema_cache.get(connection_name)
    if schema is None:
        async with pool_manager.connection(
            conn_info.db_type, conn_str, credential_extras=extras, connection_name=connection_name
        ) as connector:
            schema = await connector.get_schema()
        schema_cache.put(connection_name, schema)

    DATE_TYPE_KEYWORDS = ("date", "timestamp", "datetime")

    global_max: str | None = None
    table_max: dict[str, str] = {}
    table_row_count: dict[str, int] = {}
    table_col_results: dict[str, dict[str, tuple[str | None, str | None]]] = {}
    found_any = False

    for key in sorted(schema.keys()):
        table = schema[key]
        table_schema = table.get("schema", "")
        table_name = table.get("name", key)
        full_name = f"{table_schema}.{table_name}" if table_schema else table_name

        date_cols = [
            col
            for col in table.get("columns", [])
            if any(kw in col.get("type", "").lower() for kw in DATE_TYPE_KEYWORDS)
        ]

        if not date_cols:
            continue

        found_any = True
        col_results: dict[str, tuple[str | None, str | None]] = {}

        select_parts = []
        for col in date_cols:
            col_name = col["name"]
            safe_col_name = col_name.replace('"', '""')
            quoted = f'"{safe_col_name}"'
            select_parts.append(f'MIN({quoted}) AS "min_{safe_col_name}", MAX({quoted}) AS "max_{safe_col_name}"')

        quoted_table = _quote_table(full_name)
        sql = f"SELECT {', '.join(select_parts)} FROM {quoted_table}"

        try:
            async with pool_manager.connection(
                conn_info.db_type, conn_str, credential_extras=extras, connection_name=connection_name
            ) as connector:
                rows = await connector.execute(sql)
                if rows:
                    row = rows[0]
                    for col in date_cols:
                        col_name = col["name"]
                        min_val = row.get(f"min_{col_name}")
                        max_val = row.get(f"max_{col_name}")
                        col_results[col_name] = (
                            str(min_val).split(" ")[0] if min_val is not None else None,
                            str(max_val).split(" ")[0] if max_val is not None else None,
                        )
                        if max_val is not None:
                            max_str = str(max_val).split(" ")[0]
                            if global_max is None or max_str > global_max:
                                global_max = max_str
                            if max_str > table_max.get(full_name, ""):
                                table_max[full_name] = max_str
                count_sql = f'SELECT COUNT(*) AS "cnt" FROM {quoted_table}'
                count_rows = await connector.execute(count_sql)
                if count_rows:
                    raw = count_rows[0].get("cnt")
                    if raw is not None:
                        table_row_count[full_name] = int(raw)
        except Exception:
            for col in date_cols:
                col_results[col["name"]] = (None, None)

        table_col_results[full_name] = col_results

    largest_table: str | None = max(table_row_count, key=table_row_count.__getitem__) if table_row_count else None
    largest_table_max = table_max.get(largest_table) if largest_table else None
    largest_table_row_count = table_row_count.get(largest_table, 0) if largest_table else 0

    return _DateBoundaryResult(
        global_max=global_max,
        largest_table=largest_table,
        largest_table_row_count=largest_table_row_count,
        largest_table_max=largest_table_max,
        table_max=table_max,
        table_row_count=table_row_count,
        found_any=found_any,
        error=None,
        table_col_results=table_col_results,
        db_type=conn_info.db_type,
    )


