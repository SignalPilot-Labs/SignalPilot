from __future__ import annotations

from signalpilot._server.ai.notebook_mcp import _is_markdown_only_cell


def test_markdown_only_cells_are_detected() -> None:
    assert _is_markdown_only_cell('sp.md("""# Title\\n\\nBody""")')
    assert _is_markdown_only_cell(
        """
import signalpilot as sp

sp.md(f\"\"\"## Executive Summary

Total: {total_revenue}
\"\"\")
"""
    )


def test_non_markdown_cells_are_not_detected_as_markdown_only() -> None:
    assert not _is_markdown_only_cell(
        """
rows = db.query("select 1")
sp.md(f"Loaded {len(rows)} rows")
"""
    )
    assert not _is_markdown_only_cell(
        """
import matplotlib.pyplot as plt
fig, ax = plt.subplots()
fig
"""
    )
