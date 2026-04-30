"""Table and column scoring, FK propagation, and linked-key selection for schema linking."""

from __future__ import annotations

from typing import Any

from gateway.api.schema.linking._data import _NUMERIC_TYPES, _TIME_TYPES
from gateway.connectors.schema_cache import schema_cache


def score_tables(
    filtered: dict[str, Any],
    terms: list[str],
    ngram_terms: list[str],
    question_lower: str,
    name: str,
    is_aggregation: bool,
    is_temporal: bool,
) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    """Score each table and column by relevance to the question terms.

    Returns:
        table_scores: Mapping of table_key -> relevance score.
        column_scores: Mapping of table_key -> {col_name: score}.
    """
    table_scores: dict[str, float] = {}
    column_scores: dict[str, dict[str, float]] = {}  # table_key -> {col_name: score}
    for table_key, table_data in filtered.items():
        score = 0.0
        col_scores: dict[str, float] = {}
        table_name_lower = table_data.get("name", "").lower()

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
        for ng in ngram_terms:
            if ng == table_name_lower:
                score += 12.0  # Exact compound match is very strong
            elif ng in table_name_lower:
                score += 6.0

        # Question-type boosting: prefer tables with relevant column types
        if is_aggregation and score > 0:
            numeric_cols = sum(
                1 for c in table_data.get("columns", []) if c.get("type", "").lower().split("(")[0] in _NUMERIC_TYPES
            )
            if numeric_cols > 0:
                score += min(numeric_cols * 0.5, 3.0)

        if is_temporal and score > 0:
            time_cols = sum(
                1
                for c in table_data.get("columns", [])
                if c.get("type", "").lower().split("(")[0] in _TIME_TYPES
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

    return table_scores, column_scores


def apply_fk_propagation(table_scores: dict[str, float], filtered: dict[str, Any]) -> None:
    """Apply FK-propagated scoring in-place.

    Tables FK-connected to high-scoring tables get a fraction of that score.
    This ensures join-path tables are included AND ordered by relevance.
    """
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


def select_linked_keys(
    table_scores: dict[str, float],
    filtered: dict[str, Any],
    max_tables: int,
    small_schema: bool,
) -> set[str]:
    """Select the top-N table keys to include in the linked schema.

    Returns:
        Set of table keys to include.
    """
    # Step 4: Select top tables by score
    scored_tables = sorted(table_scores.items(), key=lambda x: (-x[1], x[0]))
    linked_keys: set[str] = set()

    # Small-schema bypass: include ALL tables when schema is small enough.
    # Per "The Death of Schema Linking?" (OpenReview): for schemas that fit
    # the context window, skipping schema linking yields higher accuracy
    # because no relevant table can be missed. #1 on BIRD benchmark (71.83%).
    if small_schema:
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

        linked_keys = set(sorted(filtered.keys(), key=_fb_relevance)[: min(max_tables, 10)])

    return linked_keys
