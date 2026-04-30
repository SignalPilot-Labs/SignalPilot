"""Schema refinement endpoint — two-pass schema refinement for Spider2.0."""

from __future__ import annotations

import logging

from fastapi import HTTPException, Request

from gateway.api.deps import (
    StoreD,
    get_filtered_schema,
    require_connection,
)
from gateway.api.schema._constants import _re_refine
from gateway.api.schema._router import router
from gateway.connectors.schema_cache import schema_cache
from gateway.schema.utils import _infer_implicit_joins
from gateway.security.scope_guard import RequireScope

logger = logging.getLogger(__name__)


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
                referenced_tables.add(g.lower().strip("`\"'[]"))

    col_patterns = [
        r'(?:SELECT|WHERE|AND|OR|ON|BY|HAVING|SET)\s+(?:`|"|\'|\[)?(\w+)(?:`|"|\'|\])?',
        r"(\w+)\s*(?:=|<|>|!=|<>|LIKE|IN|BETWEEN|IS)",
    ]
    sql_keywords = {
        "select",
        "from",
        "where",
        "and",
        "or",
        "not",
        "null",
        "true",
        "false",
        "case",
        "when",
        "then",
        "else",
        "end",
        "as",
        "in",
        "is",
        "on",
        "by",
        "having",
        "set",
        "all",
        "distinct",
        "count",
        "sum",
        "avg",
        "min",
        "max",
        "like",
        "between",
        "exists",
        "any",
        "group",
        "order",
        "limit",
        "offset",
        "union",
        "except",
        "intersect",
        "asc",
        "desc",
    }
    for pattern in col_patterns:
        for match in _re_refine.finditer(pattern, sql_clean, _re_refine.IGNORECASE):
            col = match.group(1).lower().strip("`\"'[]")
            if col not in sql_keywords:
                referenced_columns.add(col)

    # Also extract dotted references like t.column_name
    for match in _re_refine.finditer(r"(\w+)\.(\w+)", sql_clean):
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
