"""Compact/enriched schema representation endpoints."""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import HTTPException, Query

from gateway.api.deps import (
    StoreD,
    apply_schema_filter,
    get_schema_filters,
    require_connection,
    sanitize_db_error,
)
from gateway.api.schema._router import router
from gateway.connectors.pool_manager import pool_manager
from gateway.connectors.schema_cache import schema_cache
from gateway.schema_utils import (
    STRING_COLUMN_TYPES,
    _deduplicate_partitioned_tables,
    _infer_implicit_joins,
    compress_type,
)
from gateway.security.scope_guard import RequireScope

logger = logging.getLogger(__name__)


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
        async with pool_manager.connection(
            info.db_type, conn_str, credential_extras=extras, connection_name=name
        ) as connector:
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
        async with pool_manager.connection(
            info.db_type, conn_str, credential_extras=extras, connection_name=name
        ) as connector:
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
                name_str += f"→{fk_ref}"
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
            partition_note = f" [×{count} partitions: {base}_*]"

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
        async with pool_manager.connection(
            info.db_type, conn_str, credential_extras=extras, connection_name=name
        ) as connector:
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
            match = re.match(r"^([a-zA-Z]+_)", tname)
            if match:
                prefix = match.group(1)
                if prefix not in prefix_groups:
                    prefix_groups[prefix] = []
                prefix_groups[prefix].append(key)

        for _prefix, members in prefix_groups.items():
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
            meta_hints.append(
                f"{rc / 1_000_000:.1f}M rows"
                if rc >= 1_000_000
                else f"{rc / 1_000:.0f}K rows"
                if rc >= 1000
                else f"{rc} rows"
            )
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
            comment_parts.append(f"{rc:,} rows" if rc < 1_000_000 else f"{rc / 1_000_000:.1f}M rows")
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
