"""Pure scoring helpers used by link, refine, search, and agent-context endpoints."""

from __future__ import annotations

from typing import Any

from gateway.schema.utils import _infer_implicit_joins


def _levenshtein(s1: str, s2: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (0 if c1 == c2 else 1)))
        prev = curr
    return prev[len(s2)]


def _fuzzy_match(query: str, target: str, max_distance: int = 2) -> bool:
    """Simple edit-distance fuzzy matching for schema search."""
    if len(query) < 4 or len(target) < 3:
        return False
    if abs(len(query) - len(target)) > max_distance:
        if len(target) > len(query) + max_distance:
            for i in range(len(target) - len(query) + 1):
                window = target[i : i + len(query)]
                if _levenshtein(query, window) <= max_distance:
                    return True
        return False
    return _levenshtein(query, target) <= max_distance


def _build_join_hints(linked_keys: set[str], filtered: dict[str, Any]) -> list[str]:
    """Build FK-based and inferred join hints between linked tables."""
    join_hints: list[str] = []
    _seen_joins: set[tuple] = set()
    for key in linked_keys:
        if key not in filtered:
            continue
        t = filtered[key]
        for fk in t.get("foreign_keys", []):
            ref_table = fk.get("references_table", "")
            ref_col = fk.get("references_column", "")
            fk_col = fk.get("column", "")
            for ref_key in linked_keys:
                if filtered.get(ref_key, {}).get("name", "") == ref_table:
                    pair = tuple(sorted([key, ref_key]))
                    if pair not in _seen_joins:
                        _seen_joins.add(pair)
                        join_hints.append(f"{t['name']}.{fk_col} = {ref_table}.{ref_col}")
                    break
    inferred = _infer_implicit_joins(filtered)
    for ij in inferred:
        from_name, to_name = ij.get("from_table", ""), ij.get("to_table", "")
        from_col, to_col = ij.get("from_column", ""), ij.get("to_column", "")
        from_in = any(filtered.get(k, {}).get("name", "") == from_name for k in linked_keys)
        to_in = any(filtered.get(k, {}).get("name", "") == to_name for k in linked_keys)
        if from_in and to_in:
            hint = f"{from_name}.{from_col} = {to_name}.{to_col} (inferred)"
            if hint not in join_hints:
                join_hints.append(hint)
    return join_hints
