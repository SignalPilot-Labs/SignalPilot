"""Generalizable post-save harness checks.

Each check is a small pure function that inspects (question, sql, result_df) and
returns either None (passed) or a CheckFailure with a one-line, generic feedback
string the agent can act on. Checks must NOT name specific tables, columns, or
DBs — they encode patterns, not instances.

Checks compose: `run_all_checks(...)` returns the first failure or None. The
harness uses that to either accept the save or feed the feedback back to the
agent for one corrective turn.

Toggling: each check has an `enabled` flag in CHECK_REGISTRY so we can A/B test.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd


@dataclass
class CheckFailure:
    """One-line, generic feedback an agent can act on."""

    check_name: str
    feedback: str  # phrased as an instruction, not a description


CheckFn = Callable[[str, str, pd.DataFrame], CheckFailure | None]


# ── Individual checks ──────────────────────────────────────────────────────────

def check_non_empty(question: str, sql: str, df: pd.DataFrame) -> CheckFailure | None:
    """Empty result is almost never the right answer unless the question explicitly allows it."""
    if len(df) == 0:
        # questions that legitimately expect 0 rows are rare and usually phrased
        # like "find any X where ..." with explicit "if any" wording
        q_lower = question.lower()
        allows_empty = any(phrase in q_lower for phrase in ("if any", "any X where", "find rows where"))
        if not allows_empty:
            return CheckFailure(
                "non_empty",
                "Result has 0 rows. Re-check filters — drop them one by one to find which one eliminated all rows.",
            )
    return None


def check_no_all_null_columns(question: str, sql: str, df: pd.DataFrame) -> CheckFailure | None:
    """A column that is entirely NULL almost always indicates a wrong JOIN."""
    if df.empty:
        return None
    for col in df.columns:
        if df[col].isna().all() or (df[col].astype(str) == "").all():
            return CheckFailure(
                "no_all_null_columns",
                f"Column '{col}' is entirely null/empty — your JOIN is dropping rows or matching the wrong key. Inspect that column's source table and JOIN condition.",
            )
    return None


def check_id_with_name(question: str, sql: str, df: pd.DataFrame) -> CheckFailure | None:
    """If the result has an ID-shaped column for an entity, a name-shaped column should accompany it.

    Pattern (schema-agnostic):
    - any column ending in _id, Id, ID, _key, Key, _code, Code is "ID-shaped"
    - any column containing 'name', 'title', 'label' is "name-shaped"
    - if there's an ID column and the question asks for "each X" / "list X" / "top X",
      we expect a corresponding name column to exist too
    """
    if df.empty:
        return None
    q_lower = question.lower()
    asks_for_each = any(phrase in q_lower for phrase in ("each ", "list ", "top ", "for every ", "per ", "by each "))
    if not asks_for_each:
        return None

    cols = [c.lower() for c in df.columns]
    has_id_col = any(
        c.endswith("_id") or c.endswith("id") or c.endswith("_key") or c.endswith("key") or c.endswith("_code")
        for c in cols
    )
    has_name_col = any(("name" in c) or ("title" in c) or ("label" in c) for c in cols)

    if has_id_col and not has_name_col:
        return CheckFailure(
            "id_with_name",
            "Result has an ID column but no name/title/label column. When the question asks for entities ('each X', 'top X'), include BOTH the ID and a descriptive name column.",
        )
    return None


def check_top_n_row_count(question: str, sql: str, df: pd.DataFrame) -> CheckFailure | None:
    """If question says 'top N', row count should be ≤ N (allowing ties)."""
    import re

    q = question.lower()
    m = re.search(r"top\s+(\d+)", q)
    if not m:
        return None
    n = int(m.group(1))
    # Allow up to 2x N for tie-breaking, but anything well beyond is wrong
    if len(df) > n * 2:
        return CheckFailure(
            "top_n_row_count",
            f"Question asks for top {n} but result has {len(df)} rows. Add LIMIT {n} or QUALIFY ROW_NUMBER() <= {n} (or use DENSE_RANK for ties).",
        )
    return None


def check_metric_column_present(question: str, sql: str, df: pd.DataFrame) -> CheckFailure | None:
    """If the question asks for an aggregate (average/share/count/rate/grade), a numeric metric column should exist.

    Heuristic: detect aggregate keywords in the question; verify at least one numeric
    column exists in the result. Generic — does not check specific column names.
    """
    if df.empty:
        return None
    q = question.lower()
    aggregate_phrases = (
        "average ", "avg ", "mean ", "median ",
        "share of", "share in", "percentage of", "percent of", "ratio of",
        "rate of", "frequency of",
        "total ", "sum of",
        "count of", "number of",
        "score", "grade", "rating",
    )
    if not any(p in q for p in aggregate_phrases):
        return None

    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    if not numeric_cols:
        return CheckFailure(
            "metric_column_present",
            "Question asks for a numeric metric (average/share/count/rate/grade) but result has no numeric column. Add an explicit column for the computed metric.",
        )
    return None


def check_groupby_dedup(question: str, sql: str, df: pd.DataFrame) -> CheckFailure | None:
    """If question implies 'one row per X' but rows duplicate on the leading text column, fan-out occurred.

    Generic heuristic: if the first column is non-numeric and has duplicates, the
    grain is wrong (fan-out from a JOIN, missing GROUP BY, or missing DISTINCT).
    """
    if df.empty or len(df.columns) == 0:
        return None
    q = question.lower()
    implies_unique = any(p in q for p in ("for each ", "per ", "by each ", "list each "))
    if not implies_unique:
        return None
    first_col = df.columns[0]
    if pd.api.types.is_numeric_dtype(df[first_col]):
        return None
    n_unique = df[first_col].nunique(dropna=False)
    if n_unique < len(df):
        return CheckFailure(
            "groupby_dedup",
            f"Question asks for one row per entity but column '{first_col}' has {n_unique} unique values across {len(df)} rows — fan-out from a JOIN or missing GROUP BY/DISTINCT.",
        )
    return None


# ── Registry & runner ──────────────────────────────────────────────────────────

CHECK_REGISTRY: dict[str, tuple[CheckFn, bool]] = {
    "non_empty": (check_non_empty, True),
    "no_all_null_columns": (check_no_all_null_columns, True),
    "id_with_name": (check_id_with_name, True),
    "top_n_row_count": (check_top_n_row_count, True),
    "metric_column_present": (check_metric_column_present, True),
    "groupby_dedup": (check_groupby_dedup, True),
}


def run_all_checks(
    question: str,
    sql: str,
    df: pd.DataFrame,
    enabled_only: bool = True,
) -> list[CheckFailure]:
    """Run every (enabled) check. Returns the list of failures, in registry order."""
    failures: list[CheckFailure] = []
    for name, (fn, enabled) in CHECK_REGISTRY.items():
        if enabled_only and not enabled:
            continue
        try:
            result = fn(question, sql, df)
            if result is not None:
                failures.append(result)
        except Exception as e:
            # A check that crashes must not block the harness — log and continue.
            failures.append(CheckFailure(name, f"[check crashed: {e}]"))
    return failures
