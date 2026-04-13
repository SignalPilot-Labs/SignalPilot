"""
Date spine auto-fixer for dbt projects.

Generates local override files for package models with current_date hazards,
and edits project models in-place. Returns a list of DateSpineFix objects
rather than writing files directly, so the caller (MCP tool) controls I/O.

Comment-aware replacement strategy:
- Lines starting with -- (after stripping leading whitespace) are skipped.
- Block comments (/* ... */) are tracked with a simple state flag.
- Content inside these comment regions is not substituted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


# ── Constants ────────────────────────────────────────────────────────────────

CONFIG_BLOCK = "{{ config(materialized='table') }}\n"

# Patterns replaced by this fixer (matches _RE_DATE_HAZARD but also getdate/sysdate variants).
# Negative lookbehind (?<!\.) prevents matching inside Jinja method calls
# like dbt.current_timestamp() which would produce broken syntax.
_REPLACEMENT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?<!\.)\bcurrent_timestamp\b", re.IGNORECASE), "__DATE__"),
    (re.compile(r"(?<!\.)\bcurrent_date\b", re.IGNORECASE), "__DATE__"),
    (re.compile(r"(?<!\.)\bnow\(\)", re.IGNORECASE), "__DATE__"),
    (re.compile(r"(?<!\.)\bgetdate\(\)", re.IGNORECASE), "__DATE__"),
    (re.compile(r"(?<!\.)\bsysdate\b", re.IGNORECASE), "__DATE__"),
]

_RE_BLOCK_COMMENT_OPEN = re.compile(r"/\*")
_RE_BLOCK_COMMENT_CLOSE = re.compile(r"\*/")


# ── Data types ───────────────────────────────────────────────────────────────


@dataclass
class DateSpineFix:
    """Describes a single file fix — either a new override or an in-place edit."""

    original_path: str        # relative path to the hazard source
    output_path: Path         # absolute path where the file should be written
    content: str              # full SQL with replacements applied
    is_package: bool          # True if this is a new package override
    patterns_replaced: list[str] = field(default_factory=list)  # e.g. ["current_date", "now()"]
    already_overridden: bool = False  # True if override already existed — skip write


# ── Replacement logic ─────────────────────────────────────────────────────────


def _replace_date_patterns(sql: str, replacement_date: str) -> tuple[str, list[str]]:
    """Replace date hazard patterns in SQL, skipping comment regions.

    Uses a line-by-line strategy:
    - Lines starting with -- (after stripping) are passed through unchanged.
    - Block comment regions (/* ... */) are tracked with a simple open/close flag.
    - Content inside comment regions is never substituted.

    Returns (modified_sql, list_of_matched_pattern_names).
    """
    # Use max_date + 1 day to mimic current_date behavior.
    # current_date returns "today", which is always 1 day after the last complete
    # day in the source data. Date spine macros treat end_date as exclusive, so
    # without +1 the spine would be 1 row short.
    date_literal = f"('{replacement_date}'::date + INTERVAL '1 day')::date"
    found_patterns: set[str] = set()

    output_lines: list[str] = []
    in_block_comment = False

    for line in sql.splitlines(keepends=True):
        stripped = line.lstrip()

        # Detect transitions into/out of block comments.
        # We process the entire line even if mid-line transitions exist —
        # the simple state flag is good enough for real-world SQL.
        if in_block_comment:
            if _RE_BLOCK_COMMENT_CLOSE.search(line):
                in_block_comment = False
            output_lines.append(line)
            continue

        if _RE_BLOCK_COMMENT_OPEN.search(line):
            # A /* on this line opens a block comment. Check if it closes on the same line.
            after_open = _RE_BLOCK_COMMENT_OPEN.split(line, maxsplit=1)[1]
            if not _RE_BLOCK_COMMENT_CLOSE.search(after_open):
                # Block comment stays open past this line — skip substitution on this line.
                in_block_comment = True
                output_lines.append(line)
                continue
            # Block comment opens and closes on the same line — fall through to substitution.

        # Lines that are purely comments (-- style) are passed through unchanged.
        if stripped.startswith("--"):
            output_lines.append(line)
            continue

        # Apply substitutions.
        new_line = line
        for pattern, _ in _REPLACEMENT_PATTERNS:
            if pattern.search(new_line):
                # Extract human-readable name from regex pattern
                name = re.sub(r"\\b|\(\?<!\\\.\)", "", pattern.pattern).strip("()").lower()
                found_patterns.add(name)
                new_line = pattern.sub(date_literal, new_line)
        output_lines.append(new_line)

    return "".join(output_lines), sorted(found_patterns)


def _make_override_content(source_sql: str, replacement_date: str) -> tuple[str, list[str]]:
    """Create a package model override: prepend config block + replace date patterns."""
    replaced_sql, patterns = _replace_date_patterns(source_sql, replacement_date)
    return CONFIG_BLOCK + replaced_sql, patterns


def _make_inplace_content(source_sql: str, replacement_date: str) -> tuple[str, list[str]]:
    """Edit a project model in-place: replace date patterns, preserve config block if present."""
    return _replace_date_patterns(source_sql, replacement_date)


# ── Public API ────────────────────────────────────────────────────────────────


def generate_date_spine_fixes(
    project_dir: Path,
    hazards: list[dict],
    replacement_date: str,
) -> list[DateSpineFix]:
    """Generate DateSpineFix objects for all hazards.

    Args:
        project_dir: Absolute path to the dbt project root.
        hazards: List of hazard dicts from scanner (date_hazards field on ProjectMap).
                 Each dict has: file, pattern, model_name, package (bool), override_path (str).
        replacement_date: Date string like "2022-01-31" used as the literal replacement.

    Returns:
        List of DateSpineFix objects. Caller is responsible for writing files.
    """
    fixes: list[DateSpineFix] = []

    for hazard in hazards:
        is_package = bool(hazard.get("package"))
        model_name = hazard.get("model_name", "")
        source_rel = hazard.get("file", "")

        if is_package:
            source_path = project_dir / source_rel
            override_rel = hazard.get("override_path", f"models/{model_name}.sql")
            output_path = project_dir / override_rel

            # If override already exists, skip it.
            if output_path.exists():
                fixes.append(DateSpineFix(
                    original_path=source_rel,
                    output_path=output_path,
                    content="",
                    is_package=True,
                    already_overridden=True,
                ))
                continue

            try:
                source_sql = source_path.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                raise OSError(f"Cannot read package source {source_path}: {e}") from e

            content, patterns = _make_override_content(source_sql, replacement_date)
            fixes.append(DateSpineFix(
                original_path=source_rel,
                output_path=output_path,
                content=content,
                is_package=True,
                patterns_replaced=patterns,
            ))

        else:
            # Project model — edit in-place.
            source_path = project_dir / source_rel
            output_path = source_path  # same file

            try:
                source_sql = source_path.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                raise OSError(f"Cannot read project model {source_path}: {e}") from e

            content, patterns = _make_inplace_content(source_sql, replacement_date)
            fixes.append(DateSpineFix(
                original_path=source_rel,
                output_path=output_path,
                content=content,
                is_package=False,
                patterns_replaced=patterns,
            ))

    return fixes
