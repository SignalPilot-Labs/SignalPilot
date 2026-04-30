"""Format renderers for schema linking: DDL, condensed, compact, and JSON output."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from gateway.api.schema._scoring import _build_join_hints
from gateway.api.schema.linking._data import _DIALECT_HINTS
from gateway.api.schema.linking._hints import build_query_hints
from gateway.api.schema.linking._samples import maybe_fetch_missing_samples
from gateway.connectors.schema_cache import schema_cache
from gateway.schema.utils import TYPE_COMPRESSION_MAP, compress_type


def render_condensed(
    linked_keys: set[str],
    filtered: dict[str, Any],
    table_scores: dict[str, float],
    column_scores: dict[str, dict[str, float]],
    prune_fn: Callable[[str, dict], list[dict]],
    name: str,
    question: str,
    info: Any,
    small_schema: bool,
) -> dict[str, Any]:
    """Render condensed DDL: minimal token usage — pruned columns, no annotations, compressed types."""
    condensed_lines = []
    total_cols_original = 0
    total_cols_kept = 0
    for key in sorted(linked_keys):
        if key not in filtered:
            continue
        t = filtered[key]
        table_name = f"{t.get('schema', '')}.{t.get('name', '')}"
        all_cols = t.get("columns", [])
        kept_cols = prune_fn(key, t)
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
            col_parts.append(
                f"  FOREIGN KEY ({fk['column']}) REFERENCES {fk.get('references_table', '')}({fk.get('references_column', '')})"
            )
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
        "full_schema": small_schema,
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


def render_compact(
    linked_keys: set[str],
    filtered: dict[str, Any],
    table_scores: dict[str, float],
    column_scores: dict[str, dict[str, float]],
    prune_fn: Callable[[str, dict], list[dict]],
    name: str,
    question: str,
    info: Any,
    small_schema: bool,
) -> dict[str, Any]:
    """Render compact one-line-per-table format."""
    lines = []
    for key in sorted(linked_keys):
        if key not in filtered:
            continue
        t = filtered[key]
        col_strs = []
        kept_cols = prune_fn(key, t)
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
        "full_schema": small_schema,
        "linked_tables": len(linked_keys),
        "total_tables": len(filtered),
        "scores": {k: round(table_scores.get(k, 0), 1) for k in sorted(linked_keys) if table_scores.get(k, 0) > 0},
        "schema": "\n".join(lines),
    }


def render_json(
    linked_keys: set[str],
    filtered: dict[str, Any],
    table_scores: dict[str, float],
    column_scores: dict[str, dict[str, float]],
    prune_fn: Callable[[str, dict], list[dict]],
    name: str,
    question: str,
    info: Any,
    small_schema: bool,
) -> dict[str, Any]:
    """Render JSON format with full table data."""
    linked_schema = {k: filtered[k] for k in sorted(linked_keys) if k in filtered}
    return {
        "connection_name": name,
        "question": question,
        "format": "json",
        "full_schema": small_schema,
        "linked_tables": len(linked_keys),
        "total_tables": len(filtered),
        "scores": {k: table_scores.get(k, 0) for k in sorted(linked_keys)},
        "tables": linked_schema,
    }


async def render_ddl(
    store: Any,
    info: Any,
    name: str,
    question: str,
    question_lower: str,
    linked_keys: set[str],
    filtered: dict[str, Any],
    table_scores: dict[str, float],
    column_scores: dict[str, dict[str, float]],
    prune_fn: Callable[[str, dict], list[dict]],
    small_schema: bool,
    is_aggregation: bool,
    is_temporal: bool,
) -> dict[str, Any]:
    """Render DDL format (default — preferred by Spider2.0 SOTA).

    This is the only async renderer; it triggers sample-value fetching and builds query hints.
    """
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
        ddl_cols = prune_fn(key, t)
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
            col_parts.append(
                f"  FOREIGN KEY ({fk['column']}) REFERENCES {fk.get('references_table', '')}({fk.get('references_column', '')})"
            )
        rc = t.get("row_count", 0)
        # Build metadata comment
        meta_parts = []
        if rc:
            meta_parts.append(f"{rc:,} rows" if rc < 1_000_000 else f"{rc / 1_000_000:.1f}M rows")
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
    await maybe_fetch_missing_samples(store, info, name, linked_keys, filtered)

    # Build join hints and dialect info using extracted helpers
    join_hints = _build_join_hints(linked_keys, filtered)

    result: dict[str, Any] = {
        "connection_name": name,
        "question": question,
        "format": "ddl",
        "full_schema": small_schema,
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
    query_hints = build_query_hints(question_lower, info.db_type, is_aggregation, is_temporal)
    if query_hints:
        result["query_hints"] = query_hints

    return result
