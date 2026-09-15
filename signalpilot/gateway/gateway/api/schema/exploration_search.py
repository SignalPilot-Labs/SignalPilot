"""Schema change feed, filtered-schema and schema search endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, Query

from gateway.api.deps import (
    StoreD,
    get_filtered_schema,
    get_or_fetch_schema,
    require_connection,
)
from gateway.api.schema._router import router
from gateway.api.schema._scoring import _fuzzy_match
from gateway.connectors.pool_manager import pool_manager
from gateway.connectors.schema_cache import schema_cache
from gateway.security.scope_guard import RequireScope

logger = logging.getLogger(__name__)


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
