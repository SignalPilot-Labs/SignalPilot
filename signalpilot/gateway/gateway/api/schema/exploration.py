"""Schema exploration, diff, overview, and search endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, Query

from gateway.api.deps import (
    StoreD,
    get_filtered_schema,
    get_or_fetch_schema,
    require_connection,
    sanitize_db_error,
)
from gateway.api.schema._identifiers import _quote_table_name
from gateway.api.schema._router import router
from gateway.api.schema._scoring import _fuzzy_match
from gateway.connectors.pool_manager import pool_manager
from gateway.connectors.schema_cache import schema_cache
from gateway.schema_utils import _infer_implicit_joins
from gateway.security.scope_guard import RequireScope

logger = logging.getLogger(__name__)


@router.get("/connections/{name}/schema/explore-table", dependencies=[RequireScope("read")])
async def explore_table(
    name: str,
    store: StoreD,
    table: str = Query(..., max_length=256, description="Full table name (e.g., 'public.customers')"),
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
                result["referenced_by"].append(
                    {
                        "table": key,
                        "column": fk["column"],
                        "references_column": fk["references_column"],
                    }
                )

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
                    async with pool_manager.connection(
                        info.db_type, conn_str, credential_extras=extras, connection_name=name
                    ) as connector:
                        samples = await connector.get_sample_values(table, string_cols[:10], limit=sample_limit)
                    if samples:
                        schema_cache.put_sample_values(name, table, samples)
                        result["sample_values"] = samples
            except Exception:
                pass

    return result


@router.post("/connections/{name}/schema/explore-columns", dependencies=[RequireScope("read")])
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
    table_key = body.get("table", "")
    requested_cols = body.get("columns", [])
    include_stats = body.get("include_stats", True)
    include_values = body.get("include_values", True)
    value_limit = min(body.get("value_limit", 10), 25)

    if not table_key:
        raise HTTPException(status_code=422, detail="table is required")
    if len(requested_cols) > 50:
        raise HTTPException(status_code=422, detail="columns list must have at most 50 items")

    info = await require_connection(store, name)
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
        "integer",
        "int",
        "bigint",
        "smallint",
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
        "Float32",
        "Float64",
        "UInt32",
        "UInt64",
        "Int32",
        "Int64",
        "INTEGER",
        "BIGINT",
        "FLOAT64",
        "NUMERIC",
        "DECIMAL",
    }

    conn_str = await store.get_connection_string(name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored")
    extras = await store.get_credential_extras(name)

    result_cols: list[dict] = []

    async with pool_manager.connection(db_type, conn_str, credential_extras=extras, connection_name=name) as connector:
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
                if c.get("type", "").lower().rstrip("()0123456789, ").split("(")[0] in numeric_types
            ]
            if num_cols:
                stat_parts = []
                for c in num_cols[:15]:
                    cn = c["name"]
                    q = (
                        '"'
                        if db_type in ("postgres", "redshift", "snowflake", "duckdb", "sqlite", "trino")
                        else "`"
                        if db_type in ("mysql", "clickhouse", "databricks")
                        else "["
                    )
                    if q == "[":
                        qo, qc = "[", "]"
                    else:
                        qo = qc = q
                    safe = cn.replace(qc, qc + qc)
                    stat_parts.append(f"MIN({qo}{safe}{qc})")
                    stat_parts.append(f"MAX({qo}{safe}{qc})")
                    stat_parts.append(f"AVG(CAST({qo}{safe}{qc} AS FLOAT))")
                try:
                    q_table_key = _quote_table_name(table_key, q)
                    stat_sql = f"SELECT {', '.join(stat_parts)} FROM {q_table_key}"
                    if db_type == "mssql":
                        stat_sql = f"SELECT TOP 1000000 {', '.join(stat_parts)} FROM {q_table_key}"
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
            "engine",
            "sorting_key",
            "diststyle",
            "sortkey",
            "clustering_key",
            "partitioning",
            "clustering_fields",
            "size_bytes",
            "size_mb",
            "total_bytes",
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
        "recommendation": ("compact" if total_columns > 200 else "full" if total_columns < 50 else "enriched"),
        "inferred_joins": len(inferred_joins),
        "spider2_hints": {
            "needs_compression": total_columns > 500,
            "has_partitioned_tables": any("_20" in (t.get("name", "") or "") for t in filtered.values()),
            "join_complexity": (
                "high"
                if (total_fks + len(inferred_joins)) > 15
                else "medium"
                if (total_fks + len(inferred_joins)) > 5
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
        async with pool_manager.connection(
            info.db_type, conn_str, credential_extras=extras, connection_name=name
        ) as connector:
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
    await require_connection(store, name)

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
    schema_prefix: str = Query(
        default="", description="Filter by schema/database prefix (e.g., 'public', 'analytics')"
    ),
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


@router.get("/connections/{name}/schema/search", dependencies=[RequireScope("read")])
async def search_schema(
    name: str,
    store: StoreD,
    q: str = Query(
        ...,
        min_length=1,
        max_length=500,
        description="Search query -- matches table names, column names, column comments",
    ),
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
    for _score, key, table in scored[:limit]:
        results[key] = table

    if include_samples and results:
        try:
            extras = await store.get_credential_extras(name)
            async with pool_manager.connection(
                info.db_type, conn_str, credential_extras=extras, connection_name=name
            ) as connector:
                for _key, table in results.items():
                    matched_cols = table.get("_matched_columns", [])
                    if matched_cols and hasattr(connector, "get_sample_values"):
                        full_name = (
                            f"{table.get('schema', '')}.{table['name']}" if table.get("schema") else table["name"]
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
