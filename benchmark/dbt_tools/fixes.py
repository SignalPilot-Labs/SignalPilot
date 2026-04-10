"""Deterministic SQL rewrites applied before the final dbt run."""

from __future__ import annotations

import re
from pathlib import Path

from ..core.logging import log, log_separator
from .scanner import SKIP_DIRS

EXCLUSION_PHRASES = (
    "only ",
    "with orders",
    "with at least",
    "who have",
    "who has",
    "that have",
    "exclude",
    "excluding",
    "due to ",
    "must have",
    "require",
    "filter to",
    "restrict to",
    "limited to",
)


def rewrite_inner_joins(work_dir: Path, task_instruction: str) -> list[str]:
    """Rewrite INNER JOIN to LEFT JOIN in all non-ephemeral SQL model files.

    Returns list of relative paths (relative to work_dir) of files modified.
    Skips rewriting entirely if the task instruction contains explicit exclusion language.
    """
    inner_join_pattern = re.compile(r'\bINNER\s+JOIN\b', re.IGNORECASE)

    instruction_lower = task_instruction.lower()
    if any(phrase in instruction_lower for phrase in EXCLUSION_PHRASES):
        log("INNER JOIN rewrite skipped — task has explicit exclusion language")
        return []

    modified: list[str] = []
    models_dir = work_dir / "models"
    if not models_dir.is_dir():
        return modified
    for sql_file in models_dir.rglob("*.sql"):
        if any(skip in str(sql_file) for skip in SKIP_DIRS):
            continue
        try:
            content = sql_file.read_text()
            if content.strip().startswith("{{ config(materialized='ephemeral') }}"):
                continue
            matches = inner_join_pattern.findall(content)
            if not matches:
                continue
            new_content = inner_join_pattern.sub('LEFT JOIN', content)
            sql_file.write_text(new_content)
            rel_path = str(sql_file.relative_to(work_dir))
            modified.append(rel_path)
            log(f"[INFO] JOIN-FIX: {rel_path} — replaced {len(matches)} INNER JOIN(s) with LEFT JOIN")
        except Exception as exc:
            rel_path = str(sql_file.relative_to(work_dir))
            log(f"Warning: JOIN-FIX skipped {rel_path}: {exc}", "WARN")
    return modified


def strip_speculative_filters(work_dir: Path, task_instruction: str) -> list[str]:
    """Remove WHERE/HAVING equality filters on string literals not in the task instruction.

    Only removes = 'string_literal' equality conditions. Never touches numeric equality,
    NULL checks, date strings, IN lists, LIKE clauses, or != / <> operators.
    """
    filter_pattern = re.compile(
        r'(?P<keyword>WHERE|AND|OR|HAVING)\s+(?P<col>\w+)\s*=\s*\'(?P<literal>[^\']+)\'',
        re.IGNORECASE | re.MULTILINE,
    )
    date_pattern = re.compile(r'\d{4}-\d{2}-\d{2}')
    empty_where_pattern = re.compile(
        r'\b(WHERE|HAVING)\s*(?=GROUP\s+BY|ORDER\s+BY|LIMIT|UNION|$)',
        re.IGNORECASE | re.MULTILINE,
    )

    instruction_lower = task_instruction.lower()
    removed_items: list[str] = []

    line_comment_pattern = re.compile(r'--.*$', re.MULTILINE)
    block_comment_pattern = re.compile(r'/\*.*?\*/', re.DOTALL)
    dangling_and_or = re.compile(r'\b(WHERE|HAVING)\s+(AND|OR)\b', re.IGNORECASE)

    models_dir = work_dir / "models"
    if not models_dir.is_dir():
        return removed_items

    for sql_file in models_dir.rglob("*.sql"):
        if any(skip in str(sql_file) for skip in SKIP_DIRS):
            continue
        try:
            content = sql_file.read_text()
            if content.strip().startswith("{{ config(materialized='ephemeral') }}"):
                continue

            file_modified = False
            working_content = content
            rel_path = str(sql_file.relative_to(work_dir))

            comment_positions: set[int] = set()
            for cm in line_comment_pattern.finditer(content):
                comment_positions.update(range(cm.start(), cm.end()))
            for cm in block_comment_pattern.finditer(content):
                comment_positions.update(range(cm.start(), cm.end()))

            speculative: list[re.Match[str]] = []
            for m in filter_pattern.finditer(working_content):
                if m.start() in comment_positions:
                    continue
                literal = m.group('literal')
                if date_pattern.search(literal):
                    continue
                if literal.lower() in instruction_lower:
                    continue
                speculative.append(m)

            if not speculative:
                continue

            for m in reversed(speculative):
                keyword = m.group('keyword').upper()
                col = m.group('col')
                literal = m.group('literal')
                full_match = m.group(0)

                if keyword in ('AND', 'OR', 'HAVING'):
                    replacement = ''
                elif keyword == 'WHERE':
                    replacement = 'WHERE '
                else:
                    replacement = ''

                new_content = working_content[:m.start()] + replacement + working_content[m.end():]
                if new_content.count('(') != working_content.count('(') or new_content.count(')') != working_content.count(')'):
                    log(f"Warning: FILTER-FIX skipped {rel_path} — paren imbalance after removing {full_match!r}", "WARN")
                    continue

                working_content = new_content
                file_modified = True
                condition_str = f"{keyword} {col} = '{literal}'"
                removed_items.append(f"({rel_path}, {condition_str})")
                log(f"[INFO] FILTER-FIX: {rel_path} — removed speculative filter: {condition_str}")

            if not file_modified:
                continue

            working_content = dangling_and_or.sub(r'\1', working_content)
            working_content = empty_where_pattern.sub('', working_content)

            if working_content.count('(') != working_content.count(')'):
                log(f"Warning: FILTER-FIX aborted for {rel_path} — result has unbalanced parens", "WARN")
                continue

            sql_file.write_text(working_content)
        except Exception as exc:
            rel_path = str(sql_file.relative_to(work_dir))
            log(f"Warning: FILTER-FIX skipped {rel_path}: {exc}", "WARN")

    return removed_items


def run_post_agent_sql_fixes(
    work_dir: Path,
    task_instruction: str,
    eval_critical_models: set[str],
) -> None:
    """Run deterministic SQL rewrites on generated model files before the final dbt run."""
    log_separator("Post-agent SQL fixes (deterministic)")
    join_fixes = rewrite_inner_joins(work_dir, task_instruction)
    # Filter stripping disabled — too many false positives on legitimate staging filters.
    # The JOIN rewriter alone covers the highest-ROI pattern.
    if join_fixes:
        log(f"SQL fixes applied: {len(join_fixes)} join rewrite(s)")
    else:
        log("No post-agent SQL fixes needed")
