"""Reports MCP tool: manage_report — create or permanently delete HTML reports."""

from __future__ import annotations

import json
import os

from gateway.errors.mcp import sanitize_mcp_error
from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _require_mcp_admin_scope, _store_session
from gateway.mcp.server import mcp
from gateway.models.reports import ReportCreate

_DEFAULT_WEB_URL = "http://localhost:3200"


def _web_base_url() -> str:
    return (os.getenv("SP_WEB_URL") or os.getenv("SIGNALPILOT_WEB_URL") or _DEFAULT_WEB_URL).rstrip("/")


@audited_tool(mcp)
async def manage_report(
    action: str,
    title: str | None = None,
    html: str | None = None,
    report_id: str | None = None,
    scope_ref: str | None = None,
) -> str:
    """Create or permanently delete a rendered HTML report.

    action="create": requires title and html (a full, self-contained HTML
    document). Optionally pass scope_ref to group the report under a project.
    Returns the new report id and a shareable URL.

    action="delete": requires report_id. Deletion is permanent — there is no
    archive or undo.
    """
    try:
        act = (action or "").strip().lower()

        if act in ("create", "delete"):
            err = _require_mcp_admin_scope()
            if err:
                return err

        if act == "create":
            if not title or not html:
                return "Error: action 'create' requires both title and html"
            # Validate via DTO — raises pydantic.ValidationError on bad input
            payload = ReportCreate(title=title, html=html, scope_ref=scope_ref)
            async with _store_session() as store:
                report = await store.insert_report(payload, user_id=None, agent="manage_report")
            return json.dumps(
                {
                    "status": "created",
                    "id": report.id,
                    "url": f"{_web_base_url()}/reports?report={report.id}",
                }
            )

        if act == "delete":
            if not report_id:
                return "Error: action 'delete' requires report_id"
            async with _store_session() as store:
                deleted = await store.delete_report(report_id.strip())
            if not deleted:
                return json.dumps({"status": "not_found", "id": report_id})
            return json.dumps({"status": "deleted", "id": report_id})

        return "Error: action must be 'create' or 'delete'"

    except Exception as exc:
        from pydantic import ValidationError

        if isinstance(exc, ValidationError):
            return f"Error: invalid input — {exc.error_count()} validation error(s): {str(exc)[:300]}"
        return f"Error: {sanitize_mcp_error(str(exc))}"
