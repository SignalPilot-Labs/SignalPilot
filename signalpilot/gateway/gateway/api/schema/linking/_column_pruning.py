"""Column pruning helpers for schema linking — determines which columns to include per table."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def build_fk_target_cols(linked_keys: set[str], filtered: dict[str, Any]) -> dict[str, set[str]]:
    """Build a mapping of table_key -> set of column names that are FK targets from linked tables.

    For example, if orders.customer_id → customers.id, then customers.id must be kept.
    """
    fk_target_cols: dict[str, set[str]] = {}
    for lk in linked_keys:
        if lk not in filtered:
            continue
        for fk in filtered[lk].get("foreign_keys", []):
            ref_table = fk.get("references_table", "")
            ref_col = fk.get("references_column", "")
            # Find the matching linked table key
            for candidate_key in linked_keys:
                if filtered.get(candidate_key, {}).get("name", "") == ref_table:
                    if candidate_key not in fk_target_cols:
                        fk_target_cols[candidate_key] = set()
                    fk_target_cols[candidate_key].add(ref_col)
                    break
    return fk_target_cols


def make_column_pruner(
    table_scores: dict[str, float],
    column_scores: dict[str, dict[str, float]],
    fk_target_cols: dict[str, set[str]],
    prune_columns: bool,
) -> Callable[[str, dict], list[dict]]:
    """Return a closure that prunes columns for a given table.

    Always includes: PK columns, FK columns, FK-referenced columns, and
    columns with relevance score > 0.
    For high-scoring tables (>= 5.0), includes ALL columns (they're clearly relevant).
    For lower-scoring tables (FK-connected), only includes structural + matched columns.

    RSL-SQL / EDBT 2026: "missing a column is fatal; extras are tolerable noise."
    We err on the side of keeping columns, especially join-path columns.
    """

    def _prune_columns(table_key: str, table_data: dict) -> list[dict]:
        """Return only relevant columns for a table, keeping PKs and FKs always."""
        t_score = table_scores.get(table_key, 0)
        # High-relevance tables: keep all columns (the whole table matters)
        if t_score >= 5.0 or not prune_columns:
            return table_data.get("columns", [])

        col_relevance = column_scores.get(table_key, {})
        fk_cols = {fk.get("column", "") for fk in table_data.get("foreign_keys", [])}
        fk_targets = fk_target_cols.get(table_key, set())

        kept = []
        for col in table_data.get("columns", []):
            col_name = col.get("name", "")
            # Always keep: PKs, FK columns, FK-target columns, and columns with question relevance
            if col.get("primary_key"):
                kept.append(col)
            elif col_name in fk_cols:
                kept.append(col)
            elif col_name in fk_targets:
                kept.append(col)
            elif col_relevance.get(col_name, 0) > 0:
                kept.append(col)
        # If pruning removed everything, keep all (safety)
        return kept if kept else table_data.get("columns", [])

    return _prune_columns
