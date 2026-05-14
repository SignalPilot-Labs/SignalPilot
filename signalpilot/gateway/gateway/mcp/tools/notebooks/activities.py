"""Notebook activity log MCP tool: retrieve lifecycle events for a notebook."""

from __future__ import annotations

import re

from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _store_session
from gateway.mcp.server import mcp
from gateway.store.notebook_activities import NOTEBOOK_ACTION_VALUES

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

_LIMIT_DEFAULT = 50


@audited_tool(mcp)
async def get_notebook_activities(notebook_id: str, limit: int = _LIMIT_DEFAULT, action: str = "") -> str:
    """
    Retrieve the activity log for a notebook, showing lifecycle events in reverse chronological order.

    Args:
        notebook_id: UUID of the notebook
        limit: Maximum number of events to return (default 50, max 100)
        action: Optional filter by action type. Allowed values: upload, analyze, delete,
                update, download, compare, export_report. Empty string returns all actions.

    Returns:
        Formatted text listing of activity events with timestamps, actions, and details.
    """
    if not _UUID_RE.match(notebook_id):
        return f"Error: Invalid notebook ID '{notebook_id}'."

    resolved_action: str | None = action.strip() or None
    if resolved_action is not None and resolved_action not in NOTEBOOK_ACTION_VALUES:
        return f"Error: Invalid action '{resolved_action}'. Allowed: {sorted(NOTEBOOK_ACTION_VALUES)}"

    async with _store_session() as store:
        meta = await store.get_notebook_meta(notebook_id)
        if not meta:
            return f"Error: Notebook '{notebook_id}' not found."
        activities = await store.get_notebook_activities(
            notebook_id,
            limit=limit,
            offset=0,
            action=resolved_action,
        )
        total = await store.count_notebook_activities(notebook_id, action=resolved_action)

    if not activities:
        return f"No activity recorded for notebook '{meta.name}'."

    lines: list[str] = [
        f"Activity log for: {meta.name}",
        f"Showing {len(activities)} of {total} event(s)",
        "",
    ]
    for event in activities:
        user_label = f" (user: {event.user_id})" if event.user_id else ""
        lines.append(f"  [{event.action}]{user_label} at {event.created_at}")
        if event.details:
            for key, val in event.details.items():
                lines.append(f"    {key}: {val}")

    return "\n".join(lines)


__all__ = ["get_notebook_activities"]
