"""Notebook file I/O helpers and analysis logic.

Shared between MCP tools and API router. Handles reading, writing, and
deleting .ipynb files from the notebooks directory, plus content analysis.
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

_IMPORT_RE = re.compile(r"^\s*(?:import\s+([\w.]+)|from\s+([\w.]+)\s+import)", re.MULTILINE)
_FUNC_RE = re.compile(r"^\s*def\s+(\w+)\s*\(", re.MULTILINE)


def _notebooks_dir() -> Path:
    d = Path(os.environ.get("SP_NOTEBOOKS_DIR", "/tmp/sp-workspaces/notebooks"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_notebook_path(notebook_id: str) -> Path:
    """Resolve notebook path and verify it stays within the notebooks directory."""
    if not _UUID_RE.match(notebook_id):
        raise ValueError(f"Invalid notebook ID: {notebook_id}")
    base = _notebooks_dir().resolve()
    path = (base / f"{notebook_id}.ipynb").resolve()
    if not path.is_relative_to(base):
        raise ValueError(f"Invalid notebook ID: {notebook_id}")
    return path


def _save_notebook_file(notebook_id: str, content: str) -> None:
    """Atomically write notebook content to {notebook_id}.ipynb."""
    path = _safe_notebook_path(notebook_id)
    tmp = path.with_suffix(".ipynb.tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.rename(path)


def _load_notebook_file(notebook_id: str) -> dict | None:
    """Read and parse notebook JSON; returns None if missing or invalid."""
    path = _safe_notebook_path(notebook_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _delete_notebook_file(notebook_id: str) -> None:
    """Delete notebook file, ignoring missing files."""
    path = _safe_notebook_path(notebook_id)
    path.unlink(missing_ok=True)


def _parse_notebook(nb: dict) -> dict:
    """Extract structural metadata from a parsed nbformat notebook dict."""
    cells = nb.get("cells", [])
    cell_count = len(cells)
    code_cell_count = sum(1 for c in cells if c.get("cell_type") == "code")
    markdown_cell_count = sum(1 for c in cells if c.get("cell_type") == "markdown")
    kernelspec = nb.get("metadata", {}).get("kernelspec", {})
    kernel_name: str | None = kernelspec.get("name") if kernelspec else None
    return {
        "cell_count": cell_count,
        "code_cell_count": code_cell_count,
        "markdown_cell_count": markdown_cell_count,
        "kernel_name": kernel_name,
    }


def _cell_source(cell: dict) -> str:
    """Return cell source as a single string regardless of list/str format."""
    src = cell.get("source", "")
    if isinstance(src, list):
        return "".join(src)
    return src


def _analyze_notebook_content(nb: dict) -> dict:
    """Compute full analysis of a parsed notebook dict.

    Returns a dict matching NotebookAnalysis fields (without notebook_id/analyzed_at).
    """
    cells = nb.get("cells", [])

    cell_counts: dict[str, int] = {}
    imports: list[str] = []
    execution_order_gaps: list[int] = []
    error_cells: list[int] = []
    output_summary: dict[str, int] = {}
    total_code_lines = 0
    functions_defined: list[str] = []
    seen_imports: set[str] = set()
    seen_functions: set[str] = set()
    seen_error_indices: set[int] = set()
    execution_counts: list[int] = []

    for idx, cell in enumerate(cells):
        cell_type = cell.get("cell_type", "unknown")
        cell_counts[cell_type] = cell_counts.get(cell_type, 0) + 1
        source = _cell_source(cell)

        if cell_type == "code":
            lines = source.splitlines()
            total_code_lines += len(lines)

            for match in _IMPORT_RE.finditer(source):
                module = match.group(1) or match.group(2)
                if module and module not in seen_imports:
                    seen_imports.add(module)
                    imports.append(module)

            for match in _FUNC_RE.finditer(source):
                func_name = match.group(1)
                if func_name not in seen_functions:
                    seen_functions.add(func_name)
                    functions_defined.append(func_name)

            exec_count = cell.get("execution_count")
            if exec_count is not None:
                execution_counts.append(exec_count)

            for output in cell.get("outputs", []):
                output_type = output.get("output_type", "unknown")
                output_summary[output_type] = output_summary.get(output_type, 0) + 1
                if output_type == "error" and idx not in seen_error_indices:
                    seen_error_indices.add(idx)
                    error_cells.append(idx)

    if execution_counts:
        sorted_counts = sorted(execution_counts)
        for i in range(len(sorted_counts) - 1):
            current = sorted_counts[i]
            nxt = sorted_counts[i + 1]
            if nxt - current > 1:
                execution_order_gaps.append(current + 1)

    kernelspec = nb.get("metadata", {}).get("kernelspec")
    kernel_info: dict | None = dict(kernelspec) if kernelspec else None

    return {
        "cell_counts": cell_counts,
        "imports": imports,
        "execution_order_gaps": execution_order_gaps,
        "error_cells": error_cells,
        "output_summary": output_summary,
        "total_code_lines": total_code_lines,
        "functions_defined": functions_defined,
        "kernel_info": kernel_info,
    }


def _now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(UTC).isoformat()
