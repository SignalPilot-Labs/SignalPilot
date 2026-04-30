"""Raw schema introspection endpoints."""

from __future__ import annotations

import logging

from fastapi import HTTPException, Query

from gateway.api.deps import (
    StoreD,
    apply_schema_filter,
    get_schema_filters,
    require_connection,
    sanitize_db_error,
)
from gateway.api.schema._constants import _FILTER_PATTERN_MAX_LEN
from gateway.api.schema._identifiers import _quote_identifier, _quote_table_name
from gateway.api.schema._router import router
from gateway.connectors.pool_manager import pool_manager
from gateway.connectors.schema_cache import schema_cache
from gateway.schema_utils import (
    STRING_COLUMN_TYPES,
    _compress_schema,
    _deduplicate_partitioned_tables,
    _group_tables,
)
from gateway.scope_guard import RequireScope

logger = logging.getLogger(__name__)


# ───────────────────────────────────────────────────────────────────────────
# GET /connections/{name}/schema
# ───────────────────────────────────────────────────────────────────────────


@router.get("/connections/{name}/schema", dependencies=[RequireScope("read")])
async def get_connection_schema(
    name: str,
    store: StoreD,
    compact: bool = Query(default=False, description="Return compressed schema optimized for LLM context windows"),
    filter: str = Query(
        default="",
        max_length=1000,
        description="Filter tables by name pattern (case-insensitive substring match, comma-separated)",
    ),
):
    """Retrieve the full schema for a database connection (Feature #18: schema caching).

    With compact=true, returns a compressed DDL-style representation that reduces
    token count by ~60-70% while preserving all information needed for text-to-SQL.
    With filter, returns only tables matching the given patterns.
    This is critical for Spider2.0 benchmark performance on large schemas.
    """
    info = await require_connection(store, name)

    conn_str = await store.get_connection_string(name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored for this connection")

    # Check schema cache first (Feature #18)
    cached = schema_cache.get(name)
    is_cached = cached is not None
    if cached is None:
        try:
            extras = await store.get_credential_extras(name)
            async with pool_manager.connection(
                info.db_type, conn_str, credential_extras=extras, connection_name=name
            ) as connector:
                cached = await connector.get_schema()
        except Exception as e:
            raise HTTPException(status_code=500, detail=sanitize_db_error(str(e), info.db_type))
        schema_cache.put(name, cached)

    # Apply endorsement filter (HEX Data Browser pattern — curate tables for AI agents)
    filtered = await store.apply_endorsement_filter(name, cached)
    sf_include, sf_exclude = await get_schema_filters(store, name)
    filtered = apply_schema_filter(filtered, sf_include, sf_exclude)

    # Apply table name filter if provided (additional narrowing)
    if filter:
        patterns = [p.strip().lower() for p in filter.split(",") if p.strip()]
        filtered = {
            k: v
            for k, v in filtered.items()
            if any(pat in k.lower() or pat in v.get("name", "").lower() for pat in patterns)
        }

    # For compact mode, include cached sample values inline (Spider2.0 optimization)
    if compact:
        sample_map: dict[str, dict[str, list]] = {}
        for table_key in filtered:
            cached_samples = schema_cache.get_sample_values(name, table_key)
            if cached_samples:
                sample_map[table_key] = cached_samples
        tables = _compress_schema(filtered, sample_map)
    else:
        tables = filtered
    return {
        "connection_name": name,
        "db_type": info.db_type,
        "table_count": len(filtered),
        "total_tables": len(cached),
        "tables": tables,
        "cached": is_cached,
        "compact": compact,
        "filtered": bool(filter),
    }


# ───────────────────────────────────────────────────────────────────────────
# GET /connections/{name}/schema/grouped
# ───────────────────────────────────────────────────────────────────────────


@router.get("/connections/{name}/schema/grouped", dependencies=[RequireScope("read")])
async def get_grouped_schema(
    name: str,
    store: StoreD,
    sample_limit: int = Query(default=3, ge=1, le=10),
):
    """Return schema organized by table groups — optimized for large schemas.

    Uses ReFoRCE-style pattern-based table grouping to organize related tables
    together. This helps AI agents understand table relationships and reduces
    schema linking errors in text-to-SQL tasks.
    """
    info = await require_connection(store, name)

    conn_str = await store.get_connection_string(name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored")

    try:
        extras = await store.get_credential_extras(name)
        async with pool_manager.connection(
            info.db_type, conn_str, credential_extras=extras, connection_name=name
        ) as connector:
            cached = schema_cache.get(name)
            if cached is None:
                cached = await connector.get_schema()
                schema_cache.put(name, cached)

            # ReFoRCE-style: deduplicate partitioned tables before compression
            deduped, partition_map = _deduplicate_partitioned_tables(cached)
            compressed = _compress_schema(deduped)
            groups = _group_tables(deduped)

        return {
            "connection_name": name,
            "db_type": info.db_type,
            "table_count": len(cached),
            "deduplicated_count": len(deduped),
            "partitioned_families": len(partition_map),
            "group_count": len(groups),
            "groups": {
                group_name: {
                    "tables": {k: compressed[k] for k in table_keys if k in compressed},
                    "table_count": len(table_keys),
                }
                for group_name, table_keys in groups.items()
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=sanitize_db_error(str(e), info.db_type))


# ───────────────────────────────────────────────────────────────────────────
# GET /connections/{name}/schema/samples
# ───────────────────────────────────────────────────────────────────────────


@router.get("/connections/{name}/schema/samples", dependencies=[RequireScope("read")])
async def get_schema_samples(
    name: str,
    store: StoreD,
    tables: str = Query(
        default="",
        max_length=2000,
        description="Comma-separated table keys to sample (e.g., 'public.users,public.orders')",
    ),
    limit: int = Query(default=5, ge=1, le=20, description="Max distinct values per column"),
):
    """Get sample distinct values for columns — critical for Spider2.0 schema linking.

    Top performers use sample values to reduce column name hallucination
    and improve schema-to-question matching. Returns up to `limit` distinct
    values per column for the specified tables.
    """
    info = await require_connection(store, name)

    conn_str = await store.get_connection_string(name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored")

    # Get schema to know which columns exist
    cached = schema_cache.get(name)
    if cached is None:
        try:
            extras = await store.get_credential_extras(name)
            async with pool_manager.connection(
                info.db_type, conn_str, credential_extras=extras, connection_name=name
            ) as connector:
                cached = await connector.get_schema()
                schema_cache.put(name, cached)
        except Exception as e:
            raise HTTPException(status_code=500, detail=sanitize_db_error(str(e), info.db_type))

    # Determine which tables to sample
    table_keys = [t.strip() for t in tables.split(",") if t.strip()] if tables else list(cached.keys())
    # Cap at 10 tables to prevent overload
    table_keys = table_keys[:10]

    try:
        extras = await store.get_credential_extras(name)
        async with pool_manager.connection(
            info.db_type, conn_str, credential_extras=extras, connection_name=name
        ) as connector:
            samples: dict[str, dict[str, list]] = {}
            for table_key in table_keys:
                if table_key not in cached:
                    continue
                table_info = cached[table_key]
                # Only sample string-like columns (most useful for schema linking)
                sample_cols = [
                    col["name"]
                    for col in table_info.get("columns", [])
                    if col.get("type", "") in STRING_COLUMN_TYPES or "char" in col.get("type", "").lower()
                ]
                if not sample_cols:
                    continue

                table_name = (
                    f"{table_info.get('schema', '')}.{table_info['name']}"
                    if table_info.get("schema")
                    else table_info["name"]
                )
                values = await connector.get_sample_values(table_name, sample_cols, limit=limit)
                if values:
                    samples[table_key] = values
                    schema_cache.put_sample_values(name, table_key, values)

        return {
            "connection_name": name,
            "tables_sampled": len(samples),
            "samples": samples,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=sanitize_db_error(str(e), info.db_type))


# ───────────────────────────────────────────────────────────────────────────
# POST /connections/{name}/schema/explore
# ───────────────────────────────────────────────────────────────────────────


@router.post("/connections/{name}/schema/explore", dependencies=[RequireScope("read")])
async def explore_column_values(
    name: str,
    store: StoreD,
    table: str = Query(..., max_length=256, description="Full table name (e.g., 'public.users')"),
    column: str = Query(..., max_length=128, description="Column to explore"),
    limit: int = Query(default=20, ge=1, le=100, description="Max distinct values"),
    filter_pattern: str = Query(default="", description="LIKE pattern to filter values (e.g., '%active%')"),
):
    """ReFoRCE-style iterative column exploration for Spider2.0.

    Allows the AI agent to dynamically probe column values to resolve ambiguity
    in schema linking. ReFoRCE's ablation shows disabling column exploration
    causes 3-4% EX degradation — it's critical for handling enum-like columns
    where the question uses domain terminology not in column names.

    Returns distinct values, value counts, and NULL statistics.
    """
    if filter_pattern and len(filter_pattern) > _FILTER_PATTERN_MAX_LEN:
        raise HTTPException(
            status_code=422, detail=f"filter_pattern must be at most {_FILTER_PATTERN_MAX_LEN} characters"
        )

    info = await require_connection(store, name)

    conn_str = await store.get_connection_string(name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored")

    db_type = info.db_type
    # Build exploration query with dialect-aware quoting
    quote = '"' if db_type in ("postgres", "redshift", "snowflake", "trino", "duckdb", "sqlite") else "`"
    if db_type == "mssql":
        quote = "["

    q_col = _quote_identifier(column, quote)
    q_table = _quote_table_name(table, quote)

    # Construct safe exploration query using parameterized queries to prevent
    # SQL injection. Different connectors use different placeholder styles.
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
            # Escape backslashes first to prevent MySQL-style backslash-quote
            # bypass (e.g., \' defeating quote-doubling).
            safe_pattern = filter_pattern.replace("\\", "\\\\").replace("'", "''")
            where_clause = f"WHERE {q_col} {like_op} '{safe_pattern}'"

    # Build the query — dialect-aware LIMIT/TOP
    if db_type == "mssql":
        explore_sql = f"""
SELECT TOP {limit}
    {q_col} AS value,
    COUNT(*) AS [count]
FROM {q_table}
{where_clause}
GROUP BY {q_col}
ORDER BY [count] DESC
"""
    else:
        explore_sql = f"""
SELECT
    {q_col} AS value,
    COUNT(*) AS count
FROM {q_table}
{where_clause}
GROUP BY {q_col}
ORDER BY count DESC
LIMIT {limit}
"""

    # NULL stats query
    null_sql = f"""
SELECT
    COUNT(*) AS total_rows,
    SUM(CASE WHEN {q_col} IS NULL THEN 1 ELSE 0 END) AS null_count,
    COUNT(DISTINCT {q_col}) AS distinct_count
FROM {q_table}
"""

    try:
        extras = await store.get_credential_extras(name)
        async with pool_manager.connection(
            info.db_type, conn_str, credential_extras=extras, connection_name=name
        ) as connector:
            actual_sql = explore_sql

            values_rows = await connector.execute(actual_sql, params=explore_params, timeout=30)
            stats_rows = await connector.execute(null_sql, timeout=30)

        stats = stats_rows[0] if stats_rows else {}
        return {
            "connection_name": name,
            "table": table,
            "column": column,
            "values": [{"value": r.get("value"), "count": r.get("count", 0)} for r in values_rows],
            "statistics": {
                "total_rows": stats.get("total_rows", 0),
                "null_count": stats.get("null_count", 0),
                "distinct_count": stats.get("distinct_count", 0),
                "null_pct": round(stats.get("null_count", 0) / max(stats.get("total_rows", 1), 1) * 100, 1),
            },
            "filter": filter_pattern or None,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=sanitize_db_error(str(e), info.db_type))
