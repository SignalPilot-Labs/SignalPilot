"""Reports MCP tools for rendered HTML reports and dashboards."""

from __future__ import annotations

import json
import os

from gateway.errors.mcp import sanitize_mcp_error
from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _require_mcp_admin_scope, _store_session
from gateway.mcp.server import mcp
from gateway.models.reports import ReportCreate, ReportUpdate

_DEFAULT_WEB_URL = "http://localhost:3200"


def _web_base_url() -> str:
    return (os.getenv("SP_WEB_URL") or os.getenv("SIGNALPILOT_WEB_URL") or _DEFAULT_WEB_URL).rstrip("/")


def _parse_data_json(value: str | None):
    if value is None or value == "":
        return None
    return json.loads(value)


def _report_update_payload(
    *,
    title: str | None,
    html: str | None,
    data_json: str | None,
) -> ReportUpdate:
    kwargs = {}
    if title is not None:
        kwargs["title"] = title
    if html is not None:
        kwargs["html"] = html
    if data_json is not None:
        kwargs["data_json"] = _parse_data_json(data_json)
    return ReportUpdate(**kwargs)


@audited_tool(mcp)
async def manage_report(
    action: str,
    title: str | None = None,
    html: str | None = None,
    report_id: str | None = None,
    scope_ref: str | None = None,
    data_json: str | None = None,
) -> str:
    """Create, edit, or permanently delete a rendered HTML report.

    action="create": requires title and html (a full, self-contained HTML
    document). Optionally pass scope_ref to group the report under a project.
    Returns the new report id and a shareable URL.

    action="edit": requires report_id and at least one of title, html, data_json.

    action="delete": requires report_id. Deletion is permanent — there is no
    archive or undo.
    """
    try:
        act = (action or "").strip().lower()

        if act in ("create", "edit", "delete"):
            err = _require_mcp_admin_scope()
            if err:
                return err

        if act == "create":
            if not title or not html:
                return "Error: action 'create' requires both title and html"
            payload = ReportCreate(
                title=title,
                html=html,
                scope_ref=scope_ref,
                kind="report",
                data_json=_parse_data_json(data_json),
            )
            async with _store_session() as store:
                report = await store.insert_report(payload, user_id=None, agent="manage_report")
            return json.dumps(
                {
                    "status": "created",
                    "id": report.id,
                    "url": f"{_web_base_url()}/reports?report={report.id}",
                }
            )

        if act == "edit":
            if not report_id:
                return "Error: action 'edit' requires report_id"
            if title is None and html is None and data_json is None:
                return "Error: action 'edit' requires title, html, or data_json"
            payload = _report_update_payload(title=title, html=html, data_json=data_json)
            async with _store_session() as store:
                report = await store.update_report_html(report_id.strip(), payload)
            return json.dumps(
                {
                    "status": "edited",
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

        return "Error: action must be 'create', 'edit', or 'delete'"

    except Exception as exc:
        from pydantic import ValidationError

        if isinstance(exc, ValidationError):
            return f"Error: invalid input — {exc.error_count()} validation error(s): {str(exc)[:300]}"
        return f"Error: {sanitize_mcp_error(str(exc))}"


@audited_tool(mcp)
async def manage_dashboard(
    action: str,
    title: str | None = None,
    html: str | None = None,
    data_json: str | None = None,
    dashboard_id: str | None = None,
    scope_ref: str | None = None,
) -> str:
    """Create, edit, or permanently delete an HTML dashboard.

    action="create": requires title, html, and data_json.
    action="edit": requires dashboard_id and at least one of title, html,
    data_json.
    action="delete": requires dashboard_id.
    """
    try:
        act = (action or "").strip().lower()
        if act in ("create", "edit", "delete"):
            err = _require_mcp_admin_scope()
            if err:
                return err

        if act == "create":
            if not title or not html or data_json is None:
                return "Error: action 'create' requires title, html, and data_json"
            payload = ReportCreate(
                title=title,
                html=html,
                scope_ref=scope_ref,
                kind="dashboard",
                data_json=_parse_data_json(data_json),
            )
            async with _store_session() as store:
                report = await store.insert_report(payload, user_id=None, agent="manage_dashboard")
            return json.dumps(
                {
                    "status": "created",
                    "id": report.id,
                    "url": f"{_web_base_url()}/reports?report={report.id}",
                }
            )

        if act == "edit":
            if not dashboard_id:
                return "Error: action 'edit' requires dashboard_id"
            if title is None and html is None and data_json is None:
                return "Error: action 'edit' requires title, html, or data_json"
            payload = _report_update_payload(title=title, html=html, data_json=data_json)
            async with _store_session() as store:
                report = await store.update_report_html(dashboard_id.strip(), payload)
            return json.dumps(
                {
                    "status": "edited",
                    "id": report.id,
                    "url": f"{_web_base_url()}/reports?report={report.id}",
                }
            )

        if act == "delete":
            if not dashboard_id:
                return "Error: action 'delete' requires dashboard_id"
            async with _store_session() as store:
                deleted = await store.delete_report(dashboard_id.strip())
            if not deleted:
                return json.dumps({"status": "not_found", "id": dashboard_id})
            return json.dumps({"status": "deleted", "id": dashboard_id})

        return "Error: action must be 'create', 'edit', or 'delete'"

    except Exception as exc:
        from pydantic import ValidationError

        if isinstance(exc, ValidationError):
            return f"Error: invalid input — {exc.error_count()} validation error(s): {str(exc)[:300]}"
        return f"Error: {sanitize_mcp_error(str(exc))}"
