"""
gateway.dbt — dbt project discovery and validation.

Public API:
    build_project_map(project_dir, focus="all", ...) -> str
        Yml-direct project discovery. Works on broken/incomplete projects.
        Returns a compact, LLM-optimized markdown view of the project.
        Cached by file-mtime fingerprint.

    validate_project(project_dir, ...) -> ValidationResult
        Wraps `dbt parse`. Surfaces compilation errors and orphan-patch
        warnings (yml-defined models with no .sql file).

    format_validation_result(result) -> str
        Render a ValidationResult as compact markdown for the agent.

This package is intentionally independent of dbt-core for discovery. The
discovery side parses yml files directly with PyYAML so it works in every
project state — including states where `dbt parse` itself fails. The
validation side calls `dbt parse` as a subprocess and parses its stderr.

File size budget: every module under 500 lines.
"""

from __future__ import annotations

from pathlib import Path

from .cache import cache_clear, cache_get, cache_put, fingerprint
from .formatters import render_project_map
from .inventory import scan_project
from .types import (
    ColumnSpec,
    MacroInfo,
    ModelInfo,
    ModelStatus,
    ProjectMap,
    SourceInfo,
    ValidationResult,
)
from .validator import format_validation_result, validate_project

__all__ = [
    "build_project_map",
    "render_project_map",
    "scan_project",
    "validate_project",
    "format_validation_result",
    "cache_clear",
    "ColumnSpec",
    "MacroInfo",
    "ModelInfo",
    "ModelStatus",
    "ProjectMap",
    "SourceInfo",
    "ValidationResult",
]


def build_project_map(
    project_dir: str | Path,
    focus: str = "all",
    max_models_per_section: int = 40,
    include_columns: bool = False,
    use_cache: bool = True,
) -> str:
    """Cached entrypoint for dbt project discovery.

    Checks the mtime-fingerprint cache first; on miss, runs the full scan
    and renders the result, then stores it. Cache is invalidated whenever
    any yml/sql/dbt_project file under the project changes.

    Args:
        project_dir: absolute path to the dbt project root
        focus: one of "all", "work_order", "missing", "stubs", "sources",
               "macros", or "model:<name>"
        max_models_per_section: per-section truncation threshold
        include_columns: include column lists inline for complete models
        use_cache: set False to bypass the cache (used by tests)

    Returns:
        markdown-formatted string
    """
    project_dir = Path(project_dir)
    if not project_dir.exists():
        return f"Error: project directory does not exist: {project_dir}"

    if not use_cache:
        return render_project_map(
            project_dir,
            focus=focus,
            max_models_per_section=max_models_per_section,
            include_columns=include_columns,
        )

    fp = fingerprint(project_dir)
    cache_key = (
        str(project_dir.resolve()),
        focus,
        max_models_per_section,
        include_columns,
        fp,
    )
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    rendered = render_project_map(
        project_dir,
        focus=focus,
        max_models_per_section=max_models_per_section,
        include_columns=include_columns,
    )
    cache_put(cache_key, rendered)
    return rendered
