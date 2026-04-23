"""Schema introspection, compression, and agent-context endpoints."""

from __future__ import annotations

import json
import logging
import re
from collections import deque
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from ..connectors.pool_manager import pool_manager
from ..scope_guard import RequireScope
from ..connectors.schema_cache import schema_cache
from ..schema_utils import (
    TYPE_COMPRESSION_MAP,
    STRING_COLUMN_TYPES,
    compress_type,
    _compress_schema,
    _deduplicate_partitioned_tables,
    _group_tables,
    _infer_implicit_joins,
)
from ..store import (
    DATA_DIR,
)
from .deps import (
    StoreD,
    get_filtered_schema,
    get_or_fetch_schema,
    apply_filters,
    require_connection,
    sanitize_db_error,
    get_schema_filters,
    apply_schema_filter,
)

logger = logging.getLogger(__name__)
_re_link = re
_re_refine = re

router = APIRouter(prefix="/api")

# ---------------------------------------------------------------------------
# Semantic model helpers (needed by agent-context endpoint)
# ---------------------------------------------------------------------------

_semantic_models: dict[str, dict] = {}  # connection_name -> model


def _semantic_model_path(name: str):
    """Path to the semantic model JSON file for a connection."""
    return DATA_DIR / f"semantic_{name}.json"


def _load_semantic_model(name: str) -> dict:
    """Load semantic model from disk (cached in memory)."""
    if name in _semantic_models:
        return _semantic_models[name]
    path = _semantic_model_path(name)
    if path.exists():
        try:
            model = json.loads(path.read_text())
            _semantic_models[name] = model
            return model
        except Exception:
            pass
    empty: dict = {"tables": {}, "joins": [], "glossary": {}}
    _semantic_models[name] = empty
    return empty


# ───────────────────────────────────────────────────────────────────────────
# GET /connections/{name}/schema
# ───────────────────────────────────────────────────────────────────────────

@router.get("/connections/{name}/schema", dependencies=[RequireScope("read")])
async def get_connection_schema(
    name: str,
    store: StoreD,
    compact: bool = Query(default=False, description="Return compressed schema optimized for LLM context windows"),
    filter: str = Query(default="", description="Filter tables by name pattern (case-insensitive substring match, comma-separated)"),
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
            async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
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
            k: v for k, v in filtered.items()
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
        async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
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
    tables: str = Query(default="", description="Comma-separated table keys to sample (e.g., 'public.users,public.orders')"),
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
            async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
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
        async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
            samples: dict[str, dict[str, list]] = {}
            for table_key in table_keys:
                if table_key not in cached:
                    continue
                table_info = cached[table_key]
                # Only sample string-like columns (most useful for schema linking)
                sample_cols = [
                    col["name"] for col in table_info.get("columns", [])
                    if col.get("type", "") in STRING_COLUMN_TYPES or "char" in col.get("type", "").lower()
                ]
                if not sample_cols:
                    continue

                table_name = f"{table_info.get('schema', '')}.{table_info['name']}" if table_info.get("schema") else table_info["name"]
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

@router.post("/connections/{name}/schema/explore", dependencies=[RequireScope("write")])
async def explore_column_values(
    name: str,
    store: StoreD,
    table: str = Query(..., description="Full table name (e.g., 'public.users')"),
    column: str = Query(..., description="Column to explore"),
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
    info = await require_connection(store, name)

    conn_str = await store.get_connection_string(name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored")

    db_type = info.db_type
    # Build exploration query with dialect-aware quoting
    quote = '"' if db_type in ("postgres", "redshift", "snowflake", "trino", "duckdb", "sqlite") else '`'
    if db_type == "mssql":
        quote = '['
        close_quote = ']'
    else:
        close_quote = quote

    q_col = f"{quote}{column}{close_quote}"

    # Construct safe exploration query
    parts = []
    if filter_pattern:
        like_op = "ILIKE" if db_type in ("postgres", "redshift", "snowflake") else "LIKE"
        parts.append(f"WHERE {q_col} {like_op} :pattern")

    where_clause = parts[0] if parts else ""

    # Build the query — dialect-aware LIMIT/TOP
    if db_type == "mssql":
        explore_sql = f"""
SELECT TOP {limit}
    {q_col} AS value,
    COUNT(*) AS [count]
FROM {table}
{where_clause}
GROUP BY {q_col}
ORDER BY [count] DESC
"""
    else:
        explore_sql = f"""
SELECT
    {q_col} AS value,
    COUNT(*) AS count
FROM {table}
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
FROM {table}
"""

    try:
        extras = await store.get_credential_extras(name)
        async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
            # Replace :pattern placeholder with parameterized query
            actual_sql = explore_sql.replace(":pattern", f"'{filter_pattern}'") if filter_pattern else explore_sql

            values_rows = await connector.execute(actual_sql, timeout=30)
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


# ───────────────────────────────────────────────────────────────────────────
# GET /connections/{name}/schema/enriched
# ───────────────────────────────────────────────────────────────────────────

@router.get("/connections/{name}/schema/enriched", dependencies=[RequireScope("read")])
async def get_enriched_schema(
    name: str,
    store: StoreD,
    sample_limit: int = Query(default=3, ge=1, le=10, description="Max sample values per column"),
):
    """Return enriched compact schema optimized for Spider2.0 text-to-SQL.

    Combines compact DDL + foreign keys + sample values + statistics in one call.
    This is the recommended endpoint for AI agents — provides everything needed
    for accurate schema linking in a single request with minimal token count.
    """
    info = await require_connection(store, name)

    conn_str = await store.get_connection_string(name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored")

    try:
        extras = await store.get_credential_extras(name)
        async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
            # Get or use cached schema
            cached = schema_cache.get(name)
            if cached is None:
                cached = await connector.get_schema()
                schema_cache.put(name, cached)

            # Apply endorsement filter and schema filters
            filtered = await store.apply_endorsement_filter(name, cached)
            sf_include, sf_exclude = await get_schema_filters(store, name)
            filtered = apply_schema_filter(filtered, sf_include, sf_exclude)

            # ReFoRCE-style: deduplicate partitioned table families
            filtered, partition_map = _deduplicate_partitioned_tables(filtered)

            # Build enriched compact schema
            enriched: dict[str, Any] = {}
            for key, table in filtered.items():
                # Compact DDL
                cols = []
                pk_cols = []
                for col in table.get("columns", []):
                    col_type = col.get("type", "")
                    nullable = "" if col.get("nullable", True) else " NOT NULL"
                    unique_hint = ""
                    stats = col.get("stats", {})
                    if stats.get("distinct_fraction") == -1.0:
                        unique_hint = " UNIQUE"
                    cols.append(f"{col['name']} {col_type}{nullable}{unique_hint}")
                    if col.get("primary_key"):
                        pk_cols.append(col["name"])

                browse_kw = "CREATE VIEW" if table.get("type") == "view" else "CREATE TABLE"
                ddl_parts = [f"{browse_kw} {table.get('schema', '')}.{table['name']} ("]
                ddl_parts.append("  " + ", ".join(cols))
                if pk_cols:
                    ddl_parts.append(f"  PRIMARY KEY ({', '.join(pk_cols)})")
                ddl_parts.append(")")

                fk_refs = []
                for fk in table.get("foreign_keys", []):
                    ref_table = fk.get("references_table", "")
                    if fk.get("references_schema"):
                        ref_table = f"{fk['references_schema']}.{ref_table}"
                    fk_refs.append(f"{fk['column']} -> {ref_table}.{fk.get('references_column', '')}")

                entry: dict[str, Any] = {
                    "ddl": "\n".join(ddl_parts),
                    "row_count": table.get("row_count", 0),
                }
                if fk_refs:
                    entry["foreign_keys"] = fk_refs
                if table.get("indexes"):
                    entry["indexes"] = [idx.get("name", "") for idx in table["indexes"]]
                if table.get("description"):
                    entry["description"] = table["description"]
                # Add partition info for deduplicated table families
                if key in partition_map:
                    entry["_partitions"] = len(partition_map[key])
                    entry["_partition_base"] = table.get("_partition_base", "")

                enriched[key] = entry

            # Sample values (string columns only, limited tables)
            for key in list(enriched.keys())[:15]:  # Cap at 15 tables
                table_info = cached.get(key, {})
                sample_cols = [
                    col["name"] for col in table_info.get("columns", [])
                    if col.get("type", "") in STRING_COLUMN_TYPES or "char" in col.get("type", "").lower()
                ]
                if not sample_cols:
                    continue
                table_name = f"{table_info.get('schema', '')}.{table_info['name']}" if table_info.get("schema") else table_info["name"]
                try:
                    values = await connector.get_sample_values(table_name, sample_cols, limit=sample_limit)
                    if values:
                        enriched[key]["sample_values"] = values
                except Exception:
                    pass

        return {
            "connection_name": name,
            "db_type": info.db_type,
            "table_count": len(enriched),
            "partitioned_families": len(partition_map),
            "tables": enriched,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=sanitize_db_error(str(e), info.db_type))


# ───────────────────────────────────────────────────────────────────────────
# GET /connections/{name}/schema/compact
# ───────────────────────────────────────────────────────────────────────────

@router.get("/connections/{name}/schema/compact", dependencies=[RequireScope("read")])
async def get_compact_schema(
    name: str,
    store: StoreD,
    max_tables: int = Query(default=50, ge=1, le=500, description="Maximum tables to include"),
    include_fk: bool = Query(default=True, description="Include foreign key relationships"),
    include_types: bool = Query(default=True, description="Include column type info"),
    format: str = Query(default="text", pattern="^(text|json)$", description="Output format"),
):
    """Ultra-compact schema representation optimized for LLM context windows.

    Based on EDBT 2026 schema compression research and RSL-SQL bidirectional linking.
    Produces a minimal-token schema that preserves the most important signals:
    - Table and column names (always)
    - Primary keys and foreign keys (high-impact for Spider2.0)
    - Column types (optional, helps with type-aware SQL generation)
    - Row counts (helps agent estimate query cost)

    Text format example:
        public.customers (10000 rows): customer_id* INT, name VARCHAR, email VARCHAR
        public.orders (50000 rows): order_id* INT, customer_id->customers.customer_id INT, total DECIMAL
    """
    info = await require_connection(store, name)

    cached = schema_cache.get(name)
    if cached is None:
        conn_str = await store.get_connection_string(name)
        if not conn_str:
            raise HTTPException(status_code=400, detail="No credentials stored")
        extras = await store.get_credential_extras(name)
        async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
            cached = await connector.get_schema()
            schema_cache.put(name, cached)

    filtered = await store.apply_endorsement_filter(name, cached)
    sf_include, sf_exclude = await get_schema_filters(store, name)
    filtered = apply_schema_filter(filtered, sf_include, sf_exclude)

    # ReFoRCE-style: deduplicate date-partitioned table families before compression
    filtered, partition_map = _deduplicate_partitioned_tables(filtered)

    # Sort tables by relevance: most connected (FK-rich) first, then by row count
    # This ensures the most important join-hub tables appear in truncated schemas
    def _table_relevance(key: str) -> tuple:
        table = filtered[key]
        fk_count = len(table.get("foreign_keys", []))
        row_count = table.get("row_count", 0) or 0
        col_count = len(table.get("columns", []))
        # Higher FK count = higher relevance (join hubs are critical for Spider2.0)
        # Higher row count = higher relevance (larger tables are usually more important)
        return (-fk_count, -row_count, -col_count, key)

    table_keys = sorted(filtered.keys(), key=_table_relevance)[:max_tables]

    # Build FK lookup for compact reference format (explicit + inferred)
    fk_map: dict[str, str] = {}  # table.col -> ref_table.ref_col
    if include_fk:
        for key, table in filtered.items():
            for fk in table.get("foreign_keys", []):
                fk_key = f"{key}.{fk['column']}"
                ref = f"{fk.get('references_table', '')}.{fk.get('references_column', '')}"
                fk_map[fk_key] = ref
        # Add inferred joins
        inferred = _infer_implicit_joins(filtered)
        for inf in inferred:
            inf_from_key = f"{inf['from_schema']}.{inf['from_table']}" if inf["from_schema"] else inf["from_table"]
            fk_key = f"{inf_from_key}.{inf['from_column']}"
            if fk_key not in fk_map:
                ref = f"{inf['to_table']}.{inf['to_column']}"
                fk_map[fk_key] = ref

    if format == "json":
        compact: dict[str, Any] = {}
        for key in table_keys:
            table = filtered[key]
            cols = []
            for col in table.get("columns", []):
                entry: dict[str, Any] = {"n": col["name"]}
                if include_types:
                    entry["t"] = col.get("type", "")
                if col.get("primary_key"):
                    entry["pk"] = True
                fk_ref = fk_map.get(f"{key}.{col['name']}")
                if fk_ref:
                    entry["fk"] = fk_ref
                comment = col.get("comment", "")
                if comment:
                    entry["desc"] = comment
                # Cardinality hints for Spider2.0 query planning
                stats = col.get("stats", {})
                if stats:
                    dc = stats.get("distinct_count", 0)
                    df = abs(stats.get("distinct_fraction", 0))
                    if df == 1.0 or (dc and dc == table.get("row_count", 0) and dc > 100):
                        entry["u"] = True  # unique column
                    elif dc and dc <= 10:
                        entry["lc"] = dc  # low-cardinality with exact count
                cols.append(entry)
            compact[key] = {"c": cols, "r": table.get("row_count", 0)}
            if table.get("size_mb"):
                compact[key]["mb"] = table["size_mb"]
            # Add partition info for deduplicated table families
            if key in partition_map:
                compact[key]["_partitions"] = len(partition_map[key])
                compact[key]["_partition_base"] = table.get("_partition_base", "")
        return {
            "connection_name": name,
            "format": "json",
            "table_count": len(compact),
            "partitioned_families": len(partition_map),
            "token_estimate": sum(len(str(v)) for v in compact.values()) // 4,
            "tables": compact,
        }

    # Text format — optimized for direct LLM consumption
    lines = []
    total_chars = 0
    for key in table_keys:
        table = filtered[key]
        row_count = table.get("row_count", 0)
        size_mb = table.get("size_mb", 0)
        meta_parts = []
        if row_count:
            if row_count >= 1_000_000:
                meta_parts.append(f"{row_count / 1_000_000:.1f}M rows")
            elif row_count >= 1_000:
                meta_parts.append(f"{row_count / 1_000:.0f}K rows")
            else:
                meta_parts.append(f"{row_count} rows")
        if size_mb and size_mb >= 1:
            if size_mb >= 1024:
                meta_parts.append(f"{size_mb / 1024:.1f}GB")
            else:
                meta_parts.append(f"{size_mb:.0f}MB")
        row_str = f" ({', '.join(meta_parts)})" if meta_parts else ""

        col_parts = []
        for col in table.get("columns", []):
            name_str = col["name"]
            if col.get("primary_key"):
                name_str += "*"
            fk_ref = fk_map.get(f"{key}.{col['name']}")
            if fk_ref:
                name_str += f"\u2192{fk_ref}"
            if include_types:
                col_type = compress_type(col.get("type", ""))
                name_str += f" {col_type}"
            # Cardinality hints in text format
            stats = col.get("stats", {})
            if stats:
                dc = stats.get("distinct_count", 0)
                df = abs(stats.get("distinct_fraction", 0))
                if df == 1.0 or (dc and dc == table.get("row_count", 0) and dc > 100):
                    name_str += "!"  # unique marker
                elif dc and dc <= 10:
                    name_str += f"~{dc}"  # low-cardinality count
            col_parts.append(name_str)

        # Add partition annotation for deduplicated table families
        partition_note = ""
        if key in partition_map:
            count = len(partition_map[key])
            base = table.get("_partition_base", "")
            partition_note = f" [\u00d7{count} partitions: {base}_*]"

        line = f"{key}{row_str}{partition_note}: {', '.join(col_parts)}"
        lines.append(line)
        total_chars += len(line)

    schema_text = "\n".join(lines)
    return {
        "connection_name": name,
        "format": "text",
        "table_count": len(lines),
        "partitioned_families": len(partition_map),
        "token_estimate": total_chars // 4,
        "schema": schema_text,
    }


# ───────────────────────────────────────────────────────────────────────────
# GET /connections/{name}/schema/ddl
# ───────────────────────────────────────────────────────────────────────────

@router.get("/connections/{name}/schema/ddl", dependencies=[RequireScope("read")])
async def get_schema_ddl(
    name: str,
    store: StoreD,
    max_tables: int = Query(default=50, ge=1, le=500, description="Maximum tables to include"),
    include_fk: bool = Query(default=True, description="Include foreign key constraints"),
    compress: bool = Query(default=False, description="Enable ReFoRCE-style table grouping for large schemas"),
):
    """CREATE TABLE DDL representation of the schema.

    Spider2.0 SOTA systems (DAIL-SQL, DIN-SQL, CHESS) found that CREATE TABLE
    DDL format outperforms list/JSON formats for text-to-SQL accuracy because:
    1. LLMs have seen massive amounts of DDL in training data
    2. DDL naturally encodes constraints (PK, FK, NOT NULL)
    3. DDL is compact and unambiguous

    Example output:
        CREATE TABLE public.customers (
            customer_id INT PRIMARY KEY,
            name VARCHAR NOT NULL,
            email VARCHAR
        );
    """
    info = await require_connection(store, name)

    cached = schema_cache.get(name)
    if cached is None:
        conn_str = await store.get_connection_string(name)
        if not conn_str:
            raise HTTPException(status_code=400, detail="No credentials stored")
        extras = await store.get_credential_extras(name)
        async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
            cached = await connector.get_schema()
        schema_cache.put(name, cached)

    filtered = await store.apply_endorsement_filter(name, cached)
    sf_include, sf_exclude = await get_schema_filters(store, name)
    filtered = apply_schema_filter(filtered, sf_include, sf_exclude)

    # ReFoRCE-style: deduplicate partitioned table families
    filtered, _partition_map = _deduplicate_partitioned_tables(filtered)

    # Sort by FK relevance (same as compact)
    def _table_relevance(key: str) -> tuple:
        table = filtered[key]
        fk_count = len(table.get("foreign_keys", []))
        row_count = table.get("row_count", 0) or 0
        return (-fk_count, -row_count, key)

    table_keys = sorted(filtered.keys(), key=_table_relevance)[:max_tables]

    # Build FK lookup
    fk_map: dict[str, str] = {}
    if include_fk:
        for key, table in filtered.items():
            for fk in table.get("foreign_keys", []):
                fk_key = f"{key}.{fk['column']}"
                ref = f"{fk.get('references_table', '')}.{fk.get('references_column', '')}"
                fk_map[fk_key] = ref

    # ReFoRCE-style table grouping: merge similar-prefix tables, show one DDL per group
    # This dramatically reduces token usage for large schemas (300KB+ DDL -> fits in context)
    grouped_tables: set[str] = set()  # Keys that are compressed (show name only)
    group_representatives: dict[str, list[str]] = {}  # representative_key -> [member_names]
    if compress and len(table_keys) > 15:
        # Extract common prefixes (e.g., "stg_", "dim_", "fact_", "raw_")
        prefix_groups: dict[str, list[str]] = {}
        for key in table_keys:
            tname = filtered[key].get("name", "")
            # Find prefix: everything before first underscore that appears in 3+ tables
            match = re.match(r'^([a-zA-Z]+_)', tname)
            if match:
                prefix = match.group(1)
                if prefix not in prefix_groups:
                    prefix_groups[prefix] = []
                prefix_groups[prefix].append(key)

        for prefix, members in prefix_groups.items():
            if len(members) >= 3:
                # Pick the member with most columns as representative
                rep = max(members, key=lambda k: len(filtered[k].get("columns", [])))
                others = [k for k in members if k != rep]
                group_representatives[rep] = [filtered[k].get("name", "") for k in others]
                grouped_tables.update(others)

        # Remove grouped tables from table_keys
        table_keys = [k for k in table_keys if k not in grouped_tables]

    ddl_statements = []
    for key in table_keys:
        table = filtered[key]
        # Use schema-qualified name
        table_name = f"{table.get('schema', '')}.{table.get('name', '')}"

        # Table-level comment with metadata (helps agent plan queries)
        table_desc = table.get("description", "")
        meta_hints = []
        if table.get("row_count"):
            rc = table["row_count"]
            meta_hints.append(f"{rc / 1_000_000:.1f}M rows" if rc >= 1_000_000
                             else f"{rc / 1_000:.0f}K rows" if rc >= 1000
                             else f"{rc} rows")
        if table.get("size_mb") and table["size_mb"] >= 1:
            sm = table["size_mb"]
            meta_hints.append(f"{sm / 1024:.1f}GB" if sm >= 1024 else f"{sm:.0f}MB")
        if table.get("engine"):
            meta_hints.append(table["engine"])
        header_parts = [p for p in [table_desc, ", ".join(meta_hints)] if p]
        table_header = f"-- {' | '.join(header_parts)}\n" if header_parts else ""

        col_lines = []
        pk_cols = []
        for col in table.get("columns", []):
            col_type = compress_type(col.get("type", "TEXT"))
            parts = [f"  {col['name']} {col_type}"]
            if not col.get("nullable", True):
                parts.append("NOT NULL")
            # Inline column annotations (semantic hints for agent)
            annotations = []
            col_comment = col.get("comment", "")
            if col_comment:
                annotations.append(col_comment)
            # Redshift: distribution key and encoding hints
            if col.get("dist_key"):
                annotations.append("DISTKEY")
            if col.get("sort_key_position"):
                annotations.append(f"SORTKEY#{col['sort_key_position']}")
            # ClickHouse: low cardinality columns
            if col.get("low_cardinality"):
                annotations.append("LOW_CARDINALITY")
            # Cardinality hint for query planning
            stats = col.get("stats", {})
            if stats.get("distinct_count") is not None and stats["distinct_count"] > 0:
                dc = stats["distinct_count"]
                if dc <= 10:
                    annotations.append(f"{dc} distinct values")
                elif dc <= 1000:
                    annotations.append(f"{dc} distinct values")
                else:
                    annotations.append("high cardinality")
            elif stats.get("distinct_fraction") is not None:
                frac = abs(stats["distinct_fraction"])
                if frac == 1.0:
                    annotations.append("unique")
                elif frac > 0.5:
                    annotations.append("high cardinality")
                elif frac > 0 and frac <= 0.01:
                    annotations.append("low cardinality")
            # Inline sample values for low-cardinality columns
            is_low_card = False
            dc = stats.get("distinct_count", 0) if stats else 0
            df = abs(stats.get("distinct_fraction", 0)) if stats else 0
            if dc and dc <= 50:
                is_low_card = True
            elif df and df < 0.05:
                is_low_card = True
            elif not stats:
                is_low_card = True
            if is_low_card:
                cached_samples = schema_cache.get_sample_values(name, key)
                if cached_samples and col["name"] in cached_samples:
                    sample_vals = cached_samples[col["name"]]
                    if len(sample_vals) <= 10:
                        annotations.append(f"e.g. {', '.join(repr(v) for v in sample_vals[:5])}")
            if annotations:
                parts.append(f"-- {'; '.join(annotations)}")
            col_lines.append(" ".join(parts))
            if col.get("primary_key"):
                pk_cols.append(col["name"])

        # Add PK constraint
        if pk_cols:
            col_lines.append(f"  PRIMARY KEY ({', '.join(pk_cols)})")

        # Add FK constraints
        if include_fk:
            for fk in table.get("foreign_keys", []):
                ref_table = fk.get("references_table", "")
                ref_col = fk.get("references_column", "")
                col_lines.append(f"  FOREIGN KEY ({fk['column']}) REFERENCES {ref_table}({ref_col})")

        # Build row comment with metadata
        comment_parts = []
        rc = table.get("row_count", 0)
        if rc:
            comment_parts.append(f"{rc:,} rows" if rc < 1_000_000 else f"{rc/1_000_000:.1f}M rows")
        # ClickHouse-specific: engine and sorting key (critical for query optimization)
        engine = table.get("engine", "")
        if engine:
            comment_parts.append(f"ENGINE={engine}")
        sorting_key = table.get("sorting_key", "")
        if sorting_key:
            comment_parts.append(f"ORDER BY({sorting_key})")
        # Redshift-specific: distribution style + sort key
        dist_style = table.get("diststyle", "")
        if dist_style:
            comment_parts.append(f"DISTSTYLE={dist_style}")
        sort_key = table.get("sortkey", "")
        if sort_key:
            comment_parts.append(f"SORTKEY({sort_key})")
        # Snowflake-specific: clustering key
        clustering_key = table.get("clustering_key", "")
        if clustering_key:
            comment_parts.append(f"CLUSTER BY({clustering_key})")
        # BigQuery-specific: partitioning and clustering
        partitioning = table.get("partitioning", {})
        if partitioning and partitioning.get("field"):
            comment_parts.append(f"PARTITION BY {partitioning['field']}")
        clustering = table.get("clustering_fields", [])
        if clustering:
            comment_parts.append(f"CLUSTER BY({', '.join(clustering)})")
        row_comment = f" -- {', '.join(comment_parts)}" if comment_parts else ""

        obj_keyword = "CREATE VIEW" if table.get("type") == "view" else "CREATE TABLE"
        ddl = f"{table_header}{obj_keyword} {table_name} (\n" + ",\n".join(col_lines) + f"\n);{row_comment}"

        # Append group member list if this is a representative table
        if key in group_representatives:
            members = group_representatives[key]
            ddl += f"\n-- Similar tables (same structure): {', '.join(members)}"

        ddl_statements.append(ddl)

    ddl_text = "\n\n".join(ddl_statements)
    compressed_count = len(grouped_tables) if compress else 0
    return {
        "connection_name": name,
        "format": "ddl",
        "table_count": len(ddl_statements),
        "compressed_tables": compressed_count,
        "total_tables_represented": len(ddl_statements) + compressed_count,
        "token_estimate": len(ddl_text) // 4,
        "ddl": ddl_text,
    }


# ───────────────────────────────────────────────────────────────────────────
# GET /connections/{name}/schema/agent-context
# ───────────────────────────────────────────────────────────────────────────

@router.get("/connections/{name}/schema/agent-context", dependencies=[RequireScope("read")])
async def get_agent_context(
    name: str,
    store: StoreD,
    question: str = Query(default="", description="Optional question for schema linking — omit for full schema"),
    max_tables: int = Query(default=30, ge=1, le=100, description="Max tables to include"),
    include_samples: bool = Query(default=True, description="Include cached sample values for string columns"),
    progressive: bool = Query(default=False, description="Progressive disclosure: full DDL for top tables, compact one-liners for the rest (saves 40-60%% tokens)"),
    full_ddl_count: int = Query(default=8, ge=1, le=50, description="Number of top-scoring tables to show full DDL for (when progressive=true)"),
):
    """Single-call schema context optimized for SQL generation agents (Spider2.0 pattern).

    Combines DDL schema, join relationships, table metadata, and sample values
    into a single prompt-ready text block. Designed to be pasted directly into
    an LLM system prompt for text-to-SQL tasks.

    When progressive=true:
    - Top-scoring tables get full DDL with columns, PKs, FKs, samples
    - Remaining tables get compact one-liners (name, column count, PKs, FKs)
    - This saves 40-60% tokens while preserving join path information
    - Mimics the two-pass approach used by CHESS and DIN-SQL (Spider2.0 SOTA)

    Based on Spider2.0 SOTA findings:
    - DDL format preferred by top performers (Genloop, QUVI, Databao)
    - Sample values critical for schema linking (3-4% EX improvement)
    - Inferred joins fill gaps in FK-free databases (ClickHouse, BigQuery)
    - Progressive disclosure: broad recall + focused detail (CHESS pattern)
    """
    info = await require_connection(store, name)

    cached = schema_cache.get(name)
    if cached is None:
        conn_str = await store.get_connection_string(name)
        if not conn_str:
            raise HTTPException(status_code=400, detail="No credentials stored")
        extras = await store.get_credential_extras(name)
        async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
            cached = await connector.get_schema()
        schema_cache.put(name, cached)

    filtered = await store.apply_endorsement_filter(name, cached)
    sf_include, sf_exclude = await get_schema_filters(store, name)
    filtered = apply_schema_filter(filtered, sf_include, sf_exclude)

    # ReFoRCE-style: deduplicate date-partitioned table families
    # This is the single most impactful compression step per ReFoRCE ablation
    filtered, _partition_map = _deduplicate_partitioned_tables(filtered)

    # If a question is provided, use schema linking to select relevant tables
    table_scores: dict[str, float] = {}
    if question:
        # Reuse the schema link logic inline to select top tables
        stopwords = {"the", "and", "for", "are", "but", "not", "you", "all", "can", "had",
                     "her", "was", "one", "our", "out", "has", "how", "many", "much",
                     "what", "which", "show", "find", "list", "give", "tell",
                     "from", "with", "that", "this", "have", "will",
                     "select", "where", "group", "having", "limit", "table", "column", "database"}
        terms = [w for w in re.findall(r'[a-zA-Z_][a-zA-Z0-9_]*', question.lower()) if len(w) >= 3 and w not in stopwords]
        for key, t in filtered.items():
            score = 0.0
            tn = t.get("name", "").lower()
            for term in terms:
                if term == tn or term == tn.rstrip("s"):
                    score += 10.0
                elif term in tn:
                    score += 3.0
                for col in t.get("columns", []):
                    cn = col.get("name", "").lower()
                    if term == cn:
                        score += 4.0
                    elif term in cn:
                        score += 1.5
            table_scores[key] = score
        # Select tables with score > 0, plus their FK-connected tables
        linked = {k for k, s in table_scores.items() if s > 0}
        fk_adds = set()
        for k in list(linked):
            for fk in filtered.get(k, {}).get("foreign_keys", []):
                for ck in filtered:
                    if filtered[ck].get("name") == fk.get("references_table"):
                        fk_adds.add(ck)
        linked |= fk_adds
        if not linked:
            linked = set(list(filtered.keys())[:max_tables])
        filtered = {k: filtered[k] for k in sorted(linked)[:max_tables] if k in filtered}

    # Load semantic model for enrichment (HEX pattern)
    semantic = _load_semantic_model(name)

    # Build context sections
    sections: list[str] = []

    # Section 1: Database info header
    total_rows = sum(t.get("row_count", 0) or 0 for t in filtered.values())
    total_mb = sum(t.get("size_mb", 0) or 0 for t in filtered.values())
    sections.append(f"-- Database: {name} ({info.db_type})")
    sections.append(f"-- Tables: {len(filtered)}, Total rows: {total_rows:,}, Total size: {total_mb:.1f} MB")
    sections.append("")

    # Section 0.5: Business glossary — only show terms relevant to the question or tables
    glossary = semantic.get("glossary", {})
    if glossary:
        # Filter glossary to terms that reference included tables
        table_names = {t.get("name", "").lower() for t in filtered.values()}
        relevant_glossary = {}
        # Extract question terms for matching (reuse if already parsed)
        q_terms = [w.lower() for w in re.findall(r'[a-zA-Z_][a-zA-Z0-9_]*', question)] if question else []
        for term, col_ref in glossary.items():
            ref_lower = col_ref.lower()
            # Include if the column reference mentions a table we're showing
            for tname in table_names:
                if tname and tname in ref_lower:
                    relevant_glossary[term] = col_ref
                    break
            # Also include if a question term matches the glossary term
            if question and term not in relevant_glossary:
                for qterm in q_terms:
                    if qterm in term.lower():
                        relevant_glossary[term] = col_ref
                        break
        if relevant_glossary:
            glossary_lines = ["-- === Business Glossary ==="]
            for term, col_ref in sorted(relevant_glossary.items())[:25]:
                glossary_lines.append(f"-- {term} = {col_ref}")
            sections.append("\n".join(glossary_lines))
            sections.append("")

    # Section 2: DDL with inline metadata
    inferred = _infer_implicit_joins(filtered)
    inferred_map: dict[str, list[dict]] = {}
    for ij in inferred:
        key = f"{ij['from_schema']}.{ij['from_table']}" if ij.get("from_schema") else ij["from_table"]
        if key not in inferred_map:
            inferred_map[key] = []
        inferred_map[key].append(ij)

    # Semantic join hints from model
    semantic_joins = semantic.get("joins", [])

    # Progressive disclosure: determine which tables get full DDL vs compact summary
    # Top-scoring tables get full DDL; the rest get a one-liner with PKs/FKs only
    full_ddl_keys: set[str] = set()
    compact_keys: set[str] = set()
    if progressive and question:
        # Sort by score (from schema linking above), take top N for full DDL
        scored = sorted(filtered.keys(), key=lambda k: table_scores.get(k, 0), reverse=True)
        full_ddl_keys = set(scored[:full_ddl_count])
        compact_keys = set(scored[full_ddl_count:])
    elif progressive:
        # No question — just use the first N tables alphabetically
        all_keys = sorted(filtered.keys())
        full_ddl_keys = set(all_keys[:full_ddl_count])
        compact_keys = set(all_keys[full_ddl_count:])
    else:
        full_ddl_keys = set(filtered.keys())

    # Compact section for low-scoring tables (progressive mode)
    if compact_keys:
        compact_lines = ["-- === Additional Tables (compact) ==="]
        for key in sorted(compact_keys):
            table = filtered[key]
            table_name = f"{table.get('schema', '')}.{table['name']}" if table.get("schema") else table["name"]
            cols = table.get("columns", [])
            pks = [c["name"] for c in cols if c.get("primary_key")]
            fks = table.get("foreign_keys", [])
            rc = table.get("row_count", 0) or 0
            parts = [f"{len(cols)} cols"]
            if rc:
                parts.append(f"{rc:,} rows")
            if pks:
                parts.append(f"PK: {','.join(pks)}")
            for fk in fks:
                ref = fk.get("references_table", "?")
                parts.append(f"FK: {fk.get('column', '?')}\u2192{ref}")
            for ij in inferred_map.get(key, []):
                parts.append(f"join: {ij['from_column']}\u2192{ij['to_table']}")
            compact_lines.append(f"-- {table_name} ({', '.join(parts)})")
        sections.append("\n".join(compact_lines))
        sections.append("")

    # Full DDL section for top-scoring tables
    if full_ddl_keys and compact_keys:
        sections.append("-- === Detailed Schema (top tables) ===")

    for key in sorted(full_ddl_keys):
        table = filtered[key]
        table_name = f"{table.get('schema', '')}.{table['name']}" if table.get("schema") else table["name"]
        rc = table.get("row_count", 0) or 0
        size = table.get("size_mb", 0) or 0
        meta_parts = []
        if rc:
            meta_parts.append(f"{rc:,} rows")
        if size:
            meta_parts.append(f"{size:.1f} MB")
        # Semantic model description overrides database comment
        sem_table = semantic.get("tables", {}).get(key, {})
        desc = sem_table.get("description", "") or table.get("description", "")
        if desc:
            meta_parts.append(desc)
        if progressive and question:
            score = table_scores.get(key, 0)
            if score > 0:
                meta_parts.append(f"relevance={score:.1f}")
        meta_comment = f" -- {', '.join(meta_parts)}" if meta_parts else ""

        obj_kw = "CREATE VIEW" if table.get("type") == "view" else "CREATE TABLE"
        col_lines = []
        sem_cols = sem_table.get("columns", {})
        for col in table.get("columns", []):
            ct = col.get("type", "").upper()
            nn = " NOT NULL" if not col.get("nullable", True) else ""
            # Semantic column description overrides database comment
            sem_col = sem_cols.get(col["name"], {})
            comment = sem_col.get("description", "") or col.get("comment", "")
            # Add business name if different from column name
            biz_name = sem_col.get("business_name", "")
            if biz_name and biz_name.lower() != col["name"].lower().replace("_", " "):
                comment = f"{biz_name}: {comment}" if comment else biz_name
            # Add unit annotation
            unit = sem_col.get("unit", "")
            if unit:
                comment = f"{comment} ({unit})" if comment else f"({unit})"
            comment_str = f" -- {comment}" if comment else ""
            col_lines.append(f"  {col['name']} {ct}{nn}{comment_str}")

        # PKs
        pks = [col["name"] for col in table.get("columns", []) if col.get("primary_key")]
        if pks:
            col_lines.append(f"  PRIMARY KEY ({', '.join(pks)})")

        # Explicit FKs
        for fk in table.get("foreign_keys", []):
            ref = f"{fk.get('references_schema', '')}.{fk['references_table']}" if fk.get("references_schema") else fk["references_table"]
            col_lines.append(f"  FOREIGN KEY ({fk['column']}) REFERENCES {ref}({fk['references_column']})")

        # Inferred FKs
        for ij in inferred_map.get(key, []):
            ref = f"{ij.get('to_schema', '')}.{ij['to_table']}" if ij.get("to_schema") else ij["to_table"]
            col_lines.append(f"  -- inferred join: {ij['from_column']} -> {ref}({ij['to_column']})")

        # Semantic join hints from model (curated by user)
        for sj in semantic_joins:
            sj_from = sj.get("from", "")
            if sj_from.startswith(f"{key}.") or sj_from.startswith(f"{table_name}."):
                join_type = sj.get("type", "")
                join_desc = sj.get("description", "")
                hint = f"  -- join hint: {sj_from} -> {sj.get('to', '')}"
                if join_type:
                    hint += f" ({join_type})"
                if join_desc:
                    hint += f" -- {join_desc}"
                col_lines.append(hint)

        ddl = f"{obj_kw} {table_name} (\n" + ",\n".join(col_lines) + f"\n);{meta_comment}"
        sections.append(ddl)

    # Section 3: Sample values (if cached and requested)
    if include_samples:
        sample_sections: list[str] = []
        for key in sorted(filtered.keys()):
            samples = schema_cache.get_sample_values(name, key)
            if samples:
                lines = [f"-- Sample values for {key}:"]
                for col_name, vals in samples.items():
                    lines.append(f"--   {col_name}: {', '.join(repr(v) for v in vals[:5])}")
                sample_sections.append("\n".join(lines))
        if sample_sections:
            sections.append("")
            sections.append("-- === Sample Values ===")
            sections.extend(sample_sections)

    context_text = "\n\n".join(sections)
    result = {
        "connection_name": name,
        "db_type": info.db_type,
        "table_count": len(filtered),
        "token_estimate": len(context_text) // 4,
        "has_question_filter": bool(question),
        "context": context_text,
    }
    if progressive:
        result["progressive"] = {
            "full_ddl_tables": len(full_ddl_keys),
            "compact_tables": len(compact_keys),
            "full_ddl_count_param": full_ddl_count,
        }
    return result


# ───────────────────────────────────────────────────────────────────────────
# Helper: _build_join_hints
# ───────────────────────────────────────────────────────────────────────────

def _build_join_hints(linked_keys: set[str], filtered: dict[str, Any]) -> list[str]:
    """Build FK-based and inferred join hints between linked tables."""
    join_hints: list[str] = []
    _seen_joins: set[tuple] = set()
    for key in linked_keys:
        if key not in filtered:
            continue
        t = filtered[key]
        for fk in t.get("foreign_keys", []):
            ref_table = fk.get("references_table", "")
            ref_col = fk.get("references_column", "")
            fk_col = fk.get("column", "")
            for ref_key in linked_keys:
                if filtered.get(ref_key, {}).get("name", "") == ref_table:
                    pair = tuple(sorted([key, ref_key]))
                    if pair not in _seen_joins:
                        _seen_joins.add(pair)
                        join_hints.append(f"{t['name']}.{fk_col} = {ref_table}.{ref_col}")
                    break
    inferred = _infer_implicit_joins(filtered)
    for ij in inferred:
        from_name, to_name = ij.get("from_table", ""), ij.get("to_table", "")
        from_col, to_col = ij.get("from_column", ""), ij.get("to_column", "")
        from_in = any(filtered.get(k, {}).get("name", "") == from_name for k in linked_keys)
        to_in = any(filtered.get(k, {}).get("name", "") == to_name for k in linked_keys)
        if from_in and to_in:
            hint = f"{from_name}.{from_col} = {to_name}.{to_col} (inferred)"
            if hint not in join_hints:
                join_hints.append(hint)
    return join_hints


# ── Dialect hints (Spider2.0 multi-database optimization) ─────────────────
# Tells the agent which SQL dialect to use and common pitfalls.
_DIALECT_HINTS: dict[str, dict[str, Any]] = {
    "postgres": {
        "dialect": "PostgreSQL",
        "identifier_quote": '"',
        "string_quote": "'",
        "limit_syntax": "LIMIT n OFFSET m",
        "date_functions": "NOW(), CURRENT_DATE, DATE_TRUNC('month', col), EXTRACT(YEAR FROM col)",
        "string_functions": "CONCAT(a, b), LOWER(), UPPER(), LENGTH(), SUBSTRING()",
        "tips": ["Use :: for type casting (e.g., col::TEXT)", "ILIKE for case-insensitive LIKE"],
    },
    "mysql": {
        "dialect": "MySQL",
        "identifier_quote": "`",
        "string_quote": "'",
        "limit_syntax": "LIMIT n OFFSET m",
        "date_functions": "NOW(), CURDATE(), DATE_FORMAT(col, '%Y-%m'), YEAR(col), MONTH(col)",
        "string_functions": "CONCAT(a, b), LOWER(), UPPER(), LENGTH(), SUBSTRING()",
        "tips": ["Use backticks for reserved words", "GROUP BY is strict — list all non-aggregated columns"],
    },
    "mssql": {
        "dialect": "T-SQL (SQL Server)",
        "identifier_quote": "[]",
        "string_quote": "'",
        "limit_syntax": "TOP n or OFFSET m ROWS FETCH NEXT n ROWS ONLY",
        "date_functions": "GETDATE(), CAST(col AS DATE), DATEPART(YEAR, col), DATEDIFF(DAY, a, b), FORMAT(col, 'yyyy-MM')",
        "string_functions": "CONCAT(a, b), LOWER(), UPPER(), LEN(), SUBSTRING()",
        "tips": ["Use TOP n instead of LIMIT", "Use OFFSET...FETCH for pagination", "Use [] for reserved words"],
    },
    "redshift": {
        "dialect": "Redshift (PostgreSQL-based)",
        "identifier_quote": '"',
        "string_quote": "'",
        "limit_syntax": "LIMIT n OFFSET m",
        "date_functions": "GETDATE(), CURRENT_DATE, DATE_TRUNC('month', col), EXTRACT(YEAR FROM col), DATEDIFF(day, a, b)",
        "string_functions": "CONCAT(a, b), LOWER(), UPPER(), LEN(), SUBSTRING()",
        "tips": ["PostgreSQL-like but no LATERAL joins", "Use APPROXIMATE COUNT(DISTINCT) for large tables"],
    },
    "snowflake": {
        "dialect": "Snowflake SQL",
        "identifier_quote": '"',
        "string_quote": "'",
        "limit_syntax": "LIMIT n OFFSET m",
        "date_functions": "CURRENT_TIMESTAMP(), CURRENT_DATE(), DATE_TRUNC('month', col), EXTRACT(YEAR FROM col), DATEDIFF('day', a, b)",
        "string_functions": "CONCAT(a, b), LOWER(), UPPER(), LENGTH(), SUBSTR()",
        "tips": ["Identifiers are case-insensitive unless double-quoted", "Use FLATTEN() for semi-structured data", "QUALIFY for window function filtering"],
    },
    "bigquery": {
        "dialect": "BigQuery Standard SQL",
        "identifier_quote": "`",
        "string_quote": "'",
        "limit_syntax": "LIMIT n OFFSET m",
        "date_functions": "CURRENT_TIMESTAMP(), CURRENT_DATE(), DATE_TRUNC(col, MONTH), EXTRACT(YEAR FROM col)",
        "string_functions": "CONCAT(a, b), LOWER(), UPPER(), LENGTH(), SUBSTR()",
        "tips": ["Use backticks for project.dataset.table references", "Use UNNEST() for repeated fields", "QUALIFY for window filtering"],
    },
    "clickhouse": {
        "dialect": "ClickHouse SQL",
        "identifier_quote": '"',
        "string_quote": "'",
        "limit_syntax": "LIMIT n OFFSET m",
        "date_functions": "now(), today(), toStartOfMonth(col), toYear(col), dateDiff('day', a, b)",
        "string_functions": "concat(a, b), lower(), upper(), length(), substring()",
        "tips": ["Functions are case-sensitive and camelCase", "Use -If suffix for conditional aggregation (e.g., countIf, sumIf)", "Array functions: arrayJoin, groupArray"],
    },
    "trino": {
        "dialect": "Trino SQL (ANSI-based)",
        "identifier_quote": '"',
        "string_quote": "'",
        "limit_syntax": "LIMIT n OFFSET m",
        "date_functions": "CURRENT_TIMESTAMP, CURRENT_DATE, DATE_TRUNC('month', col), EXTRACT(YEAR FROM col)",
        "string_functions": "CONCAT(a, b), LOWER(), UPPER(), LENGTH(), SUBSTR()",
        "tips": ["Use catalog.schema.table for cross-catalog queries", "UNNEST() for arrays", "Supports ANSI SQL window functions"],
    },
    "databricks": {
        "dialect": "Databricks SQL (Spark SQL-based)",
        "identifier_quote": "`",
        "string_quote": "'",
        "limit_syntax": "LIMIT n",
        "date_functions": "CURRENT_TIMESTAMP(), CURRENT_DATE(), DATE_TRUNC('MONTH', col), EXTRACT(YEAR FROM col)",
        "string_functions": "CONCAT(a, b), LOWER(), UPPER(), LENGTH(), SUBSTRING()",
        "tips": ["Use backticks for identifiers", "Supports QUALIFY for window filtering", "Use catalog.schema.table for Unity Catalog"],
    },
    "duckdb": {
        "dialect": "DuckDB SQL (PostgreSQL-compatible)",
        "identifier_quote": '"',
        "string_quote": "'",
        "limit_syntax": "LIMIT n OFFSET m",
        "date_functions": "NOW(), CURRENT_DATE, DATE_TRUNC('month', col), EXTRACT(YEAR FROM col), DATE_DIFF('day', a, b)",
        "string_functions": "CONCAT(a, b), LOWER(), UPPER(), LENGTH(), SUBSTRING()",
        "tips": ["Very PostgreSQL-compatible", "Supports LIST and STRUCT types", "PIVOT/UNPIVOT supported natively"],
    },
}


@router.get("/connections/{name}/schema/link", dependencies=[RequireScope("read")])
async def schema_link(
    name: str,
    store: StoreD,
    question: str = Query(..., description="Natural language question to link schema for"),
    format: str = Query(default="ddl", pattern="^(ddl|compact|json|condensed)$", description="Output format: ddl (full), condensed (pruned columns), compact (one-line), json"),
    max_tables: int = Query(default=20, ge=1, le=100, description="Max tables in linked schema"),
    prune_columns: bool = Query(default=False, description="Drop columns with 0 relevance from low-scoring tables (reduces token count 30-60%%)"),
):
    """Smart schema linking — find tables and columns relevant to a natural language question.

    Implements high-recall schema linking optimized for Spider2.0:
    1. Tokenizes the question into meaningful terms
    2. Matches terms against table names, column names, and comments
    3. Includes FK-connected tables for join path completeness
    4. Returns linked schema in DDL format (preferred by SOTA systems)

    Based on EDBT 2026 research: recall matters more than precision for schema linking.
    Better to include extra tables than miss a relevant one.
    """
    info = await require_connection(store, name)
    filtered = await get_filtered_schema(store, name, info)

    # ── Small-schema bypass (OpenReview "Death of Schema Linking?" finding) ──
    # When the full schema is small enough to fit the context window, skip scoring
    # and include all tables. SOTA systems achieve higher accuracy this way because
    # they can never miss a relevant table. Threshold: ≤ max_tables tables.
    total_columns = sum(len(t.get("columns", [])) for t in filtered.values())
    _small_schema = len(filtered) <= max_tables and total_columns <= 500

    # Step 1: Tokenize question into search terms
    # Extract meaningful words (3+ chars, not common SQL/English stopwords)
    stopwords = {
        "the", "and", "for", "are", "but", "not", "you", "all", "can", "had",
        "her", "was", "one", "our", "out", "has", "how", "man", "new", "now",
        "old", "see", "way", "who", "did", "get", "has", "him", "his", "let",
        "say", "she", "too", "use", "what", "which", "show", "find", "list",
        "give", "tell", "many", "much", "each", "every", "from", "with", "that",
        "this", "have", "will", "your", "they", "been", "more", "when", "make",
        "like", "very", "just", "than", "them", "some", "would", "could",
        "select", "where", "group", "having", "limit",
        "result", "table", "column", "database", "query", "display", "retrieve",
    }
    # Semantic synonyms for common business/analytical terms that map to column names
    # This improves recall when the question uses different words than the schema
    _synonyms: dict[str, list[str]] = {
        "spending": ["amount", "total", "payment", "cost", "price", "revenue"],
        "revenue": ["amount", "total", "sales", "income", "price"],
        "bought": ["order", "purchase", "transaction"],
        "sold": ["order", "sale", "transaction"],
        "profit": ["margin", "revenue", "cost", "amount"],
        "expensive": ["price", "cost", "amount"],
        "cheapest": ["price", "cost", "amount"],
        "latest": ["date", "time", "created", "updated", "recent"],
        "oldest": ["date", "time", "created"],
        "biggest": ["count", "total", "amount", "size"],
        "active": ["status", "is_active", "enabled"],
        "inactive": ["status", "is_active", "enabled"],
        "location": ["city", "state", "country", "region", "address", "zip"],
        "address": ["city", "state", "country", "zip", "address_line"],
        "employee": ["staff", "worker", "user", "agent"],
        "customer": ["client", "buyer", "account", "user"],
        "product": ["item", "sku", "goods", "inventory"],
        "category": ["type", "group", "segment", "class"],
        "average": ["avg", "mean"],
        "monthly": ["month", "date"],
        "yearly": ["year", "date", "annual"],
        "daily": ["day", "date"],
        "payment": ["amount", "transaction", "charge", "invoice"],
        "shipping": ["shipment", "delivery", "tracking", "freight"],
        "discount": ["promo", "coupon", "rebate", "reduction"],
        "name": ["title", "label", "description"],
        "total": ["sum", "amount", "aggregate", "count"],
        "count": ["number", "total", "quantity"],
        "quantity": ["qty", "count", "amount", "units"],
        "percentage": ["percent", "rate", "ratio", "fraction"],
        "rank": ["position", "order", "rank", "rating"],
        "department": ["dept", "division", "team", "group", "unit"],
        "salary": ["wage", "pay", "compensation", "income", "earning"],
        "manager": ["supervisor", "boss", "lead", "head"],
        "country": ["nation", "region", "territory", "geo"],
        "city": ["town", "municipality", "location"],
        "email": ["mail", "contact", "address"],
        "phone": ["tel", "telephone", "mobile", "contact"],
        "created": ["created_at", "date", "timestamp", "registered"],
        "updated": ["modified", "changed", "last_modified"],
        "deleted": ["removed", "archived", "inactive"],
        "stock": ["inventory", "supply", "quantity", "available"],
        "supplier": ["vendor", "provider", "manufacturer"],
        "invoice": ["bill", "receipt", "statement", "charge"],
        "order": ["purchase", "transaction", "booking", "request"],
    }
    question_lower = question.lower()
    terms = [w for w in _re_link.findall(r'[a-zA-Z_][a-zA-Z0-9_]*', question_lower) if len(w) >= 3 and w not in stopwords]

    # N-gram extraction: combine adjacent terms into compound matches
    # "order items" should match "order_items" table, "customer address" → "customer_address"
    raw_terms = [w for w in _re_link.findall(r'[a-zA-Z_][a-zA-Z0-9_]*', question_lower) if len(w) >= 2 and w not in stopwords]
    ngram_terms: list[str] = []
    for i in range(len(raw_terms) - 1):
        bigram = f"{raw_terms[i]}_{raw_terms[i + 1]}"
        ngram_terms.append(bigram)
        if i + 2 < len(raw_terms):
            trigram = f"{raw_terms[i]}_{raw_terms[i + 1]}_{raw_terms[i + 2]}"
            ngram_terms.append(trigram)

    # Abbreviation expansion (common DB naming abbreviations → full words)
    _abbreviations: dict[str, list[str]] = {
        "cust": ["customer", "client"],
        "prod": ["product", "production"],
        "cat": ["category"],
        "qty": ["quantity"],
        "amt": ["amount"],
        "txn": ["transaction"],
        "inv": ["inventory", "invoice"],
        "dept": ["department"],
        "emp": ["employee"],
        "mgr": ["manager"],
        "addr": ["address"],
        "desc": ["description"],
        "num": ["number"],
        "dt": ["date"],
        "ts": ["timestamp"],
        "cnt": ["count"],
        "pct": ["percent", "percentage"],
        "avg": ["average"],
        "tot": ["total"],
        "bal": ["balance"],
        "acct": ["account"],
        "org": ["organization"],
        "loc": ["location"],
        "sku": ["product", "item"],
        "ref": ["reference"],
        "seq": ["sequence"],
        "idx": ["index"],
        "dim": ["dimension"],
        "fct": ["fact"],
        "stg": ["staging"],
    }

    # Expand terms with semantic synonyms (improves recall for Spider2.0)
    expanded_terms = list(terms)
    for term in terms:
        if term in _synonyms:
            for syn in _synonyms[term]:
                if syn not in expanded_terms:
                    expanded_terms.append(syn)
        # Abbreviation expansion
        if term in _abbreviations:
            for full_word in _abbreviations[term]:
                if full_word not in expanded_terms:
                    expanded_terms.append(full_word)
    # Add n-gram compound terms
    for ng in ngram_terms:
        if ng not in expanded_terms:
            expanded_terms.append(ng)
    terms = expanded_terms

    # Simple lemmatization for common suffixes (improves recall without NLTK dependency)
    def _lemmatize(word: str) -> str:
        """Reduce common English inflections to base form."""
        if word.endswith("ies") and len(word) > 4:
            return word[:-3] + "y"  # categories → category
        if word.endswith("ves") and len(word) > 4:
            return word[:-3] + "f"  # shelves → shelf
        if word.endswith("ses") and len(word) > 4:
            return word[:-2]  # addresses → address
        if word.endswith("es") and len(word) > 3:
            return word[:-2]  # taxes → tax
        if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
            return word[:-1]  # orders → order
        if word.endswith("ing") and len(word) > 5:
            return word[:-3]  # shipping → ship
        if word.endswith("ed") and len(word) > 4:
            return word[:-2]  # created → creat
        return word

    # Add lemmatized forms for better matching
    lemma_additions = []
    for term in terms:
        lemma = _lemmatize(term)
        if lemma != term and lemma not in terms and len(lemma) >= 3:
            lemma_additions.append(lemma)
    terms.extend(lemma_additions)

    # Question-type detection: boost relevant column types
    # Aggregation questions → boost numeric columns
    # Time questions → boost date/timestamp columns
    _agg_keywords = {"average", "avg", "sum", "total", "count", "max", "maximum", "min", "minimum",
                     "mean", "median", "aggregate", "top", "bottom", "highest", "lowest", "most", "least"}
    _time_keywords = {"when", "date", "year", "month", "week", "day", "quarter", "recent",
                      "latest", "oldest", "between", "before", "after", "during", "period"}
    _numeric_types = {"int", "integer", "bigint", "smallint", "float", "double", "decimal",
                      "numeric", "real", "number", "money"}
    _time_types = {"date", "datetime", "timestamp", "timestamptz", "time"}

    question_words = set(question_lower.split())
    is_aggregation = bool(question_words & _agg_keywords)
    is_temporal = bool(question_words & _time_keywords)

    # Step 2: Score each table and column by relevance
    table_scores: dict[str, float] = {}
    column_scores: dict[str, dict[str, float]] = {}  # table_key -> {col_name: score}
    for table_key, table_data in filtered.items():
        score = 0.0
        col_scores: dict[str, float] = {}
        table_name_lower = table_data.get("name", "").lower()
        schema_name_lower = table_data.get("schema", "").lower()

        # Split table name into parts for compound matching (order_items -> ["order", "items"])
        table_name_parts = set(table_name_lower.split("_"))

        for term in terms:
            # Exact table name match (highest signal)
            if term == table_name_lower or term == table_name_lower.rstrip("s"):
                score += 10.0
            elif term in table_name_lower:
                score += 5.0
            # Singular/plural matching
            elif term + "s" == table_name_lower or term + "es" == table_name_lower:
                score += 8.0
            elif table_name_lower + "s" == term or table_name_lower + "es" == term:
                score += 8.0
            # Match against individual parts of compound table names
            elif term in table_name_parts or term.rstrip("s") in table_name_parts:
                score += 4.0

            # Column name matching — track per-column scores
            for col in table_data.get("columns", []):
                col_name_lower = col.get("name", "").lower()
                col_name = col.get("name", "")
                col_score = 0.0
                if term == col_name_lower:
                    col_score = 4.0
                elif term in col_name_lower:
                    col_score = 2.0
                # Check column comments
                comment = (col.get("comment") or "").lower()
                if term in comment:
                    col_score = max(col_score, 1.0)
                if col_score > 0:
                    col_scores[col_name] = col_scores.get(col_name, 0) + col_score
                    score += col_score

            # Table description/comment matching
            desc = (table_data.get("description") or "").lower()
            if term in desc:
                score += 2.0

        # N-gram matching: "order_items" bigram matches the table name directly
        # This catches compound terms like "customer address" → "customer_address"
        full_table_key_lower = f"{schema_name_lower}.{table_name_lower}"
        for ng in ngram_terms:
            if ng == table_name_lower:
                score += 12.0  # Exact compound match is very strong
            elif ng in table_name_lower:
                score += 6.0

        # Question-type boosting: prefer tables with relevant column types
        if is_aggregation and score > 0:
            numeric_cols = sum(
                1 for c in table_data.get("columns", [])
                if c.get("type", "").lower().split("(")[0] in _numeric_types
            )
            if numeric_cols > 0:
                score += min(numeric_cols * 0.5, 3.0)

        if is_temporal and score > 0:
            time_cols = sum(
                1 for c in table_data.get("columns", [])
                if c.get("type", "").lower().split("(")[0] in _time_types
                or any(kw in c.get("name", "").lower() for kw in ("date", "time", "created", "updated"))
            )
            if time_cols > 0:
                score += min(time_cols * 0.5, 2.0)

        # Check cached sample values for value-based linking (RSL-SQL bidirectional approach)
        # EDBT 2026: value-based linking catches cases term-matching misses,
        # e.g., "show orders from California" matches sample value "California" in state column
        cached_samples = schema_cache.get_sample_values(name, table_key)
        if cached_samples:
            for col_name, sample_vals in cached_samples.items():
                for sv in sample_vals:
                    sv_lower = str(sv).lower()
                    if len(sv_lower) >= 3 and sv_lower in question_lower:
                        score += 6.0  # Strong signal: question mentions actual data value
                        col_scores[col_name] = col_scores.get(col_name, 0) + 4.0  # Also boost the column
                        break  # One match per column is enough

        # Boost tables with many FKs (hub tables are usually more relevant)
        fk_count = len(table_data.get("foreign_keys", []))
        if fk_count > 0 and score > 0:
            score += min(fk_count * 0.5, 3.0)  # Up to +3 for hub tables

        # Boost tables with column statistics (better schema = more useful for agent)
        has_stats = sum(1 for c in table_data.get("columns", []) if c.get("stats") or c.get("has_statistics"))
        if has_stats > 0 and score > 0:
            score += 1.0  # Tables with stats are more informative

        table_scores[table_key] = score
        column_scores[table_key] = col_scores

    # Step 3: FK-propagated scoring (Spider2.0 optimization)
    # Tables FK-connected to high-scoring tables get a fraction of that score.
    # This ensures join-path tables are included AND ordered by relevance.
    # Build reverse FK index first: table_name → [keys of tables that reference it]
    reverse_fk_index: dict[str, list[str]] = {}
    for key, table_data in filtered.items():
        for fk in table_data.get("foreign_keys", []):
            ref_table = fk.get("references_table", "")
            if ref_table not in reverse_fk_index:
                reverse_fk_index[ref_table] = []
            reverse_fk_index[ref_table].append(key)

    # Forward FK propagation: if table A (score 20) → references table B, B gets +20*0.3
    # Reverse FK propagation: if table C references table A, C gets +20*0.2
    fk_boost: dict[str, float] = {}
    for key, score in table_scores.items():
        if score <= 0:
            continue
        table_data = filtered.get(key, {})
        # Forward: A.customer_id → customers — boost customers
        for fk in table_data.get("foreign_keys", []):
            ref_table = fk.get("references_table", "")
            for candidate_key in filtered:
                if filtered[candidate_key].get("name", "") == ref_table and candidate_key != key:
                    fk_boost[candidate_key] = max(fk_boost.get(candidate_key, 0), score * 0.3)
                    break
        # Reverse: tables that reference this table — boost them
        table_name = table_data.get("name", "")
        for referring_key in reverse_fk_index.get(table_name, []):
            if referring_key in filtered and referring_key != key:
                fk_boost[referring_key] = max(fk_boost.get(referring_key, 0), score * 0.2)

    # Apply FK boosts to scores
    for key, boost in fk_boost.items():
        if table_scores.get(key, 0) == 0:
            table_scores[key] = boost  # FK-only tables get the boost as their score
        # Don't increase already-scored tables — they earned their score directly

    # Step 4: Select top tables by score
    scored_tables = sorted(table_scores.items(), key=lambda x: (-x[1], x[0]))
    linked_keys = set()

    # Small-schema bypass: include ALL tables when schema is small enough.
    # Per "The Death of Schema Linking?" (OpenReview): for schemas that fit
    # the context window, skipping schema linking yields higher accuracy
    # because no relevant table can be missed. #1 on BIRD benchmark (71.83%).
    if _small_schema:
        linked_keys = set(filtered.keys())
    else:
        # Include tables with score > 0 (now includes FK-propagated scores)
        for key, score in scored_tables:
            if score > 0 and len(linked_keys) < max_tables:
                linked_keys.add(key)

    # If no matches found, fall back to first N tables sorted by FK relevance
    if not linked_keys:
        def _fb_relevance(key: str) -> tuple:
            t = filtered[key]
            return (-len(t.get("foreign_keys", [])), -(t.get("row_count", 0) or 0), key)
        linked_keys = set(sorted(filtered.keys(), key=_fb_relevance)[:min(max_tables, 10)])

    # Build response
    linked_schema = {k: filtered[k] for k in sorted(linked_keys) if k in filtered}

    # ── Column pruning helper ──────────────────────────────────────────────
    # For each table, determine which columns to include.
    # Always include: PK columns, FK columns, FK-referenced columns, and
    # columns with relevance score > 0.
    # For high-scoring tables (>= 5.0), include ALL columns (they're clearly relevant).
    # For lower-scoring tables (FK-connected), only include structural + matched columns.
    #
    # RSL-SQL / EDBT 2026: "missing a column is fatal; extras are tolerable noise."
    # We err on the side of keeping columns, especially join-path columns.

    # Build a set of columns that are FK targets from linked tables
    # (e.g., if orders.customer_id → customers.id, then customers.id must be kept)
    _fk_target_cols: dict[str, set[str]] = {}
    for lk in linked_keys:
        if lk not in filtered:
            continue
        for fk in filtered[lk].get("foreign_keys", []):
            ref_table = fk.get("references_table", "")
            ref_col = fk.get("references_column", "")
            ref_schema = fk.get("references_schema", "")
            ref_key = f"{ref_schema}.{ref_table}" if ref_schema else ref_table
            # Find the matching linked table key
            for candidate_key in linked_keys:
                if filtered.get(candidate_key, {}).get("name", "") == ref_table:
                    if candidate_key not in _fk_target_cols:
                        _fk_target_cols[candidate_key] = set()
                    _fk_target_cols[candidate_key].add(ref_col)
                    break

    def _prune_columns(table_key: str, table_data: dict) -> list[dict]:
        """Return only relevant columns for a table, keeping PKs and FKs always."""
        t_score = table_scores.get(table_key, 0)
        # High-relevance tables: keep all columns (the whole table matters)
        if t_score >= 5.0 or not prune_columns:
            return table_data.get("columns", [])

        col_relevance = column_scores.get(table_key, {})
        fk_cols = {fk.get("column", "") for fk in table_data.get("foreign_keys", [])}
        fk_targets = _fk_target_cols.get(table_key, set())

        kept = []
        for col in table_data.get("columns", []):
            col_name = col.get("name", "")
            # Always keep: PKs, FK columns, FK-target columns, and columns with question relevance
            if col.get("primary_key"):
                kept.append(col)
            elif col_name in fk_cols:
                kept.append(col)
            elif col_name in fk_targets:
                kept.append(col)
            elif col_relevance.get(col_name, 0) > 0:
                kept.append(col)
        # If pruning removed everything, keep all (safety)
        return kept if kept else table_data.get("columns", [])

    if format == "condensed":
        # Condensed DDL: minimal token usage — pruned columns, no annotations, compressed types
        condensed_lines = []
        total_cols_original = 0
        total_cols_kept = 0
        for key in sorted(linked_keys):
            if key not in filtered:
                continue
            t = filtered[key]
            table_name = f"{t.get('schema', '')}.{t.get('name', '')}"
            all_cols = t.get("columns", [])
            kept_cols = _prune_columns(key, t)
            total_cols_original += len(all_cols)
            total_cols_kept += len(kept_cols)
            col_parts = []
            pk_cols = []
            for col in kept_cols:
                ct = col.get("type", "TEXT").upper()
                ct = compress_type(ct)
                # Strip precision from types for brevity: VARCHAR(255) → VARCHAR
                if "(" in ct and ct.split("(")[0] in ("VARCHAR", "NVARCHAR", "CHAR", "DECIMAL", "NUMERIC"):
                    ct = ct.split("(")[0]
                nn = " NOT NULL" if not col.get("nullable", True) else ""
                col_parts.append(f"  {col['name']} {ct}{nn}")
                if col.get("primary_key"):
                    pk_cols.append(col["name"])
            if pk_cols:
                col_parts.append(f"  PRIMARY KEY ({', '.join(pk_cols)})")
            for fk in t.get("foreign_keys", []):
                col_parts.append(f"  FOREIGN KEY ({fk['column']}) REFERENCES {fk.get('references_table', '')}({fk.get('references_column', '')})")
            pruned_note = ""
            if len(kept_cols) < len(all_cols):
                pruned_note = f" -- {len(all_cols) - len(kept_cols)} columns pruned"
            obj_kw = "CREATE VIEW" if t.get("type") == "view" else "CREATE TABLE"
            col_block = ",\n".join(col_parts)
            condensed_lines.append(f"{obj_kw} {table_name} (\n{col_block}\n);{pruned_note}")
        condensed_text = "\n\n".join(condensed_lines)
        reduction_pct = round((1 - total_cols_kept / max(total_cols_original, 1)) * 100)
        condensed_result: dict[str, Any] = {
            "connection_name": name,
            "question": question,
            "format": "condensed",
            "full_schema": _small_schema,
            "linked_tables": len(linked_keys),
            "total_tables": len(filtered),
            "columns_original": total_cols_original,
            "columns_kept": total_cols_kept,
            "column_reduction_pct": reduction_pct,
            "token_estimate": len(condensed_text) // 4,
            "scores": {k: round(table_scores.get(k, 0), 1) for k in sorted(linked_keys) if table_scores.get(k, 0) > 0},
            "ddl": condensed_text,
        }
        # Add join hints and dialect (shared with DDL format)
        _join_hints = _build_join_hints(linked_keys, filtered)
        if _join_hints:
            condensed_result["join_hints"] = _join_hints
        _dh = _DIALECT_HINTS.get(info.db_type)
        if _dh:
            condensed_result["dialect"] = _dh
        return condensed_result

    if format == "compact":
        lines = []
        for key in sorted(linked_keys):
            if key not in filtered:
                continue
            t = filtered[key]
            col_strs = []
            kept_cols = _prune_columns(key, t)
            for c in kept_cols:
                pk_flag = "*" if c.get("primary_key") else ""
                ct = c.get("type", "").upper()
                s = f"{c['name']}{pk_flag} {ct}"
                stats = c.get("stats", {})
                if stats.get("distinct_count"):
                    s += f"({stats['distinct_count']}d)"
                col_strs.append(s)
            if len(kept_cols) < len(t.get("columns", [])):
                col_strs.append(f"+{len(t['columns']) - len(kept_cols)} more")
            cols = ", ".join(col_strs)
            rc = t.get("row_count", 0)
            rc_str = f" ({rc:,} rows)" if rc else ""
            score = table_scores.get(key, 0)
            lines.append(f"{key}{rc_str} [score={score:.1f}]: {cols}")
        return {
            "connection_name": name,
            "question": question,
            "format": "compact",
            "full_schema": _small_schema,
            "linked_tables": len(linked_keys),
            "total_tables": len(filtered),
            "scores": {k: round(table_scores.get(k, 0), 1) for k in sorted(linked_keys) if table_scores.get(k, 0) > 0},
            "schema": "\n".join(lines),
        }

    if format == "json":
        return {
            "connection_name": name,
            "question": question,
            "format": "json",
            "full_schema": _small_schema,
            "linked_tables": len(linked_keys),
            "total_tables": len(filtered),
            "scores": {k: table_scores.get(k, 0) for k in sorted(linked_keys)},
            "tables": linked_schema,
        }

    # DDL format (default — preferred by Spider2.0 SOTA)
    ddl_lines = []
    for key in sorted(linked_keys):
        if key not in filtered:
            continue
        t = filtered[key]
        table_name = f"{t.get('schema', '')}.{t.get('name', '')}"
        # Table description as comment (semantic context for agent)
        table_desc = t.get("description", "")
        header = f"-- {table_desc}\n" if table_desc else ""
        col_parts = []
        pk_cols = []
        ddl_cols = _prune_columns(key, t)
        pruned_count = len(t.get("columns", [])) - len(ddl_cols)
        for col in ddl_cols:
            ct = col.get("type", "TEXT").upper()
            ct = TYPE_COMPRESSION_MAP.get(ct, ct)
            parts = [f"  {col['name']} {ct}"]
            if not col.get("nullable", True):
                parts.append("NOT NULL")
            # Column annotations for agent context
            annotations = []
            col_comment = col.get("comment", "")
            if col_comment:
                annotations.append(col_comment)
            # Column statistics help agent understand data shape
            stats = col.get("stats", {})
            if stats.get("distinct_count"):
                annotations.append(f"{stats['distinct_count']} distinct values")
            elif stats.get("distinct_fraction"):
                frac = abs(stats["distinct_fraction"])
                if frac >= 0.99:
                    annotations.append("unique")
                elif frac >= 0.5:
                    annotations.append("high cardinality")
            # Redshift/warehouse column-level optimization hints
            if col.get("dist_key"):
                annotations.append("DISTKEY")
            if col.get("sort_key_position"):
                annotations.append(f"SORTKEY#{col['sort_key_position']}")
            if col.get("low_cardinality"):
                annotations.append("low cardinality")
            # Inline sample values for low-cardinality string columns (Spider2.0 key technique)
            # Only for columns with <=50 distinct values — avoids wasting tokens on unique/high-card columns
            is_low_card = False
            dc = stats.get("distinct_count", 0) if stats else 0
            df = abs(stats.get("distinct_fraction", 0)) if stats else 0
            if dc and dc <= 50:
                is_low_card = True
            elif df and df < 0.05:
                is_low_card = True
            elif not stats:
                is_low_card = True  # No stats = show samples as hint

            if is_low_card:
                cached_samples = schema_cache.get_sample_values(name, key)
                if cached_samples and col["name"] in cached_samples:
                    sample_vals = cached_samples[col["name"]]
                    if len(sample_vals) <= 10:
                        annotations.append(f"e.g. {', '.join(repr(v) for v in sample_vals[:5])}")
            if annotations:
                parts.append(f"-- {'; '.join(annotations)}")
            col_parts.append(" ".join(parts))
            if col.get("primary_key"):
                pk_cols.append(col["name"])
        if pk_cols:
            col_parts.append(f"  PRIMARY KEY ({', '.join(pk_cols)})")
        for fk in t.get("foreign_keys", []):
            col_parts.append(f"  FOREIGN KEY ({fk['column']}) REFERENCES {fk.get('references_table', '')}({fk.get('references_column', '')})")
        rc = t.get("row_count", 0)
        # Build metadata comment
        meta_parts = []
        if rc:
            meta_parts.append(f"{rc:,} rows" if rc < 1_000_000 else f"{rc/1_000_000:.1f}M rows")
        engine = t.get("engine", "")
        if engine:
            meta_parts.append(f"ENGINE={engine}")
        sorting = t.get("sorting_key", "")
        if sorting:
            meta_parts.append(f"ORDER BY({sorting})")
        diststyle = t.get("diststyle", "")
        if diststyle:
            meta_parts.append(f"DISTSTYLE={diststyle}")
        sortkey = t.get("sortkey", "")
        if sortkey:
            meta_parts.append(f"SORTKEY({sortkey})")
        clustering_key = t.get("clustering_key", "")
        if clustering_key:
            meta_parts.append(f"CLUSTER BY({clustering_key})")
        meta_parts.append(f"relevance={table_scores.get(key, 0):.1f}")
        if pruned_count > 0:
            meta_parts.append(f"{pruned_count} cols pruned")
        rc_comment = f" -- {', '.join(meta_parts)}"
        obj_kw = "CREATE VIEW" if t.get("type") == "view" else "CREATE TABLE"
        col_block = ",\n".join(col_parts)
        ddl_lines.append(f"{header}{obj_kw} {table_name} (\n{col_block}\n);{rc_comment}")

    ddl_text = "\n\n".join(ddl_lines)

    # Proactively fetch sample values for linked tables that lack them (background)
    # Next schema_link call will include inline samples in DDL annotations
    missing_samples = []
    string_types = {"character varying", "varchar", "text", "char", "character", "enum",
                   "String", "VARCHAR", "TEXT", "CHAR", "NVARCHAR", "string"}
    for key in linked_keys:
        if key not in filtered:
            continue
        if schema_cache.get_sample_values(name, key) is not None:
            continue  # Already cached
        t = filtered[key]
        sample_cols = [
            c["name"] for c in t.get("columns", [])
            if c.get("type", "") in string_types or "char" in c.get("type", "").lower()
        ]
        if sample_cols:
            missing_samples.append((key, t, sample_cols[:10]))

    if missing_samples:
        try:
            conn_str = await store.get_connection_string(name)
            if conn_str:
                extras = await store.get_credential_extras(name)
                async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
                    for key, t, sample_cols in missing_samples[:5]:  # Cap at 5 tables
                        table_name = f"{t.get('schema', '')}.{t['name']}" if t.get("schema") else t["name"]
                        try:
                            values = await connector.get_sample_values(table_name, sample_cols, limit=5)
                            if values:
                                schema_cache.put_sample_values(name, key, values)
                        except Exception:
                            pass
        except Exception:
            pass  # Best-effort — don't fail the schema_link response

    # Build join hints and dialect info using extracted helpers
    join_hints = _build_join_hints(linked_keys, filtered)

    result: dict[str, Any] = {
        "connection_name": name,
        "question": question,
        "format": "ddl",
        "full_schema": _small_schema,
        "linked_tables": len(linked_keys),
        "total_tables": len(filtered),
        "token_estimate": len(ddl_text) // 4,
        "scores": {k: round(table_scores.get(k, 0), 1) for k in sorted(linked_keys) if table_scores.get(k, 0) > 0},
        "ddl": ddl_text,
    }
    if join_hints:
        result["join_hints"] = join_hints
    dialect = _DIALECT_HINTS.get(info.db_type)
    if dialect:
        result["dialect"] = dialect

    # Query-type-aware hints (ReFoRCE "format restriction" pattern)
    # Detect question type and provide SQL pattern guidance to reduce errors
    query_hints: list[str] = []
    _q = question_lower
    if is_aggregation:
        query_hints.append("Use GROUP BY for aggregations; include all non-aggregated SELECT columns")
    if any(w in _q for w in ("top", "highest", "lowest", "rank", "first", "best", "worst")):
        if info.db_type == "mssql":
            query_hints.append("Use TOP N instead of LIMIT; for ranking use ROW_NUMBER() OVER(...)")
        else:
            query_hints.append("Use ORDER BY ... LIMIT N for top-N queries; consider RANK()/ROW_NUMBER() for ties")
    if any(w in _q for w in ("percentage", "percent", "ratio", "share", "proportion")):
        query_hints.append("Use 100.0 * COUNT/SUM to avoid integer division; cast to DECIMAL if needed")
    if is_temporal:
        if info.db_type in ("postgres", "redshift"):
            query_hints.append("Use DATE_TRUNC('month', col) for time grouping; EXTRACT(YEAR FROM col) for year")
        elif info.db_type == "mysql":
            query_hints.append("Use DATE_FORMAT(col, '%Y-%m') for month grouping; YEAR(col), MONTH(col) for parts")
        elif info.db_type == "mssql":
            query_hints.append("Use FORMAT(col, 'yyyy-MM') or DATEPART(YEAR, col) for time grouping")
        elif info.db_type == "bigquery":
            query_hints.append("Use FORMAT_DATE('%Y-%m', col) or EXTRACT(YEAR FROM col) for time grouping")
        elif info.db_type == "snowflake":
            query_hints.append("Use DATE_TRUNC('MONTH', col) for time grouping; TO_CHAR(col, 'YYYY-MM')")
    if any(w in _q for w in ("distinct", "unique", "different")):
        query_hints.append("Use COUNT(DISTINCT col) for unique counts; SELECT DISTINCT for unique rows")
    if any(w in _q for w in ("compare", "versus", "vs", "difference", "change")):
        query_hints.append("Consider self-joins or window functions (LAG/LEAD) for comparisons")
    if any(w in _q for w in ("running", "cumulative", "rolling")):
        query_hints.append("Use SUM(...) OVER (ORDER BY ...) for running totals; ROWS BETWEEN for rolling windows")

    if query_hints:
        result["query_hints"] = query_hints

    return result


def _levenshtein(s1: str, s2: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (0 if c1 == c2 else 1)))
        prev = curr
    return prev[len(s2)]


def _fuzzy_match(query: str, target: str, max_distance: int = 2) -> bool:
    """Simple edit-distance fuzzy matching for schema search."""
    if len(query) < 4 or len(target) < 3:
        return False
    if abs(len(query) - len(target)) > max_distance:
        if len(target) > len(query) + max_distance:
            for i in range(len(target) - len(query) + 1):
                window = target[i : i + len(query)]
                if _levenshtein(query, window) <= max_distance:
                    return True
        return False
    return _levenshtein(query, target) <= max_distance


def _save_semantic_model(name: str, model: dict) -> None:
    _semantic_models[name] = model
    path = _semantic_model_path(name)
    path.write_text(json.dumps(model, indent=2))


# ─── Endpoints ───────────────────────────────────────────────────────────────


@router.post("/connections/{name}/schema/refine", dependencies=[RequireScope("write")])
async def refine_schema(
    name: str,
    store: StoreD,
    request: Request,
):
    """Two-pass schema refinement -- Spider2.0 SOTA technique.

    Takes a draft SQL query and returns only the tables/columns actually
    referenced in it. This enables the two-pass pattern used by top performers
    (RSL-SQL, ReFoRCE):
      1. Agent gets broad schema via /schema/link or /schema/agent-context
      2. Agent generates draft SQL
      3. Agent calls this endpoint with the draft SQL
      4. This returns a minimal, precise schema for the final SQL generation

    Research shows this reduces hallucinated columns by 40-60% and improves
    execution accuracy by 3-5% on Spider2.0-Lite.
    """
    info = await require_connection(store, name)

    body = await request.json()
    draft_sql = body.get("draft_sql", "")
    question = body.get("question", "")
    format = body.get("format", "ddl")

    if not draft_sql:
        raise HTTPException(status_code=400, detail="draft_sql is required")

    filtered = await get_filtered_schema(store, name, info)

    sql_clean = draft_sql

    # Patterns that precede table names in SQL
    table_patterns = [
        r'(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+(?:`|"|\'|\[)?(\w+(?:\.\w+)*)(?:`|"|\'|\])?',
        r'(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+(?:`|"|\'|\[)?(\w+)(?:`|"|\'|\])?\s*\.\s*(?:`|"|\'|\[)?(\w+)(?:`|"|\'|\])?',
    ]

    referenced_tables: set[str] = set()
    referenced_columns: set[str] = set()

    for pattern in table_patterns:
        for match in _re_refine.finditer(pattern, sql_clean, _re_refine.IGNORECASE):
            groups = [g for g in match.groups() if g]
            for g in groups:
                referenced_tables.add(g.lower().strip('`"\'[]'))

    col_patterns = [
        r'(?:SELECT|WHERE|AND|OR|ON|BY|HAVING|SET)\s+(?:`|"|\'|\[)?(\w+)(?:`|"|\'|\])?',
        r'(\w+)\s*(?:=|<|>|!=|<>|LIKE|IN|BETWEEN|IS)',
    ]
    sql_keywords = {
        'select', 'from', 'where', 'and', 'or', 'not', 'null',
        'true', 'false', 'case', 'when', 'then', 'else', 'end',
        'as', 'in', 'is', 'on', 'by', 'having', 'set', 'all',
        'distinct', 'count', 'sum', 'avg', 'min', 'max', 'like',
        'between', 'exists', 'any', 'group', 'order', 'limit',
        'offset', 'union', 'except', 'intersect', 'asc', 'desc',
    }
    for pattern in col_patterns:
        for match in _re_refine.finditer(pattern, sql_clean, _re_refine.IGNORECASE):
            col = match.group(1).lower().strip('`"\'[]')
            if col not in sql_keywords:
                referenced_columns.add(col)

    # Also extract dotted references like t.column_name
    for match in _re_refine.finditer(r'(\w+)\.(\w+)', sql_clean):
        alias_or_table = match.group(1).lower()
        col = match.group(2).lower()
        referenced_tables.add(alias_or_table)
        referenced_columns.add(col)

    # Match extracted names to actual schema tables
    matched_keys: set[str] = set()
    table_name_to_key: dict[str, str] = {}
    for key, t in filtered.items():
        tn = t.get("name", "").lower()
        sn = t.get("schema", "").lower()
        full = f"{sn}.{tn}" if sn else tn
        table_name_to_key[tn] = key
        table_name_to_key[full] = key

    for ref in referenced_tables:
        if ref in table_name_to_key:
            matched_keys.add(table_name_to_key[ref])
        for key, t in filtered.items():
            tn = t.get("name", "").lower()
            if ref == tn:
                matched_keys.add(key)

    # Add FK-connected tables for join completeness
    fk_adds: set[str] = set()
    for key in list(matched_keys):
        t = filtered.get(key, {})
        for fk in t.get("foreign_keys", []):
            ref_table = fk.get("references_table", "").lower()
            if ref_table in table_name_to_key:
                fk_adds.add(table_name_to_key[ref_table])
    matched_keys |= fk_adds

    # Also add inferred join targets
    inferred = _infer_implicit_joins(filtered)
    for ij in inferred:
        for key, t in filtered.items():
            tn = t.get("name", "").lower()
            if tn == ij["from_table"].lower():
                if key in matched_keys:
                    for k2, t2 in filtered.items():
                        if t2.get("name", "").lower() == ij["to_table"].lower():
                            matched_keys.add(k2)

    if not matched_keys:
        matched_keys = set(list(filtered.keys())[:20])

    # Build DDL
    ddl_lines = []
    for key in sorted(matched_keys):
        if key not in filtered:
            continue
        t = filtered[key]
        table_name = f"{t.get('schema', '')}.{t.get('name', '')}"
        col_parts = []
        pk_cols = []
        for col in t.get("columns", []):
            ct = col.get("type", "TEXT").upper()
            type_map = {
                "CHARACTER VARYING": "VARCHAR",
                "TIMESTAMP WITHOUT TIME ZONE": "TIMESTAMP",
                "TIMESTAMP WITH TIME ZONE": "TIMESTAMPTZ",
                "DOUBLE PRECISION": "DOUBLE",
            }
            ct = type_map.get(ct, ct)
            is_referenced = col["name"].lower() in referenced_columns
            parts = [f"  {col['name']} {ct}"]
            if not col.get("nullable", True):
                parts.append("NOT NULL")
            if is_referenced:
                parts.append("-- << USED IN QUERY")
            cached_samples = schema_cache.get_sample_values(name, key)
            if cached_samples and col["name"] in cached_samples and is_referenced:
                vals = cached_samples[col["name"]][:5]
                parts.append(f"e.g. {', '.join(repr(v) for v in vals)}")
            col_parts.append(" ".join(parts))
            if col.get("primary_key"):
                pk_cols.append(col["name"])
        if pk_cols:
            col_parts.append(f"  PRIMARY KEY ({', '.join(pk_cols)})")
        for fk in t.get("foreign_keys", []):
            col_parts.append(
                f"  FOREIGN KEY ({fk['column']}) REFERENCES "
                f"{fk.get('references_table', '')}({fk.get('references_column', '')})"
            )

        rc = t.get("row_count", 0)
        meta = f" -- {rc:,} rows" if rc else ""
        col_block = ",\n".join(col_parts)
        ddl_lines.append(f"CREATE TABLE {table_name} (\n{col_block}\n);{meta}")

    ddl_text = "\n\n".join(ddl_lines)

    return {
        "connection_name": name,
        "question": question,
        "draft_sql": draft_sql,
        "refined_tables": len(matched_keys),
        "total_tables": len(filtered),
        "referenced_tables": sorted(referenced_tables),
        "referenced_columns": sorted(referenced_columns),
        "token_estimate": len(ddl_text) // 4,
        "ddl": ddl_text,
    }


@router.get("/connections/{name}/schema/explore-table", dependencies=[RequireScope("read")])
async def explore_table(
    name: str,
    store: StoreD,
    table: str = Query(..., description="Full table name (e.g., 'public.customers')"),
    include_samples: bool = Query(default=True, description="Include sample distinct values for string/enum columns"),
    include_stats: bool = Query(default=True, description="Include column-level statistics"),
    sample_limit: int = Query(default=5, ge=1, le=20, description="Max sample values per column"),
):
    """Deep column exploration for a single table -- ReFoRCE-style iterative schema linking."""
    info = await require_connection(store, name)
    cached = await get_or_fetch_schema(store, name, info)

    # Find the table
    table_data = cached.get(table)
    if not table_data:
        for key, tbl in cached.items():
            if tbl.get("name") == table or key == table:
                table_data = tbl
                table = key
                break
    if not table_data:
        raise HTTPException(status_code=404, detail=f"Table '{table}' not found in schema")

    result: dict[str, Any] = {
        "connection_name": name,
        "table": table,
        "schema": table_data.get("schema", ""),
        "name": table_data.get("name", ""),
        "row_count": table_data.get("row_count", 0),
        "engine": table_data.get("engine", ""),
        "columns": [],
        "foreign_keys": table_data.get("foreign_keys", []),
        "referenced_by": [],
    }

    # Find reverse FK references
    for key, tbl in cached.items():
        for fk in tbl.get("foreign_keys", []):
            if fk.get("references_table") == table_data.get("name"):
                result["referenced_by"].append({
                    "table": key,
                    "column": fk["column"],
                    "references_column": fk["references_column"],
                })

    # Build enriched column list
    string_cols = []
    for col in table_data.get("columns", []):
        col_info: dict[str, Any] = {
            "name": col["name"],
            "type": col.get("type", ""),
            "nullable": col.get("nullable", True),
            "primary_key": col.get("primary_key", False),
        }
        if col.get("comment"):
            col_info["comment"] = col["comment"]
        if include_stats and col.get("stats"):
            col_info["stats"] = col["stats"]

        for fk in table_data.get("foreign_keys", []):
            if fk["column"] == col["name"]:
                col_info["foreign_key"] = {
                    "references_table": fk["references_table"],
                    "references_column": fk["references_column"],
                }

        result["columns"].append(col_info)

        col_type = col.get("type", "").lower()
        if any(t in col_type for t in ("varchar", "text", "char", "string", "enum", "category")):
            string_cols.append(col["name"])

    # Fetch sample values for string columns
    if include_samples and string_cols:
        cached_samples = schema_cache.get_sample_values(name, table)
        if cached_samples:
            result["sample_values"] = cached_samples
        else:
            try:
                conn_str = await store.get_connection_string(name)
                if conn_str:
                    extras = await store.get_credential_extras(name)
                    async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
                        samples = await connector.get_sample_values(table, string_cols[:10], limit=sample_limit)
                    if samples:
                        schema_cache.put_sample_values(name, table, samples)
                        result["sample_values"] = samples
            except Exception:
                pass

    return result


@router.get("/connections/{name}/schema/overview", dependencies=[RequireScope("read")])
async def get_schema_overview(name: str, store: StoreD):
    """Quick database overview -- table count, total columns, total rows, FK graph density."""
    info = await require_connection(store, name)
    filtered = await get_filtered_schema(store, name, info)

    total_tables = len(filtered)
    total_columns = 0
    total_rows = 0
    total_fks = 0
    total_size_mb = 0.0
    schemas_set: set[str] = set()
    tables_with_fks: set[str] = set()
    largest_tables: list[dict] = []

    for key, table in filtered.items():
        cols = table.get("columns", [])
        total_columns += len(cols)
        row_count = table.get("row_count", 0) or 0
        total_rows += row_count
        total_size_mb += table.get("size_mb", 0) or 0
        schemas_set.add(table.get("schema", ""))
        fks = table.get("foreign_keys", [])
        total_fks += len(fks)
        if fks:
            tables_with_fks.add(key)
        entry: dict = {
            "table": key,
            "columns": len(cols),
            "rows": row_count,
            "fks": len(fks),
        }
        for meta_key in (
            "engine", "sorting_key", "diststyle", "sortkey",
            "clustering_key", "partitioning", "clustering_fields",
            "size_bytes", "size_mb", "total_bytes",
        ):
            val = table.get(meta_key)
            if val:
                entry[meta_key] = val
        largest_tables.append(entry)

    largest_tables.sort(key=lambda t: t["rows"], reverse=True)

    inferred_joins = _infer_implicit_joins(filtered)

    return {
        "connection_name": name,
        "db_type": info.db_type,
        "schemas": sorted(schemas_set),
        "schema_count": len(schemas_set),
        "table_count": total_tables,
        "total_columns": total_columns,
        "total_rows": total_rows,
        "total_size_mb": round(total_size_mb, 2),
        "total_foreign_keys": total_fks,
        "tables_with_fks": len(tables_with_fks),
        "avg_columns_per_table": round(total_columns / total_tables, 1) if total_tables else 0,
        "largest_tables": largest_tables[:10],
        "estimated_schema_tokens": total_columns * 8 + total_tables * 20,
        "recommendation": (
            "compact" if total_columns > 200
            else "full" if total_columns < 50
            else "enriched"
        ),
        "inferred_joins": len(inferred_joins),
        "spider2_hints": {
            "needs_compression": total_columns > 500,
            "has_partitioned_tables": any(
                "_20" in (t.get("name", "") or "") for t in filtered.values()
            ),
            "join_complexity": (
                "high" if (total_fks + len(inferred_joins)) > 15
                else "medium" if (total_fks + len(inferred_joins)) > 5
                else "low"
            ),
            "has_implicit_joins": len(inferred_joins) > 0,
        },
    }


@router.get("/connections/{name}/schema/diff", dependencies=[RequireScope("read")])
async def get_schema_diff(name: str, store: StoreD):
    """Compare current database schema against cached version."""
    info = await require_connection(store, name)

    conn_str = await store.get_connection_string(name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored")

    try:
        extras = await store.get_credential_extras(name)
        async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
            new_schema = await connector.get_schema()
    except Exception as e:
        raise HTTPException(status_code=500, detail=sanitize_db_error(str(e), info.db_type))

    diff = schema_cache.diff(name, new_schema)
    if diff is None:
        schema_cache.put(name, new_schema)
        return {
            "connection_name": name,
            "has_cached": False,
            "message": "No cached schema to compare. Current schema cached as baseline.",
            "table_count": len(new_schema),
            "fingerprint": schema_cache.get_fingerprint(name),
        }

    schema_cache.put(name, new_schema, track_diff=True)

    return {
        "connection_name": name,
        "has_cached": True,
        "diff": diff,
        "table_count": len(new_schema),
        "fingerprint": schema_cache.get_fingerprint(name),
    }


@router.get("/connections/{name}/schema/refresh-status", dependencies=[RequireScope("read")])
async def get_schema_refresh_status(name: str, store: StoreD):
    """Get schema refresh schedule status for a connection."""
    info = await require_connection(store, name)

    cached_stats = schema_cache.get(name)
    return {
        "connection_name": name,
        "schema_refresh_interval": info.schema_refresh_interval,
        "last_schema_refresh": info.last_schema_refresh,
        "next_refresh_at": (
            info.last_schema_refresh + info.schema_refresh_interval
            if info.last_schema_refresh and info.schema_refresh_interval
            else None
        ),
        "cached": cached_stats is not None,
        "cached_table_count": len(cached_stats) if cached_stats else 0,
        "fingerprint": schema_cache.get_fingerprint(name),
    }


@router.get("/connections/{name}/schema/diff-history", dependencies=[RequireScope("read")])
async def get_schema_diff_history(name: str, store: StoreD):
    """Get schema change history for a connection."""
    info = await require_connection(store, name)

    history = schema_cache.get_diff_history(name)
    return {
        "connection_name": name,
        "events": history,
        "current_fingerprint": schema_cache.get_fingerprint(name),
    }


@router.get("/schema/changes", dependencies=[RequireScope("read")])
async def get_all_schema_changes():
    """Get recent schema changes across all connections."""
    history = schema_cache.get_diff_history()
    return {
        "events": history,
        "cache_stats": schema_cache.stats(),
    }


@router.get("/connections/{name}/schema/filter", dependencies=[RequireScope("read")])
async def get_filtered_schema_endpoint(
    name: str,
    store: StoreD,
    schema_prefix: str = Query(default="", description="Filter by schema/database prefix (e.g., 'public', 'analytics')"),
    table_prefix: str = Query(default="", description="Filter by table name prefix"),
    include_columns: bool = Query(default=True, description="Include column details"),
    max_tables: int = Query(default=100, ge=1, le=1000, description="Maximum tables to return"),
):
    """Filter schema by database/schema prefix and table prefix."""
    info = await require_connection(store, name)
    filtered = await get_filtered_schema(store, name, info)

    # Apply prefix filters
    result: dict[str, Any] = {}
    for key, table in filtered.items():
        tbl_schema = table.get("schema", "")
        tbl_name = table.get("name", "")

        if schema_prefix and not tbl_schema.lower().startswith(schema_prefix.lower()):
            continue
        if table_prefix and not tbl_name.lower().startswith(table_prefix.lower()):
            continue

        if include_columns:
            result[key] = table
        else:
            result[key] = {k: v for k, v in table.items() if k != "columns"}
            result[key]["column_count"] = len(table.get("columns", []))

        if len(result) >= max_tables:
            break

    return {
        "connection_name": name,
        "filters": {
            "schema_prefix": schema_prefix or None,
            "table_prefix": table_prefix or None,
        },
        "table_count": len(result),
        "total_tables": len(filtered),
        "tables": result,
    }


@router.get("/connections/{name}/schema/relationships", dependencies=[RequireScope("read")])
async def get_schema_relationships(
    name: str,
    store: StoreD,
    format: str = Query(
        default="compact",
        pattern=r"^(compact|full|graph)$",
        description="Output format: compact (one-line per FK), full (detailed JSON), graph (adjacency list)",
    ),
    include_implicit: bool = Query(
        default=True,
        description="Include inferred joins from column name patterns (e.g., customer_id -> customers.id)",
    ),
):
    """Extract all foreign key relationships from schema -- ERD summary for AI agents."""
    info = await require_connection(store, name)
    filtered = await get_filtered_schema(store, name, info)

    # Extract all FK relationships (explicit)
    relationships: list[dict] = []
    for key, table in filtered.items():
        tbl_schema = table.get("schema", "")
        tbl_name = table.get("name", "")
        for fk in table.get("foreign_keys", []):
            ref_schema = fk.get("references_schema", tbl_schema)
            relationships.append({
                "from_schema": tbl_schema,
                "from_table": tbl_name,
                "from_column": fk["column"],
                "to_schema": ref_schema,
                "to_table": fk["references_table"],
                "to_column": fk["references_column"],
            })
    explicit_count = len(relationships)

    # Add implicit/inferred joins
    implicit_count = 0
    if include_implicit:
        inferred = _infer_implicit_joins(filtered)
        explicit_set = {
            (r["from_table"].lower(), r["from_column"].lower(),
             r["to_table"].lower(), r["to_column"].lower())
            for r in relationships
        }
        for inf in inferred:
            edge = (
                inf["from_table"].lower(), inf["from_column"].lower(),
                inf["to_table"].lower(), inf["to_column"].lower(),
            )
            if edge not in explicit_set:
                relationships.append(inf)
                implicit_count += 1

    if format == "compact":
        lines = []
        for r in relationships:
            from_qual = f"{r['from_schema']}.{r['from_table']}" if r["from_schema"] else r["from_table"]
            to_qual = f"{r['to_schema']}.{r['to_table']}" if r["to_schema"] else r["to_table"]
            suffix = " [inferred]" if r.get("inferred") else ""
            lines.append(f"{from_qual}.{r['from_column']} \u2192 {to_qual}.{r['to_column']}{suffix}")
        return {
            "connection_name": name,
            "format": "compact",
            "relationship_count": len(relationships),
            "explicit_count": explicit_count,
            "inferred_count": implicit_count,
            "relationships": lines,
        }

    elif format == "graph":
        graph: dict[str, list[str]] = {}
        for r in relationships:
            from_qual = f"{r['from_schema']}.{r['from_table']}" if r["from_schema"] else r["from_table"]
            to_qual = f"{r['to_schema']}.{r['to_table']}" if r["to_schema"] else r["to_table"]
            if from_qual not in graph:
                graph[from_qual] = []
            if to_qual not in graph[from_qual]:
                graph[from_qual].append(to_qual)
            if to_qual not in graph:
                graph[to_qual] = []
            if from_qual not in graph[to_qual]:
                graph[to_qual].append(from_qual)
        return {
            "connection_name": name,
            "format": "graph",
            "table_count": len(graph),
            "relationship_count": len(relationships),
            "adjacency": graph,
        }

    else:  # full
        return {
            "connection_name": name,
            "format": "full",
            "relationship_count": len(relationships),
            "relationships": relationships,
        }


@router.get("/connections/{name}/schema/join-paths", dependencies=[RequireScope("read")])
async def get_join_paths(
    name: str,
    store: StoreD,
    from_table: str = Query(..., description="Source table (e.g., 'public.orders')"),
    to_table: str = Query(..., description="Target table (e.g., 'public.products')"),
    max_hops: int = Query(default=4, ge=1, le=6, description="Maximum FK hops to search"),
    include_implicit: bool = Query(default=True, description="Include inferred joins from column naming conventions"),
):
    """Find all join paths between two tables -- critical for Spider2.0 multi-hop queries."""
    info = await require_connection(store, name)
    filtered = await get_filtered_schema(store, name, info)

    # Build bidirectional adjacency list with join info
    edges: dict[str, list[tuple[str, str, str, str]]] = {}
    for key, table in filtered.items():
        tbl_schema = table.get("schema", "")
        tbl_name = table.get("name", "")
        full_name = f"{tbl_schema}.{tbl_name}" if tbl_schema else tbl_name

        for fk in table.get("foreign_keys", []):
            ref_schema = fk.get("references_schema", tbl_schema)
            ref_full = f"{ref_schema}.{fk['references_table']}" if ref_schema else fk["references_table"]

            if full_name not in edges:
                edges[full_name] = []
            edges[full_name].append((full_name, fk["column"], ref_full, fk["references_column"]))

            if ref_full not in edges:
                edges[ref_full] = []
            edges[ref_full].append((ref_full, fk["references_column"], full_name, fk["column"]))

    if include_implicit:
        inferred = _infer_implicit_joins(filtered)
        for inf in inferred:
            inf_from = f"{inf['from_schema']}.{inf['from_table']}" if inf["from_schema"] else inf["from_table"]
            inf_to = f"{inf['to_schema']}.{inf['to_table']}" if inf["to_schema"] else inf["to_table"]
            if inf_from not in edges:
                edges[inf_from] = []
            edges[inf_from].append((inf_from, inf["from_column"], inf_to, inf["to_column"]))
            if inf_to not in edges:
                edges[inf_to] = []
            edges[inf_to].append((inf_to, inf["to_column"], inf_from, inf["from_column"]))

    def resolve_table(name_input: str) -> str | None:
        if name_input in edges or name_input in {
            k for t in filtered.values()
            for k in [f"{t.get('schema', '')}.{t.get('name', '')}"]
        }:
            return name_input
        for key, table in filtered.items():
            full = f"{table.get('schema', '')}.{table.get('name', '')}"
            if table.get("name", "") == name_input or full == name_input or key == name_input:
                return full
        return None

    src = resolve_table(from_table)
    dst = resolve_table(to_table)
    if not src:
        raise HTTPException(status_code=404, detail=f"Table '{from_table}' not found in schema")
    if not dst:
        raise HTTPException(status_code=404, detail=f"Table '{to_table}' not found in schema")

    if src == dst:
        return {
            "connection_name": name,
            "from_table": from_table,
            "to_table": to_table,
            "paths": [{"hops": 0, "tables": [src], "joins": []}],
        }

    # BFS to find all paths up to max_hops
    paths: list[dict] = []
    queue: deque[tuple[str, list[str], list[dict]]] = deque()
    queue.append((src, [src], []))

    while queue:
        current, path_tables, path_joins = queue.popleft()
        if len(path_tables) - 1 >= max_hops:
            continue

        for from_t, from_col, to_t, to_col in edges.get(current, []):
            if to_t in path_tables:
                continue

            new_tables = path_tables + [to_t]
            new_joins = path_joins + [{
                "from": f"{from_t}.{from_col}",
                "to": f"{to_t}.{to_col}",
            }]

            if to_t == dst:
                paths.append({
                    "hops": len(new_joins),
                    "tables": new_tables,
                    "joins": new_joins,
                    "sql_hint": " JOIN ".join(
                        f"{t}" for t in new_tables
                    ) + " ON " + " AND ".join(
                        f"{j['from']} = {j['to']}" for j in new_joins
                    ),
                })
            else:
                queue.append((to_t, new_tables, new_joins))

    paths.sort(key=lambda p: p["hops"])

    return {
        "connection_name": name,
        "from_table": from_table,
        "to_table": to_table,
        "path_count": len(paths),
        "paths": paths[:10],
    }


@router.get("/connections/{name}/schema/sample-values", dependencies=[RequireScope("read")])
async def get_cached_sample_values(
    name: str,
    store: StoreD,
    table: str = Query(..., description="Full table name (e.g., 'public.customers')"),
    columns: str = Query(default="", description="Comma-separated column names. Empty = auto-select string/enum columns"),
    limit: int = Query(default=5, ge=1, le=20, description="Max distinct values per column"),
):
    """Get cached sample values for schema linking optimization."""
    info = await require_connection(store, name)

    # Check sample cache first
    cached_samples = schema_cache.get_sample_values(name, table)
    if cached_samples is not None:
        return {
            "connection_name": name,
            "table": table,
            "cached": True,
            "sample_values": cached_samples,
        }

    conn_str = await store.get_connection_string(name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored")

    try:
        extras = await store.get_credential_extras(name)
        async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
            col_list: list[str] = []
            if columns:
                col_list = [c.strip() for c in columns.split(",") if c.strip()]
            else:
                schema = schema_cache.get(name)
                if schema and table in schema:
                    for col in schema[table].get("columns", []):
                        col_type = col.get("type", "").lower()
                        if any(t in col_type for t in ("varchar", "text", "char", "string", "enum", "category")):
                            col_list.append(col["name"])
                        if len(col_list) >= 10:
                            break

            if not col_list:
                return {
                    "connection_name": name,
                    "table": table,
                    "cached": False,
                    "sample_values": {},
                    "message": "No columns selected -- provide column names or ensure schema is cached",
                }

            values = await connector.get_sample_values(table, col_list, limit=limit)

        if values:
            schema_cache.put_sample_values(name, table, values)

        return {
            "connection_name": name,
            "table": table,
            "cached": False,
            "sample_values": values,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=sanitize_db_error(str(e), info.db_type))


@router.get("/connections/{name}/schema/search", dependencies=[RequireScope("read")])
async def search_schema(
    name: str,
    store: StoreD,
    q: str = Query(..., min_length=1, description="Search query -- matches table names, column names, column comments"),
    include_samples: bool = Query(default=False, description="Include sample values for matched columns"),
    limit: int = Query(default=20, ge=1, le=100, description="Max tables to return"),
):
    """Semantic search across schema metadata for AI agent schema linking."""
    info = await require_connection(store, name)

    conn_str = await store.get_connection_string(name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored")

    cached = await get_or_fetch_schema(store, name, info)

    # Parse HEX-style prefix filters
    prefix_filters: dict[str, list[str]] = {"schema": [], "table": [], "column": [], "database": []}
    raw_terms: list[str] = []
    for part in q.split():
        part = part.strip()
        if not part:
            continue
        matched_prefix = False
        for prefix_key in prefix_filters:
            if part.lower().startswith(f"{prefix_key}:"):
                val = part[len(prefix_key) + 1 :].lower()
                if val:
                    prefix_filters[prefix_key].append(val)
                    matched_prefix = True
                break
        if not matched_prefix:
            raw_terms.append(part.lower())

    terms = raw_terms
    scored: list[tuple[float, str, dict]] = []

    for key, table in cached.items():
        score = 0.0
        table_name_lower = table.get("name", "").lower()
        schema_name_lower = table.get("schema", "").lower()
        matched_columns: list[str] = []

        if prefix_filters["schema"] and not any(f in schema_name_lower for f in prefix_filters["schema"]):
            continue
        if prefix_filters["database"] and not any(f in schema_name_lower for f in prefix_filters["database"]):
            continue
        if prefix_filters["table"] and not any(f in table_name_lower for f in prefix_filters["table"]):
            continue
        if prefix_filters["column"]:
            col_names_lower = [col.get("name", "").lower() for col in table.get("columns", [])]
            if not any(any(f in cn for cn in col_names_lower) for f in prefix_filters["column"]):
                continue
            for col in table.get("columns", []):
                cn = col.get("name", "").lower()
                if any(f in cn for f in prefix_filters["column"]):
                    matched_columns.append(col["name"])
            score += 5.0

        if not terms and any(prefix_filters[k] for k in prefix_filters):
            score = max(score, 5.0)

        for term in terms:
            if term == table_name_lower:
                score += 10.0
            elif table_name_lower.startswith(term):
                score += 5.0
            elif term in table_name_lower:
                score += 3.0
            elif _fuzzy_match(term, table_name_lower):
                score += 2.0

            if term in schema_name_lower:
                score += 1.0

            table_parts = set(table_name_lower.replace("-", "_").split("_"))
            if term in table_parts or term.rstrip("s") in table_parts:
                if term not in table_name_lower:
                    score += 2.5

            for col in table.get("columns", []):
                col_name = col.get("name", "").lower()
                col_comment = col.get("comment", "").lower()
                if term == col_name:
                    score += 4.0
                    matched_columns.append(col["name"])
                elif col_name.startswith(term):
                    score += 2.0
                    matched_columns.append(col["name"])
                elif term in col_name:
                    score += 1.5
                    matched_columns.append(col["name"])
                elif _fuzzy_match(term, col_name):
                    score += 1.0
                    matched_columns.append(col["name"])
                if col_comment and term in col_comment:
                    score += 1.0
                    if col["name"] not in matched_columns:
                        matched_columns.append(col["name"])

            for fk in table.get("foreign_keys", []):
                ref_table = fk.get("references_table", "").lower()
                if term in ref_table:
                    score += 2.0

            desc = table.get("description", "").lower()
            if desc and term in desc:
                score += 1.5

        if score > 0:
            result_table = dict(table)
            result_table["_matched_columns"] = list(dict.fromkeys(matched_columns))
            result_table["_relevance_score"] = round(score, 1)
            scored.append((score, key, result_table))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = {}
    for score, key, table in scored[:limit]:
        results[key] = table

    if include_samples and results:
        try:
            extras = await store.get_credential_extras(name)
            async with pool_manager.connection(info.db_type, conn_str, credential_extras=extras) as connector:
                for key, table in results.items():
                    matched_cols = table.get("_matched_columns", [])
                    if matched_cols and hasattr(connector, "get_sample_values"):
                        full_name = (
                            f"{table.get('schema', '')}.{table['name']}"
                            if table.get("schema")
                            else table["name"]
                        )
                        try:
                            samples = await connector.get_sample_values(full_name, matched_cols[:5], limit=3)
                            if samples:
                                table["_sample_values"] = samples
                        except Exception:
                            pass
        except Exception:
            pass

    return {
        "connection_name": name,
        "query": q,
        "result_count": len(results),
        "total_tables": len(cached),
        "tables": results,
    }


# ─── Schema Endorsements (HEX Data Browser pattern) ────────────────────────


@router.get("/connections/{name}/schema/endorsements", dependencies=[RequireScope("read")])
async def get_endorsements(name: str, store: StoreD):
    """Get schema endorsement config for a connection."""
    await require_connection(store, name)
    return await store.get_schema_endorsements(name)


@router.put("/connections/{name}/schema/endorsements", dependencies=[RequireScope("write")])
async def update_endorsements(name: str, store: StoreD, body: dict):
    """Set schema endorsement config for a connection.

    Body: {"endorsed": ["schema.table", ...], "hidden": ["schema.table", ...], "mode": "all|endorsed_only"}
    """
    await require_connection(store, name)
    mode = body.get("mode", "all")
    if mode not in ("all", "endorsed_only"):
        raise HTTPException(status_code=422, detail="mode must be 'all' or 'endorsed_only'")
    result = await store.set_schema_endorsements(name, body)
    schema_cache.invalidate(name)
    return result


# ─── Semantic Model (HEX inline schema editing) ───────────────────────────


@router.get("/connections/{name}/semantic-model", dependencies=[RequireScope("read")])
async def get_semantic_model(name: str, store: StoreD):
    """Get the semantic model for a connection."""
    await require_connection(store, name)
    return _load_semantic_model(name)


@router.put("/connections/{name}/semantic-model", dependencies=[RequireScope("write")])
async def update_semantic_model(name: str, store: StoreD, body: dict):
    """Update the semantic model for a connection.

    Body: {
        "tables": { "public.customers": { "description": "...", "columns": { ... } } },
        "joins": [...],
        "glossary": { "revenue": "orders.total_amount", ... }
    }
    """
    await require_connection(store, name)

    model = _load_semantic_model(name)
    if "tables" in body:
        for table_key, table_data in body["tables"].items():
            if table_key not in model["tables"]:
                model["tables"][table_key] = {"description": "", "columns": {}}
            if "description" in table_data:
                model["tables"][table_key]["description"] = table_data["description"]
            if "columns" in table_data:
                if "columns" not in model["tables"][table_key]:
                    model["tables"][table_key]["columns"] = {}
                for col_name, col_data in table_data["columns"].items():
                    if col_name not in model["tables"][table_key]["columns"]:
                        model["tables"][table_key]["columns"][col_name] = {}
                    model["tables"][table_key]["columns"][col_name].update(col_data)
    if "joins" in body:
        model["joins"] = body["joins"]
    if "glossary" in body:
        model["glossary"].update(body["glossary"])

    _save_semantic_model(name, model)
    return model


@router.post("/connections/{name}/semantic-model/generate", dependencies=[RequireScope("write")])
async def generate_semantic_model(name: str, store: StoreD):
    """Auto-generate a semantic model skeleton from the database schema."""
    info = await require_connection(store, name)
    cached = await get_or_fetch_schema(store, name, info)

    model = _load_semantic_model(name)

    tables_added = 0
    joins_added = 0
    glossary_added = 0

    for key, table in cached.items():
        if key not in model["tables"]:
            model["tables"][key] = {"description": "", "columns": {}}
        table_model = model["tables"][key]

        if not table_model.get("description") and table.get("description"):
            table_model["description"] = table["description"]
            tables_added += 1

        if "columns" not in table_model:
            table_model["columns"] = {}

        for col in table.get("columns", []):
            col_name = col.get("name", "")
            if col_name and col_name not in table_model["columns"]:
                table_model["columns"][col_name] = {}
            if col_name and not table_model["columns"].get(col_name, {}).get("description"):
                comment = col.get("comment", "")
                if comment:
                    table_model["columns"][col_name]["description"] = comment

        for fk in table.get("foreign_keys", []):
            from_col = fk.get("column", "")
            to_table = fk.get("references_table", "")
            to_col = fk.get("references_column", "")
            to_schema = fk.get("references_schema", table.get("schema", ""))
            to_key = f"{to_schema}.{to_table}" if to_schema else to_table

            join_entry = {
                "from": f"{key}.{from_col}",
                "to": f"{to_key}.{to_col}",
                "type": "many_to_one",
            }
            existing = any(
                j.get("from") == join_entry["from"] and j.get("to") == join_entry["to"]
                for j in model.get("joins", [])
            )
            if not existing:
                model["joins"].append(join_entry)
                joins_added += 1

        tbl_name = table.get("name", "")
        for col in table.get("columns", []):
            col_name = col.get("name", "")
            natural = col_name.replace("_", " ").replace("-", " ").lower()
            if len(natural) > 3 and natural not in model.get("glossary", {}):
                model["glossary"][natural] = f"{key}.{col_name}"
                glossary_added += 1

    _save_semantic_model(name, model)

    return {
        "tables": len(model["tables"]),
        "joins": len(model.get("joins", [])),
        "glossary_terms": len(model.get("glossary", {})),
        "generated": {
            "tables_with_descriptions": tables_added,
            "joins_added": joins_added,
            "glossary_terms_added": glossary_added,
        },
    }


# ─── Column Name Correction (Spider2.0 hallucination fix) ──────────────────


@router.post("/connections/{name}/schema/correct-columns", dependencies=[RequireScope("write")])
async def correct_columns(name: str, store: StoreD, body: dict):
    """Suggest corrections for hallucinated column names.

    Body: {"table": "public.customers", "columns": ["customer_name", "email_addr"]}
    """
    info = await require_connection(store, name)

    table_key = body.get("table", "")
    candidate_columns = body.get("columns", [])
    threshold = body.get("threshold", 0.5)

    if not table_key or not candidate_columns:
        raise HTTPException(status_code=422, detail="table and columns are required")

    cached = await get_or_fetch_schema(store, name, info)

    table_info = cached.get(table_key)
    if not table_info:
        best_table = None
        best_dist = 999
        for k in cached:
            d = _levenshtein(table_key.lower(), k.lower())
            if d < best_dist:
                best_dist = d
                best_table = k
        if best_table and best_dist <= len(table_key) * threshold:
            table_info = cached[best_table]
        else:
            return {"corrections": {}, "table_suggestion": best_table if best_table else None}

    actual_columns = {col["name"].lower(): col["name"] for col in table_info.get("columns", [])}
    corrections: dict = {}

    for candidate in candidate_columns:
        candidate_lower = candidate.lower()
        if candidate_lower in actual_columns:
            continue

        best_match = None
        best_dist = 999
        for col_lower, col_name in actual_columns.items():
            d = _levenshtein(candidate_lower, col_lower)
            if d < best_dist:
                best_dist = d
                best_match = col_name

        max_dist = max(len(candidate), 1) * threshold
        if best_match and best_dist <= max_dist:
            corrections[candidate] = {
                "suggestion": best_match,
                "distance": best_dist,
                "confidence": round(1.0 - (best_dist / max(len(candidate), 1)), 2),
            }
        else:
            corrections[candidate] = {"suggestion": None, "distance": best_dist, "confidence": 0.0}

    return {
        "table": table_key,
        "corrections": corrections,
        "total_columns": len(actual_columns),
    }


# ─── Column Exploration (ReFoRCE pattern) ────────────────────────────────────


@router.post("/connections/{name}/schema/explore-columns", dependencies=[RequireScope("write")])
async def explore_columns_deep(name: str, store: StoreD, body: dict):
    """Deep column exploration for complex Spider2.0 queries.

    Body: {
        "table": "public.orders",
        "columns": ["status", "total_amount"],
        "include_stats": true,
        "include_values": true,
        "value_limit": 10
    }
    """
    info = await require_connection(store, name)

    table_key = body.get("table", "")
    requested_cols = body.get("columns", [])
    include_stats = body.get("include_stats", True)
    include_values = body.get("include_values", True)
    value_limit = min(body.get("value_limit", 10), 25)

    if not table_key:
        raise HTTPException(status_code=422, detail="table is required")

    cached = await get_or_fetch_schema(store, name, info)

    table_info = cached.get(table_key)
    if not table_info:
        raise HTTPException(status_code=404, detail=f"Table '{table_key}' not found in schema")

    all_columns = table_info.get("columns", [])
    if requested_cols:
        col_set = {c.lower() for c in requested_cols}
        explore_cols = [c for c in all_columns if c["name"].lower() in col_set]
    else:
        explore_cols = all_columns

    db_type = info.db_type
    numeric_types = {
        "integer", "int", "bigint", "smallint", "numeric", "decimal",
        "float", "double", "real", "number", "int4", "int8", "int2",
        "float4", "float8", "Float32", "Float64", "UInt32", "UInt64",
        "Int32", "Int64", "INTEGER", "BIGINT", "FLOAT64", "NUMERIC", "DECIMAL",
    }

    conn_str = await store.get_connection_string(name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored")
    extras = await store.get_credential_extras(name)

    result_cols: list[dict] = []

    async with pool_manager.connection(db_type, conn_str, credential_extras=extras) as connector:
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
                c for c in explore_cols
                if c.get("type", "").lower().rstrip("()0123456789, ").split("(")[0] in numeric_types
            ]
            if num_cols:
                stat_parts = []
                for c in num_cols[:15]:
                    cn = c["name"]
                    q = (
                        '"' if db_type in ("postgres", "redshift", "snowflake", "duckdb", "sqlite", "trino")
                        else '`' if db_type in ("mysql", "clickhouse", "databricks")
                        else '['
                    )
                    if q == '[':
                        qo, qc = '[', ']'
                    else:
                        qo = qc = q
                    safe = cn.replace(qc, qc + qc)
                    stat_parts.append(f"MIN({qo}{safe}{qc})")
                    stat_parts.append(f"MAX({qo}{safe}{qc})")
                    stat_parts.append(f"AVG(CAST({qo}{safe}{qc} AS FLOAT))")
                try:
                    stat_sql = f"SELECT {', '.join(stat_parts)} FROM {table_key}"
                    if db_type == "mssql":
                        stat_sql = f"SELECT TOP 1000000 {', '.join(stat_parts)} FROM {table_key}"
                    rows = await connector.execute(stat_sql, timeout=15)
                    if rows:
                        row = rows[0]
                        vals = list(row.values())
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
