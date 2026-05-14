"""Notebook batch MCP tools: batch analyze and batch delete."""

from __future__ import annotations

import re
import time

from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _store_session
from gateway.mcp.server import mcp
from gateway.store.notebook_files import (
    _analyze_notebook_content,
    _delete_notebook_file,
    _load_notebook_file,
)

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

_MAX_BATCH_IDS = 50


def _parse_notebook_ids(notebook_ids_str: str) -> list[str] | str:
    """Parse comma-separated UUIDs. Returns list on success or error string on failure."""
    raw_ids = [nid.strip() for nid in notebook_ids_str.split(",") if nid.strip()]
    if not raw_ids:
        return "Error: No notebook IDs provided."
    if len(raw_ids) > _MAX_BATCH_IDS:
        return f"Error: Too many notebook IDs. Maximum is {_MAX_BATCH_IDS}, got {len(raw_ids)}."
    for nid in raw_ids:
        if not _UUID_RE.match(nid):
            return f"Error: Invalid notebook ID '{nid}'."
    return raw_ids


@audited_tool(mcp)
async def batch_analyze_notebooks(notebook_ids: str) -> str:
    """
    Analyze multiple notebooks in a single operation.

    Args:
        notebook_ids: Comma-separated list of notebook UUIDs (max 50)

    Returns:
        Summary of results: how many succeeded and failed, with per-notebook details.
    """
    parsed = _parse_notebook_ids(notebook_ids)
    if isinstance(parsed, str):
        return parsed

    results: list[str] = []
    succeeded = 0
    failed = 0

    for notebook_id in parsed:
        async with _store_session() as store:
            meta = await store.get_notebook_meta(notebook_id)
            if not meta:
                results.append(f"  {notebook_id}: FAILED (not found)")
                failed += 1
                continue

            nb = _load_notebook_file(notebook_id)
            if not nb:
                results.append(f"  {notebook_id}: FAILED (file not found)")
                failed += 1
                continue

            analysis = _analyze_notebook_content(nb)
            analyzed_at = time.time()
            analysis_json = {**analysis, "notebook_id": notebook_id, "analyzed_at": analyzed_at}
            await store.update_notebook_analysis(
                notebook_id=notebook_id,
                analysis_json=analysis_json,
                analyzed_at=analyzed_at,
            )
            results.append(f"  {notebook_id}: OK")
            succeeded += 1

    lines = [f"Batch analysis complete: {succeeded} succeeded, {failed} failed", *results]
    return "\n".join(lines)


@audited_tool(mcp)
async def batch_delete_notebooks(notebook_ids: str) -> str:
    """
    Delete multiple notebooks in a single operation.

    Args:
        notebook_ids: Comma-separated list of notebook UUIDs (max 50)

    Returns:
        Summary of results: how many were deleted and how many were not found.
    """
    parsed = _parse_notebook_ids(notebook_ids)
    if isinstance(parsed, str):
        return parsed

    async with _store_session() as store:
        db_results = await store.batch_delete_notebooks(parsed)

    deleted_count = 0
    not_found_count = 0
    result_lines: list[str] = []

    for notebook_id, success, error in db_results:
        if success:
            _delete_notebook_file(notebook_id)
            deleted_count += 1
            result_lines.append(f"  {notebook_id}: deleted")
        else:
            not_found_count += 1
            result_lines.append(f"  {notebook_id}: {error or 'not found'}")

    lines = [f"Batch delete complete: {deleted_count} deleted, {not_found_count} not found", *result_lines]
    return "\n".join(lines)


__all__ = [
    "batch_analyze_notebooks",
    "batch_delete_notebooks",
]
