"""MCP notebooks tools package.

Split from ``mcp/tools/notebooks.py`` (601 LOC) in round 10.

Invariant: MCP ``@audited_tool`` decoration order — submodule imports must
run in the order that preserves tool registration. Decoration runs at import
time and registers onto the FastMCP singleton.

``# isort: skip_file`` is mandatory: reordering imports changes tool
registration order and alters ``mcp.list_tools()`` iteration.

Do not add ``__getattr__`` proxy or ``_common.py`` re-export helpers — see r9 lessons.
"""
# isort: skip_file

from __future__ import annotations

# Side-effect imports — order matches logical grouping (crud → analysis → batch → report → compare).
from gateway.mcp.tools.notebooks import crud as _crud  # noqa: F401
from gateway.mcp.tools.notebooks import analysis as _analysis  # noqa: F401
from gateway.mcp.tools.notebooks import batch as _batch  # noqa: F401
from gateway.mcp.tools.notebooks import report as _report  # noqa: F401
from gateway.mcp.tools.notebooks import compare as _compare  # noqa: F401

# Re-exports for gateway.mcp package re-exports and named imports.
from gateway.mcp.tools.notebooks.crud import (
    delete_notebook,
    get_notebook,
    list_notebooks,
    update_notebook_metadata,
    upload_notebook,
)
from gateway.mcp.tools.notebooks.analysis import (
    analyze_notebook,
    get_notebook_cell,
    get_notebook_file,
    get_notebook_outputs,
    get_notebooks_summary,
    reanalyze_notebook,
    search_notebooks,
)
from gateway.mcp.tools.notebooks.batch import (
    batch_analyze_notebooks,
    batch_delete_notebooks,
)
from gateway.mcp.tools.notebooks.report import get_notebook_report
from gateway.mcp.tools.notebooks.compare import compare_notebooks

__all__ = [
    "list_notebooks",
    "upload_notebook",
    "update_notebook_metadata",
    "get_notebook",
    "delete_notebook",
    "get_notebooks_summary",
    "analyze_notebook",
    "reanalyze_notebook",
    "get_notebook_outputs",
    "get_notebook_cell",
    "search_notebooks",
    "get_notebook_file",
    "batch_analyze_notebooks",
    "batch_delete_notebooks",
    "get_notebook_report",
    "compare_notebooks",
]
