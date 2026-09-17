"""Deep table and column exploration endpoints (explore-table, explore-columns)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, Query

from gateway.api.deps import (
    StoreD,
    get_or_fetch_schema,
    require_connection,
)
from gateway.api.schema._identifiers import _quote_table_name
from gateway.api.schema._router import router
from gateway.connectors.pool_manager import pool_manager
from gateway.connectors.schema_cache import schema_cache
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
        # Tolerant resolution: optional schema prefix, case-insensitive key,
        # then bare-name match (same semantics as describe_table).
        t_lower = table_key.lower()
        bare = t_lower.split(".")[-1]
        for key, tbl in cached.items():
            if key.lower() == t_lower:
                table_key, table_info = key, tbl
                break
        else:
            for key, tbl in cached.items():
                if tbl.get("name", "").lower() == bare:
                    table_key, table_info = key, tbl
                    break
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
