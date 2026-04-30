"""FK-graph relationship endpoints."""

from __future__ import annotations

import logging
from collections import deque

from fastapi import HTTPException, Query

from gateway.api.deps import (
    StoreD,
    get_filtered_schema,
    require_connection,
    sanitize_db_error,
)
from gateway.api.schema._router import router
from gateway.connectors.pool_manager import pool_manager
from gateway.connectors.schema_cache import schema_cache
from gateway.schema_utils import _infer_implicit_joins
from gateway.scope_guard import RequireScope

logger = logging.getLogger(__name__)


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
    for _key, table in filtered.items():
        tbl_schema = table.get("schema", "")
        tbl_name = table.get("name", "")
        for fk in table.get("foreign_keys", []):
            ref_schema = fk.get("references_schema", tbl_schema)
            relationships.append(
                {
                    "from_schema": tbl_schema,
                    "from_table": tbl_name,
                    "from_column": fk["column"],
                    "to_schema": ref_schema,
                    "to_table": fk["references_table"],
                    "to_column": fk["references_column"],
                }
            )
    explicit_count = len(relationships)

    # Add implicit/inferred joins
    implicit_count = 0
    if include_implicit:
        inferred = _infer_implicit_joins(filtered)
        explicit_set = {
            (r["from_table"].lower(), r["from_column"].lower(), r["to_table"].lower(), r["to_column"].lower())
            for r in relationships
        }
        for inf in inferred:
            edge = (
                inf["from_table"].lower(),
                inf["from_column"].lower(),
                inf["to_table"].lower(),
                inf["to_column"].lower(),
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
            lines.append(f"{from_qual}.{r['from_column']} → {to_qual}.{r['to_column']}{suffix}")
        return {
            "connection_name": name,
            "format": "compact",
            "relationship_count": len(relationships),
            "explicit_count": explicit_count,
            "inferred_count": implicit_count,
            "relationships": lines,
        }

    if format == "graph":
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

    # full
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
    from_table: str = Query(..., max_length=256, description="Source table (e.g., 'public.orders')"),
    to_table: str = Query(..., max_length=256, description="Target table (e.g., 'public.products')"),
    max_hops: int = Query(default=4, ge=1, le=6, description="Maximum FK hops to search"),
    include_implicit: bool = Query(default=True, description="Include inferred joins from column naming conventions"),
):
    """Find all join paths between two tables -- critical for Spider2.0 multi-hop queries."""
    info = await require_connection(store, name)
    filtered = await get_filtered_schema(store, name, info)

    # Build bidirectional adjacency list with join info
    edges: dict[str, list[tuple[str, str, str, str]]] = {}
    for _key, table in filtered.items():
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
            k for t in filtered.values() for k in [f"{t.get('schema', '')}.{t.get('name', '')}"]
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

            new_tables = [*path_tables, to_t]
            new_joins = [*path_joins, {"from": f"{from_t}.{from_col}", "to": f"{to_t}.{to_col}"}]

            if to_t == dst:
                paths.append(
                    {
                        "hops": len(new_joins),
                        "tables": new_tables,
                        "joins": new_joins,
                        "sql_hint": " JOIN ".join(f"{t}" for t in new_tables)
                        + " ON "
                        + " AND ".join(f"{j['from']} = {j['to']}" for j in new_joins),
                    }
                )
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
    columns: str = Query(
        default="", max_length=2000, description="Comma-separated column names. Empty = auto-select string/enum columns"
    ),
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
        async with pool_manager.connection(
            info.db_type, conn_str, credential_extras=extras, connection_name=name
        ) as connector:
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
