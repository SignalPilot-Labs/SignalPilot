"""Shared helper functions for MCP tool implementations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gateway.mcp.context import _store_session
from gateway.mcp.validation import _quote_table


async def _get_column_names(connector, db_type: str, table_name: str, connection_name: str | None = None) -> list[str]:
    """Get column names for a table, using the correct SQL for the database dialect."""
    if db_type in ("sqlite", "duckdb"):
        rows = await connector.execute(f"PRAGMA table_info('{table_name}')")
        return [r.get("name", "") for r in rows if r.get("name")]
    else:
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


async def _get_sandbox_url() -> str:
    async with _store_session() as store:
        settings = await store.load_settings()
    return settings.sandbox_manager_url


def _extract_replacement_snippet(content: str, replacement_date: str) -> str:
    """Return a short context snippet showing where the replacement appears."""
    needle = f"'{replacement_date}'::date"
    idx = content.find(needle)
    if idx == -1:
        return ""
    start = max(0, idx - 30)
    end = min(len(content), idx + len(needle) + 30)
    snippet = content[start:end].replace("\n", " ").strip()
    return f"...{snippet}..."


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


async def _find_hazard_table_date(
    connection_name: str,
    project_path: Path,
    boundaries: _DateBoundaryResult,
) -> tuple[str, str] | None:
    """Look for pre-existing hazard model tables in the DB and return their max date.

    When the source DB contains gold-generated tables (e.g. a pre-existing
    ``shopify__calendar`` or ``int_quickbooks__general_ledger_date_spine``),
    their max date reflects the original gold generation date — the correct
    replacement for ``current_date`` in the model SQL.

    Returns (date_string, source_description) or None.
    """
    from gateway.dbt.inventory import scan_project as _scan_project

    project = _scan_project(project_path)
    if not project.date_hazards:
        return None

    async with _store_session() as store:
        conn_info = await store.get_connection(connection_name)
        if not conn_info:
            return None
        conn_str = await store.get_connection_string(connection_name)
        if not conn_str:
            return None

    # Collect model names from hazards (the tables we want to check).
    model_names = [h.get("model_name", "") for h in project.date_hazards if h.get("model_name")]
    if not model_names:
        return None

    # Also check tables whose name contains '__' (dbt derived pattern) from boundaries.
    derived_max: dict[str, tuple[str, int]] = {}  # table -> (max_date, row_count)
    if boundaries.table_col_results:
        for tbl_name, col_results in boundaries.table_col_results.items():
            short_name = tbl_name.split(".")[-1] if "." in tbl_name else tbl_name
            for _, (_, max_val) in col_results.items():
                if max_val and "__" in short_name:
                    row_count = boundaries.table_row_count.get(tbl_name, 0)
                    if max_val > derived_max.get(short_name, ("", 0))[0]:
                        derived_max[short_name] = (max_val, row_count)

    # Priority 1: check if any hazard model name exists as a table with date data.
    # Take the MAX across all date columns (e.g. date_year=2024-01-01 vs
    # period_first_day=2024-09-01 — we want the latter).
    for model_name in model_names:
        for tbl_name, col_results in (boundaries.table_col_results or {}).items():
            short_name = tbl_name.split(".")[-1] if "." in tbl_name else tbl_name
            if short_name == model_name:
                best = max(
                    (mv for _, (_, mv) in col_results.items() if mv),
                    default=None,
                )
                if best:
                    return best, f"{best} (from pre-existing table {short_name})"

    # Priority 2: use the max date from the largest derived table (name contains '__').
    if derived_max:
        best_table = max(derived_max, key=lambda k: derived_max[k][1])
        max_date, row_count = derived_max[best_table]
        return max_date, f"{max_date} (from largest derived table {best_table}, {row_count:,} rows)"

    return None
