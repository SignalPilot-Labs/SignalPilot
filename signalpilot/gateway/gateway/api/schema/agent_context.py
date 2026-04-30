"""Agent-context endpoint — single-call schema context for SQL generation agents."""

from __future__ import annotations

import logging
import re

from fastapi import HTTPException, Query

from gateway.api.deps import (
    StoreD,
    apply_schema_filter,
    get_schema_filters,
    require_connection,
)
from gateway.api.schema._router import router
from gateway.api.schema._semantic_store import _load_semantic_model
from gateway.connectors.pool_manager import pool_manager
from gateway.connectors.schema_cache import schema_cache
from gateway.schema_utils import (
    _deduplicate_partitioned_tables,
    _infer_implicit_joins,
)
from gateway.scope_guard import RequireScope

logger = logging.getLogger(__name__)


# ───────────────────────────────────────────────────────────────────────────
# GET /connections/{name}/schema/agent-context
# ───────────────────────────────────────────────────────────────────────────


@router.get("/connections/{name}/schema/agent-context", dependencies=[RequireScope("read")])
async def get_agent_context(
    name: str,
    store: StoreD,
    question: str = Query(
        default="", max_length=2000, description="Optional question for schema linking — omit for full schema"
    ),
    max_tables: int = Query(default=30, ge=1, le=100, description="Max tables to include"),
    include_samples: bool = Query(default=True, description="Include cached sample values for string columns"),
    progressive: bool = Query(
        default=False,
        description="Progressive disclosure: full DDL for top tables, compact one-liners for the rest (saves 40-60%% tokens)",
    ),
    full_ddl_count: int = Query(
        default=8, ge=1, le=50, description="Number of top-scoring tables to show full DDL for (when progressive=true)"
    ),
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
        async with pool_manager.connection(
            info.db_type, conn_str, credential_extras=extras, connection_name=name
        ) as connector:
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
        stopwords = {
            "the",
            "and",
            "for",
            "are",
            "but",
            "not",
            "you",
            "all",
            "can",
            "had",
            "her",
            "was",
            "one",
            "our",
            "out",
            "has",
            "how",
            "many",
            "much",
            "what",
            "which",
            "show",
            "find",
            "list",
            "give",
            "tell",
            "from",
            "with",
            "that",
            "this",
            "have",
            "will",
            "select",
            "where",
            "group",
            "having",
            "limit",
            "table",
            "column",
            "database",
        }
        terms = [
            w for w in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", question.lower()) if len(w) >= 3 and w not in stopwords
        ]
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
        q_terms = [w.lower() for w in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", question)] if question else []
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
                parts.append(f"FK: {fk.get('column', '?')}→{ref}")
            for ij in inferred_map.get(key, []):
                parts.append(f"join: {ij['from_column']}→{ij['to_table']}")
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
            ref = (
                f"{fk.get('references_schema', '')}.{fk['references_table']}"
                if fk.get("references_schema")
                else fk["references_table"]
            )
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
