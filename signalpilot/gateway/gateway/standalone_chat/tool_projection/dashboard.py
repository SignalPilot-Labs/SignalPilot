"""Projections for the dashboard sandbox tools.

``dashboard_sample_data`` returns one JSON document; ``dashboard_screenshot``
returns ``[image, text-JSON]`` content, of which only the text part reaches
the projector. ``dashboard_list_published`` and ``dashboard_load_published``
read the published gallery through the gateway on the user's behalf. Every
projection keeps previews small so the ``tool_completed`` event stays well
under ``PAYLOAD_MAX``.
"""

from __future__ import annotations

from typing import Any

from gateway.standalone_chat.tool_projection.base import ProjectedResult, build, text_result
from gateway.standalone_chat.tool_projection.text import summary_text, try_json

SAMPLE_ROWS_MAX = 5
SAMPLE_COLUMNS_MAX = 40
ISSUES_MAX = 10
ISSUE_MESSAGE_MAX = 300
CHART_IDS_MAX = 50
LIST_ENTRIES_MAX = 50
LIST_DESCRIPTION_MAX = 200
LOAD_DATASETS_MAX = 50
LIST_FIELDS = ("id", "slug", "name", "description", "chart_count", "visibility", "updated_at", "last_refresh_at", "can_edit")
LOAD_DASHBOARD_FIELDS = ("id", "slug", "name", "version_no", "chart_count")


def _payload(text: str) -> dict[str, Any] | None:
    """Return the tool's JSON document.

    The runtime flattens a mixed content list into text: an image block
    becomes an "[image]" line followed by the text block. Drop everything
    before the first "{" so the JSON document parses.
    """
    parsed = try_json(text)
    if parsed is None and "{" in text:
        parsed = try_json(text[text.index("{") :])
    if isinstance(parsed, list):
        for block in parsed:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                inner = try_json(block["text"])
                if isinstance(inner, dict):
                    return inner
        return None
    return parsed if isinstance(parsed, dict) else None


def _dashboard_status(parsed: dict[str, Any]) -> tuple[bool, list[str]]:
    dashboard = parsed.get("dashboard")
    if not isinstance(dashboard, dict):
        return True, []
    errors = dashboard.get("errors")
    errors_out = [str(error)[:ISSUE_MESSAGE_MAX] for error in errors[:ISSUES_MAX]] if isinstance(errors, list) else []
    return bool(dashboard.get("valid", True)), errors_out


def _issues(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    issues: list[dict[str, str]] = []
    for issue in raw[:ISSUES_MAX]:
        if isinstance(issue, dict):
            issues.append(
                {
                    "code": str(issue.get("code") or "issue"),
                    "message": str(issue.get("message") or "")[:ISSUE_MESSAGE_MAX],
                }
            )
    return issues


def _column_names(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    names: list[str] = []
    for column in raw[:SAMPLE_COLUMNS_MAX]:
        if isinstance(column, dict) and column.get("name") is not None:
            names.append(str(column["name"]))
        elif isinstance(column, str):
            names.append(column)
    return names


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


def project_dashboard_sample(content: str, tool_input: dict[str, Any] | None) -> ProjectedResult:
    text = content or ""
    parsed = _payload(text)
    if parsed is None:
        return text_result(text, summary=summary_text(text, "Dashboard data"))
    valid, errors = _dashboard_status(parsed)
    charts_out: list[dict[str, Any]] = []
    issue_total = 0
    for chart in parsed.get("charts") or []:
        if not isinstance(chart, dict):
            continue
        issues = _issues(chart.get("issues"))
        raw_issue_count = chart.get("issues")
        issue_count = len(raw_issue_count) if isinstance(raw_issue_count, list) else len(issues)
        issue_total += issue_count
        rows = chart.get("rows")
        row_count = chart.get("row_count")
        entry: dict[str, Any] = {
            "id": str(chart.get("id") or ""),
            "type": str(chart.get("type") or ""),
            "row_count": row_count if isinstance(row_count, int) else 0,
            "issue_count": issue_count,
            "columns": _column_names(chart.get("columns")),
            "rows": [row for row in rows[:SAMPLE_ROWS_MAX] if isinstance(row, dict)] if isinstance(rows, list) else [],
            "issues": issues,
        }
        charts_out.append(entry)
    result: dict[str, Any] = {
        "kind": "dashboard_sample",
        "dashboard_valid": valid,
        "charts": charts_out,
    }
    if tool_input and isinstance(tool_input.get("path"), str):
        result["path"] = tool_input["path"]
    if errors:
        result["errors"] = errors
    if not valid:
        summary = f"Dashboard spec invalid · {_plural(len(errors), 'error')}" if errors else "Dashboard spec invalid"
    else:
        issue_text = _plural(issue_total, "issue") if issue_total else "no issues"
        summary = f"{_plural(len(charts_out), 'chart')} checked, {issue_text}"
    return build(result, summary=summary, text=text)


def project_dashboard_screenshot(content: str, tool_input: dict[str, Any] | None) -> ProjectedResult:
    text = content or ""
    parsed = _payload(text)
    if parsed is None:
        return text_result(text, summary=summary_text(text, "Dashboard screenshot"))
    valid, errors = _dashboard_status(parsed)
    rendered_raw = parsed.get("rendered")
    rendered = [str(item) for item in rendered_raw[:CHART_IDS_MAX]] if isinstance(rendered_raw, list) else []
    failed_raw = parsed.get("failed")
    failed: list[dict[str, str]] = []
    if isinstance(failed_raw, list):
        for item in failed_raw[:CHART_IDS_MAX]:
            if isinstance(item, dict):
                failed.append(
                    {
                        "id": str(item.get("id") or ""),
                        "code": str(item.get("code") or "failed"),
                        "message": str(item.get("message") or "")[:ISSUE_MESSAGE_MAX],
                    }
                )
            else:
                failed.append({"id": str(item), "code": "failed", "message": ""})
    result: dict[str, Any] = {
        "kind": "dashboard_screenshot",
        "dashboard_valid": valid,
        "rendered": rendered,
        "failed": failed,
    }
    for key in ("width", "height"):
        value = parsed.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            result[key] = value
    if isinstance(parsed.get("preview_path"), str):
        result["preview_path"] = parsed["preview_path"]
    if tool_input and isinstance(tool_input.get("path"), str):
        result["path"] = tool_input["path"]
    if errors:
        result["errors"] = errors
    error = parsed.get("error")
    if isinstance(error, str) and error:
        result["error"] = error[:ISSUE_MESSAGE_MAX]
        summary = "Dashboard renderer unavailable" if error == "renderer_unavailable" else f"Dashboard render error · {error}"
    elif not valid:
        summary = f"Dashboard spec invalid · {_plural(len(errors), 'error')}" if errors else "Dashboard spec invalid"
    else:
        summary = f"Rendered {_plural(len(rendered), 'chart')}"
        if failed:
            summary += f", {len(failed)} failed"
    return build(result, summary=summary, text=text)


def _list_entry(raw: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = {name: raw.get(name) for name in LIST_FIELDS}
    description = entry.get("description")
    entry["description"] = str(description)[:LIST_DESCRIPTION_MAX] if isinstance(description, str) else None
    return entry


def project_dashboard_list(content: str, tool_input: dict[str, Any] | None) -> ProjectedResult:
    text = content or ""
    parsed = _payload(text)
    if parsed is None:
        return text_result(text, summary=summary_text(text, "Published dashboards"))
    raw = parsed.get("dashboards")
    entries = [_list_entry(item) for item in raw[:LIST_ENTRIES_MAX] if isinstance(item, dict)] if isinstance(raw, list) else []
    result: dict[str, Any] = {"kind": "dashboard_list", "dashboards": entries}
    total = len(raw) if isinstance(raw, list) else 0
    if total > len(entries):
        result["dashboards_truncated"] = True
    summary = _plural(total, "dashboard") if total else "No dashboards"
    return build(result, summary=summary, text=text)


def _load_datasets(raw: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict):
        return {}
    datasets: dict[str, dict[str, Any]] = {}
    for name, value in list(raw.items())[:LOAD_DATASETS_MAX]:
        if isinstance(value, dict):
            rows = value.get("rows")
            datasets[str(name)] = {
                "rows": rows if isinstance(rows, int) and not isinstance(rows, bool) else 0,
                "snapshot": str(value.get("snapshot") or ""),
            }
    return datasets


def project_dashboard_load(content: str, tool_input: dict[str, Any] | None) -> ProjectedResult:
    text = content or ""
    parsed = _payload(text)
    if parsed is None:
        return text_result(text, summary=summary_text(text, "Published dashboard"))
    result: dict[str, Any] = {"kind": "dashboard_load"}
    error = parsed.get("error")
    if isinstance(error, str) and error:
        message = str(parsed.get("message") or error)[:ISSUE_MESSAGE_MAX]
        result["error"] = error[:ISSUE_MESSAGE_MAX]
        result["message"] = message
        return build(result, summary=f"Load failed: {message}", text=text)
    dashboard_raw = parsed.get("dashboard")
    dashboard = {name: dashboard_raw.get(name) for name in LOAD_DASHBOARD_FIELDS} if isinstance(dashboard_raw, dict) else {}
    if isinstance(parsed.get("path"), str):
        result["path"] = parsed["path"]
    result["dashboard"] = dashboard
    result["datasets"] = _load_datasets(parsed.get("datasets"))
    name = str(dashboard.get("name") or dashboard.get("slug") or "dashboard")
    version_no = dashboard.get("version_no")
    summary = f"Loaded {name} v{version_no}" if isinstance(version_no, int) else f"Loaded {name}"
    return build(result, summary=summary, text=text)
