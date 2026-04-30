"""Schema linking endpoint — find tables/columns relevant to a natural language question."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Query

from gateway.api.deps import StoreD, get_filtered_schema, require_connection
from gateway.api.schema._router import router
from gateway.api.schema.linking._column_pruning import build_fk_target_cols, make_column_pruner
from gateway.api.schema.linking._data import _AGG_KEYWORDS, _TIME_KEYWORDS
from gateway.api.schema.linking._renderers import render_compact, render_condensed, render_ddl, render_json
from gateway.api.schema.linking._scoring_pass import apply_fk_propagation, score_tables, select_linked_keys
from gateway.api.schema.linking._terms import extract_terms
from gateway.security.scope_guard import RequireScope

logger = logging.getLogger(__name__)


@router.get("/connections/{name}/schema/link", dependencies=[RequireScope("read")])
async def schema_link(
    name: str,
    store: StoreD,
    question: str = Query(..., max_length=2000, description="Natural language question to link schema for"),
    format: str = Query(
        default="ddl",
        pattern="^(ddl|compact|json|condensed)$",
        description="Output format: ddl (full), condensed (pruned columns), compact (one-line), json",
    ),
    max_tables: int = Query(default=20, ge=1, le=100, description="Max tables in linked schema"),
    prune_columns: bool = Query(
        default=False, description="Drop columns with 0 relevance from low-scoring tables (reduces token count 30-60%%)"
    ),
) -> Any:
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

    question_lower = question.lower()
    terms, ngram_terms = extract_terms(question_lower)

    question_words = set(question_lower.split())
    is_aggregation = bool(question_words & _AGG_KEYWORDS)
    is_temporal = bool(question_words & _TIME_KEYWORDS)

    table_scores, column_scores = score_tables(
        filtered, terms, ngram_terms, question_lower, name, is_aggregation, is_temporal
    )
    apply_fk_propagation(table_scores, filtered)
    linked_keys = select_linked_keys(table_scores, filtered, max_tables, _small_schema)

    fk_target_cols = build_fk_target_cols(linked_keys, filtered)
    prune_fn = make_column_pruner(table_scores, column_scores, fk_target_cols, prune_columns)

    if format == "condensed":
        return render_condensed(
            linked_keys, filtered, table_scores, column_scores, prune_fn, name, question, info, _small_schema
        )
    if format == "compact":
        return render_compact(
            linked_keys, filtered, table_scores, column_scores, prune_fn, name, question, info, _small_schema
        )
    if format == "json":
        return render_json(
            linked_keys, filtered, table_scores, column_scores, prune_fn, name, question, info, _small_schema
        )
    return await render_ddl(
        store,
        info,
        name,
        question,
        question_lower,
        linked_keys,
        filtered,
        table_scores,
        column_scores,
        prune_fn,
        _small_schema,
        is_aggregation,
        is_temporal,
    )
