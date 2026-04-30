"""
Non-determinism auto-fixer for dbt projects.

Finds ROW_NUMBER/RANK/DENSE_RANK OVER(...) clauses whose ORDER BY may not be unique,
and appends a tiebreaker column (first *_id column found in referenced tables).

Generates local override files for package models and edits project models in-place.
Returns a list of NondeterminismFix objects rather than writing files directly, so
the caller (MCP tool) controls I/O.

Strategy:
- For each nd_warning, read the SQL file and locate every window function OVER clause.
- Use a balanced-paren parser to extract the full OVER(...) body (handles multi-line
  and nested parens like COALESCE(a, b) in PARTITION BY).
- Extract ORDER BY columns from the OVER body.
- Query information_schema.columns for all tables referenced via {{ ref() }} and
  {{ source() }} in the model. Pick the first column ending in _id that is not
  already in ORDER BY. If none found, skip with a warning.
- Rewrite the OVER clause to append the tiebreaker, then return the modified content.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# ── Constants ────────────────────────────────────────────────────────────────

CONFIG_BLOCK = "{{ config(materialized='table') }}\n"

# Matches the opening of a window function call: ROW_NUMBER() OVER (
# Capture group 1 = function name; leaves the cursor just after the opening paren.
_RE_ND_WINDOW_START = re.compile(
    r"(ROW_NUMBER|RANK|DENSE_RANK)\s*\(\s*\)\s*OVER\s*\(",
    re.IGNORECASE,
)

# Matches jinja ref/source patterns (same as scanner.py)
_RE_REF = re.compile(r"""\{\{\s*ref\s*\(\s*['"]([^'"]+)['"]\s*\)\s*\}\}""")
_RE_SOURCE = re.compile(r"""\{\{\s*source\s*\(\s*['"]([^'"]+)['"]\s*,\s*['"]([^'"]+)['"]\s*\)\s*\}\}""")

# Extracts ORDER BY columns: everything after ORDER BY up to end of OVER body.
# We apply this to the already-extracted OVER body string.
_RE_ORDER_BY = re.compile(r"\bORDER\s+BY\s+(.+)$", re.IGNORECASE | re.DOTALL)

# Columns to skip (NULL placeholder used by some models)
_SKIP_ORDER_BY_VALUES = frozenset({"null", "1", "true", "false"})


# ── Data types ───────────────────────────────────────────────────────────────


@dataclass
class NondeterminismFix:
    """Describes a single file fix — either a new override or an in-place edit."""

    original_path: str  # relative path to the hazard source
    output_path: Path  # absolute path where the file should be written
    content: str  # full SQL with tiebreakers applied
    is_package: bool  # True if this is a new package override
    fixes_applied: list[str] = field(default_factory=list)  # e.g. ["int_visits ORDER BY + encounter_id"]
    skipped_patterns: list[str] = field(default_factory=list)  # unfixable patterns
    already_overridden: bool = False  # True if override already existed — skip write


# ── Balanced-paren extractor ─────────────────────────────────────────────────


def _extract_over_body(sql: str, open_paren_pos: int) -> tuple[str, int] | None:
    """Extract the content of an OVER(...) clause using balanced-paren counting.

    Args:
        sql: Full SQL string.
        open_paren_pos: Index of the '(' that opens the OVER clause.

    Returns:
        (body, end_pos) where body is the text inside the parens (exclusive),
        and end_pos is the index of the matching ')'. Returns None if parens
        are unbalanced (truncated file).
    """
    depth = 1
    pos = open_paren_pos + 1
    while pos < len(sql) and depth > 0:
        ch = sql[pos]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        pos += 1

    if depth != 0:
        return None

    body = sql[open_paren_pos + 1 : pos - 1]
    return body, pos - 1


# ── ORDER BY column extraction ───────────────────────────────────────────────


def _extract_order_by_columns(over_body: str) -> list[str]:
    """Extract column names from the ORDER BY clause inside an OVER body.

    Returns a list of simple column names (lowercased, stripped of ASC/DESC/NULLS).
    Only the leaf name is returned (not table.column qualified forms).
    """
    match = _RE_ORDER_BY.search(over_body)
    if not match:
        return []

    raw = match.group(1)
    # Remove nested parens (e.g. function calls like COALESCE(a,b) ASC)
    # by stripping everything inside parens.
    no_parens = re.sub(r"\([^)]*\)", "", raw)
    # Split on commas.
    parts = no_parens.split(",")
    cols: list[str] = []
    for part in parts:
        tokens = part.strip().split()
        if not tokens:
            continue
        # First token is the column/expression; ignore ASC/DESC/NULLS FIRST/LAST.
        candidate = tokens[0].lower().rstrip(";")
        # Qualified names: take the last part after dot.
        if "." in candidate:
            candidate = candidate.split(".")[-1]
        # Skip non-column tokens.
        if candidate and candidate not in _SKIP_ORDER_BY_VALUES:
            cols.append(candidate)
    return cols


# ── Tiebreaker selection ─────────────────────────────────────────────────────


def _pick_tiebreaker(
    existing_order_by_cols: list[str],
    candidate_columns: list[str],
) -> str | None:
    """Pick the first candidate column ending in _id not already in ORDER BY.

    Args:
        existing_order_by_cols: Lowercased column names already in ORDER BY.
        candidate_columns: Lowercased column names from referenced tables.

    Returns:
        Column name to use as tiebreaker, or None if nothing suitable found.
    """
    existing = frozenset(existing_order_by_cols)
    for col in candidate_columns:
        lower = col.lower()
        if lower in existing:
            continue
        if lower.endswith("_id") or lower == "id":
            return col
    return None


# ── SQL rewriter ─────────────────────────────────────────────────────────────


def _rewrite_over_clause(over_body: str, tiebreaker: str) -> str:
    """Append tiebreaker to the ORDER BY in an OVER body string.

    If the OVER body has no ORDER BY, add one. Returns the modified body.
    """
    ob_match = _RE_ORDER_BY.search(over_body)
    if ob_match:
        # Append tiebreaker after existing ORDER BY columns.
        insert_pos = ob_match.end()
        return over_body[:insert_pos].rstrip() + f", {tiebreaker}" + over_body[insert_pos:]
    # No ORDER BY — add one before the closing (which is already stripped from body).
    return over_body.rstrip() + f" ORDER BY {tiebreaker}"


def _apply_tiebreaker_to_sql(
    sql: str,
    tiebreaker: str,
    model_name: str,
) -> tuple[str, list[str], list[str]]:
    """Find all ND window patterns and append tiebreaker to their ORDER BY.

    Returns (modified_sql, fixes_applied, skipped_patterns).
    """
    fixes_applied: list[str] = []
    skipped: list[str] = []
    result = sql
    offset = 0

    for match in _RE_ND_WINDOW_START.finditer(sql):
        func_name = match.group(1).upper()
        # Position of '(' that opens OVER
        open_pos = match.end() - 1  # match ends just after '('

        # Adjust for offset shifts from prior replacements
        adjusted_open = open_pos + offset
        extracted = _extract_over_body(result, adjusted_open)
        if extracted is None:
            skipped.append(f"{model_name}: {func_name} — unbalanced parens, skipped")
            continue

        body, close_pos = extracted
        existing_cols = _extract_order_by_columns(body)

        if tiebreaker.lower() in (c.lower() for c in existing_cols):
            # Tiebreaker already present — skip.
            continue

        new_body = _rewrite_over_clause(body, tiebreaker)
        # Reconstruct: replace old body with new body
        before = result[: adjusted_open + 1]
        after = result[close_pos:]
        result = before + new_body + after

        # Update offset for subsequent matches (based on original sql positions)
        offset += len(new_body) - len(body)
        fixes_applied.append(f"{model_name}: {func_name}() ORDER BY + {tiebreaker}")

    return result, fixes_applied, skipped


# ── Public API ────────────────────────────────────────────────────────────────


def generate_nondeterminism_fixes(
    project_dir: Path,
    nd_warnings: list[dict],
    table_columns: dict[str, list[str]],
) -> list[NondeterminismFix]:
    """Generate NondeterminismFix objects for all nd_warnings.

    Args:
        project_dir: Absolute path to the dbt project root.
        nd_warnings: List of warning dicts from scanner (nondeterminism_warnings on ProjectMap).
                     Each dict has: file, model_name, pattern, package (bool), override_path (str).
        table_columns: Dict mapping table name (lowercase) -> list of column names.
                       Used to pick a tiebreaker column. Pass an empty dict if DB unavailable
                       (all patterns will be skipped with a warning).

    Returns:
        List of NondeterminismFix objects. Caller is responsible for writing files.
    """
    fixes: list[NondeterminismFix] = []

    for warning in nd_warnings:
        is_package = bool(warning.get("package"))
        model_name = warning.get("model_name", "")
        source_rel = warning.get("file", "")

        if is_package:
            source_path = project_dir / source_rel
            override_rel = warning.get("override_path", f"models/{model_name}.sql")
            output_path = project_dir / override_rel

            if output_path.exists():
                fixes.append(
                    NondeterminismFix(
                        original_path=source_rel,
                        output_path=output_path,
                        content="",
                        is_package=True,
                        already_overridden=True,
                    )
                )
                continue

            try:
                source_sql = source_path.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                fixes.append(
                    NondeterminismFix(
                        original_path=source_rel,
                        output_path=output_path,
                        content="",
                        is_package=True,
                        skipped_patterns=[f"{model_name}: cannot read source file: {e}"],
                    )
                )
                continue

            # Prepend config block for package overrides.
            sql_body = CONFIG_BLOCK + source_sql
            tiebreaker = _resolve_tiebreaker(sql_body, table_columns, model_name)
            if tiebreaker is None:
                fixes.append(
                    NondeterminismFix(
                        original_path=source_rel,
                        output_path=output_path,
                        content="",
                        is_package=True,
                        skipped_patterns=[f"{model_name}: no suitable tiebreaker column found (manual fix needed)"],
                    )
                )
                continue

            fixed_sql, applied, skipped = _apply_tiebreaker_to_sql(sql_body, tiebreaker, model_name)
            fixes.append(
                NondeterminismFix(
                    original_path=source_rel,
                    output_path=output_path,
                    content=fixed_sql,
                    is_package=True,
                    fixes_applied=applied,
                    skipped_patterns=skipped,
                )
            )

        else:
            source_path = project_dir / source_rel
            output_path = source_path  # in-place

            try:
                source_sql = source_path.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                fixes.append(
                    NondeterminismFix(
                        original_path=source_rel,
                        output_path=output_path,
                        content="",
                        is_package=False,
                        skipped_patterns=[f"{model_name}: cannot read file: {e}"],
                    )
                )
                continue

            tiebreaker = _resolve_tiebreaker(source_sql, table_columns, model_name)
            if tiebreaker is None:
                fixes.append(
                    NondeterminismFix(
                        original_path=source_rel,
                        output_path=output_path,
                        content="",
                        is_package=False,
                        skipped_patterns=[f"{model_name}: no suitable tiebreaker column found (manual fix needed)"],
                    )
                )
                continue

            fixed_sql, applied, skipped = _apply_tiebreaker_to_sql(source_sql, tiebreaker, model_name)
            fixes.append(
                NondeterminismFix(
                    original_path=source_rel,
                    output_path=output_path,
                    content=fixed_sql,
                    is_package=False,
                    fixes_applied=applied,
                    skipped_patterns=skipped,
                )
            )

    return fixes


def _resolve_tiebreaker(
    sql: str,
    table_columns: dict[str, list[str]],
    model_name: str,
) -> str | None:
    """Find a tiebreaker column by checking all referenced tables' columns.

    Returns the first *_id column that is available, or None if not found.
    """
    if not table_columns:
        return None

    # Gather all columns from all tables referenced in this SQL.
    candidates: list[str] = []
    for ref_name in _extract_ref_names(sql):
        cols = table_columns.get(ref_name.lower(), [])
        candidates.extend(cols)
    for _, table_name in _extract_source_tables(sql):
        cols = table_columns.get(table_name.lower(), [])
        candidates.extend(cols)

    # Deduplicate while preserving order.
    seen: set[str] = set()
    deduped: list[str] = []
    for col in candidates:
        if col.lower() not in seen:
            seen.add(col.lower())
            deduped.append(col)

    # Find first *_id column.
    return _pick_tiebreaker([], deduped)


def _extract_ref_names(sql: str) -> list[str]:
    """Extract model names from {{ ref('...') }} calls."""
    return [m.group(1) for m in _RE_REF.finditer(sql)]


def _extract_source_tables(sql: str) -> list[tuple[str, str]]:
    """Extract (schema, table) pairs from {{ source('...', '...') }} calls."""
    return [(m.group(1), m.group(2)) for m in _RE_SOURCE.finditer(sql)]


def build_table_columns_from_schema(
    schema: dict[str, dict],
) -> dict[str, list[str]]:
    """Convert a schema dict (from connector.get_schema()) to table->columns map.

    Args:
        schema: Dict keyed by table identifier, with each value having
                'name' (str) and 'columns' (list of dicts with 'name' key).

    Returns:
        Dict mapping lowercase table name to list of column names.
    """
    result: dict[str, list[str]] = {}
    for _key, table_data in schema.items():
        table_name = table_data.get("name", "").lower()
        if not table_name:
            continue
        cols = [col["name"] for col in table_data.get("columns", []) if col.get("name")]
        result[table_name] = cols
    return result
