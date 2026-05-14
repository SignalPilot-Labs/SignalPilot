"""Notebook file I/O helpers, analysis logic, and comparison utilities.

Shared between MCP tools and API router. Handles reading, writing, and
deleting .ipynb files from the notebooks directory, plus content analysis
and diff computation.
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

from gateway.models.notebooks import (
    AnalysisComparison,
    CellDiff,
    ComparisonSummary,
    NotebookComparison,
    NotebookInfo,
)

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


def _load_notebook_file_raw(notebook_id: str) -> str | None:
    """Read raw notebook file content as string; returns None if missing."""
    path = _safe_notebook_path(notebook_id)
    if not path.exists():
        return None
    try:
        return path.read_text("utf-8")
    except OSError:
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

    result = {
        "cell_counts": cell_counts,
        "imports": imports,
        "execution_order_gaps": execution_order_gaps,
        "error_cells": error_cells,
        "output_summary": output_summary,
        "total_code_lines": total_code_lines,
        "functions_defined": functions_defined,
        "kernel_info": kernel_info,
    }
    result["quality_score"] = _compute_quality_score(result)
    return result


def _compute_quality_score(analysis: dict) -> int:
    """Compute a 0-100 quality score from analysis data.

    Pure function — no side effects, no external dependencies.
    Score starts at 100 and deductions are applied for quality issues.
    """
    score = 100

    cell_counts: dict[str, int] = analysis.get("cell_counts", {})
    total_cells = sum(cell_counts.values())
    error_cells: list = analysis.get("error_cells", [])
    error_count = len(error_cells)

    # Error penalty: up to -40 points (20% error rate = -40)
    if total_cells > 0:
        error_rate = error_count / total_cells
        score -= min(40, int(error_rate * 200))

    # Documentation penalty: up to -20 points (0% markdown = -20)
    markdown_count = cell_counts.get("markdown", 0)
    if total_cells > 0:
        doc_ratio = markdown_count / total_cells
        if doc_ratio < 0.2:
            score -= int((0.2 - doc_ratio) * 100)

    # Code organisation penalty: up to -20 points
    code_lines: int = analysis.get("total_code_lines", 0)
    functions_defined: list = analysis.get("functions_defined", [])
    functions_count = len(functions_defined)
    if code_lines > 20 and functions_count == 0:
        score -= 20
    elif code_lines > 50:
        ratio = functions_count / (code_lines / 20)
        if ratio < 0.3:
            score -= 10

    # Cell balance penalty: up to -10 points
    if total_cells < 2:
        score -= 10
    elif total_cells > 100:
        score -= 10

    return max(0, min(100, score))


_MAX_REPORT_CELLS = 50


def _build_report_data(
    analysis_json: dict | None,
    nb_content: dict,
) -> dict:
    """Assemble raw report data from notebook metadata, analysis, and file content.

    Returns a dict with keys: cell_details, outputs_summary, metadata.
    Both the API endpoint (wraps in NotebookReport) and MCP tool (formats as text) use this.
    """
    cells = nb_content.get("cells", [])
    nb_metadata = nb_content.get("metadata", {})

    cell_details: list[dict] = []
    total_outputs = 0
    by_type: dict[str, int] = {}

    for idx, cell in enumerate(cells[:_MAX_REPORT_CELLS]):
        cell_type = cell.get("cell_type", "unknown")
        source = _cell_source(cell)
        source_line_count = len(source.splitlines())
        outputs = cell.get("outputs", [])
        has_output = bool(outputs)

        for output in outputs:
            output_type = output.get("output_type", "unknown")
            by_type[output_type] = by_type.get(output_type, 0) + 1
            total_outputs += 1

        exec_count = cell.get("execution_count")
        cell_details.append({
            "index": idx,
            "cell_type": cell_type,
            "source_line_count": source_line_count,
            "has_output": has_output,
            "execution_count": exec_count,
        })

    # Count outputs from cells beyond the preview limit too
    for cell in cells[_MAX_REPORT_CELLS:]:
        for output in cell.get("outputs", []):
            output_type = output.get("output_type", "unknown")
            by_type[output_type] = by_type.get(output_type, 0) + 1
            total_outputs += 1

    kernelspec = nb_metadata.get("kernelspec")
    kernel_info: dict | None = dict(kernelspec) if kernelspec else None

    return {
        "cell_details": cell_details,
        "outputs_summary": {
            "total_outputs": total_outputs,
            "by_type": by_type,
        },
        "metadata": {
            "nbformat": nb_content.get("nbformat"),
            "nbformat_minor": nb_content.get("nbformat_minor"),
            "kernel_info": kernel_info,
        },
    }


def _now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(UTC).isoformat()


def _build_analysis_comparison(
    left_analysis: dict,
    right_analysis: dict,
) -> AnalysisComparison:
    """Compute the diff between two analysis result dicts."""
    left_imports: list[str] = left_analysis.get("imports", [])
    right_imports: list[str] = right_analysis.get("imports", [])
    left_functions: list[str] = left_analysis.get("functions_defined", [])
    right_functions: list[str] = right_analysis.get("functions_defined", [])

    left_import_set = set(left_imports)
    right_import_set = set(right_imports)
    left_func_set = set(left_functions)
    right_func_set = set(right_functions)

    return AnalysisComparison(
        left_imports=left_imports,
        right_imports=right_imports,
        added_imports=sorted(right_import_set - left_import_set),
        removed_imports=sorted(left_import_set - right_import_set),
        left_functions=left_functions,
        right_functions=right_functions,
        added_functions=sorted(right_func_set - left_func_set),
        removed_functions=sorted(left_func_set - right_func_set),
        left_error_cells=left_analysis.get("error_cells", []),
        right_error_cells=right_analysis.get("error_cells", []),
        left_code_lines=left_analysis.get("total_code_lines", 0),
        right_code_lines=right_analysis.get("total_code_lines", 0),
    )


def _compare_cells(left_nb: dict, right_nb: dict) -> list[CellDiff]:
    """Compute per-cell diffs between two notebooks by index position."""
    left_cells: list[dict] = left_nb.get("cells", [])
    right_cells: list[dict] = right_nb.get("cells", [])
    total = max(len(left_cells), len(right_cells))
    diffs: list[CellDiff] = []

    for idx in range(total):
        has_left = idx < len(left_cells)
        has_right = idx < len(right_cells)

        if has_left and not has_right:
            cell = left_cells[idx]
            src = _cell_source(cell)
            diffs.append(CellDiff(
                index=idx,
                status="removed",
                left_type=cell.get("cell_type"),
                right_type=None,
                left_source_lines=len(src.splitlines()),
                right_source_lines=None,
            ))
        elif has_right and not has_left:
            cell = right_cells[idx]
            src = _cell_source(cell)
            diffs.append(CellDiff(
                index=idx,
                status="added",
                left_type=None,
                right_type=cell.get("cell_type"),
                left_source_lines=None,
                right_source_lines=len(src.splitlines()),
            ))
        else:
            lc = left_cells[idx]
            rc = right_cells[idx]
            left_src = _cell_source(lc)
            right_src = _cell_source(rc)
            left_type: str | None = lc.get("cell_type")
            right_type: str | None = rc.get("cell_type")
            is_same = left_src == right_src and left_type == right_type
            diffs.append(CellDiff(
                index=idx,
                status="unchanged" if is_same else "modified",
                left_type=left_type,
                right_type=right_type,
                left_source_lines=len(left_src.splitlines()),
                right_source_lines=len(right_src.splitlines()),
            ))

    return diffs


def build_notebook_comparison(
    left_meta: NotebookInfo,
    right_meta: NotebookInfo,
    left_nb: dict,
    right_nb: dict,
    left_analysis: dict | None,
    right_analysis: dict | None,
) -> NotebookComparison:
    """Compute a full diff between two notebooks.

    Pure function — no DB access. Compares cells by index position and
    computes analysis diffs when both notebooks have been analyzed.

    Args:
        left_meta: Persisted metadata for the left notebook.
        right_meta: Persisted metadata for the right notebook.
        left_nb: Parsed notebook JSON dict for the left notebook.
        right_nb: Parsed notebook JSON dict for the right notebook.
        left_analysis: Analysis result dict for the left notebook, or None.
        right_analysis: Analysis result dict for the right notebook, or None.

    Returns:
        NotebookComparison with cell_diffs, optional analysis diff, and summary counts.
    """
    cell_diffs = _compare_cells(left_nb, right_nb)

    analysis: AnalysisComparison | None = None
    if left_analysis is not None and right_analysis is not None:
        analysis = _build_analysis_comparison(left_analysis, right_analysis)

    summary = ComparisonSummary(
        added=sum(1 for d in cell_diffs if d.status == "added"),
        removed=sum(1 for d in cell_diffs if d.status == "removed"),
        modified=sum(1 for d in cell_diffs if d.status == "modified"),
        unchanged=sum(1 for d in cell_diffs if d.status == "unchanged"),
    )

    return NotebookComparison(
        left_notebook=left_meta,
        right_notebook=right_meta,
        analysis=analysis,
        cell_diffs=cell_diffs,
        summary=summary,
    )
