"""Notebook quality MCP tool: list low-quality notebooks by score."""

from __future__ import annotations

from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _store_session
from gateway.mcp.server import mcp

_DEFAULT_MAX_SCORE = 50
_DEFAULT_LIMIT = 20


@audited_tool(mcp)
async def get_low_quality_notebooks(
    max_score: int = _DEFAULT_MAX_SCORE,
    limit: int = _DEFAULT_LIMIT,
) -> str:
    """
    List analyzed notebooks with a quality score at or below max_score.

    Quality score ranges from 0 (poor) to 100 (excellent). Penalises error
    cells, low documentation ratio, unorganised code, and extreme notebook sizes.

    Args:
        max_score: Upper bound on quality score (inclusive). Returns notebooks
            with quality_score <= max_score. Default 50 (low quality).
        limit: Maximum number of results to return. Default 20.

    Returns:
        Formatted text listing low-quality notebooks sorted by score ascending.
    """
    if max_score < 0 or max_score > 100:
        return "Error: max_score must be between 0 and 100."
    if limit < 1:
        return "Error: limit must be at least 1."

    async with _store_session() as store:
        items = await store.list_analyzed_notebooks()

    filtered = [item for item in items if item.quality_score <= max_score]
    filtered.sort(key=lambda item: item.quality_score)
    filtered = filtered[:limit]

    if not filtered:
        return f"No analyzed notebooks found with quality score <= {max_score}."

    lines = [f"Low-quality notebooks (score <= {max_score}), showing {len(filtered)} result(s):\n"]
    for item in filtered:
        lines.append(f"  - {item.name} (id: {item.notebook_id}, quality: {item.quality_score}/100)")
    return "\n".join(lines)


__all__ = ["get_low_quality_notebooks"]
