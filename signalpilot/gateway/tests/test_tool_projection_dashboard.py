"""Projection contracts for the dashboard sandbox tools."""

from __future__ import annotations

import json

from gateway.standalone_chat.tool_projection import finalize_payload, project_tool_result
from gateway.standalone_chat.tool_projection.limits import PAYLOAD_MAX

_SAMPLE = "mcp__standalone-chat__dashboard_sample_data"
_SCREENSHOT = "mcp__standalone-chat__dashboard_screenshot"


def _sample_payload(rows: int = 12, issues: list[dict] | None = None) -> str:
    return json.dumps(
        {
            "dashboard": {"valid": True, "errors": []},
            "charts": [
                {
                    "id": "revenue_by_month",
                    "type": "line",
                    "dataset": "monthly",
                    "resolved_file": "artifacts/monthly.csv",
                    "columns": [
                        {"name": "month", "inferred_type": "date"},
                        {"name": "revenue", "inferred_type": "number"},
                    ],
                    "row_count": rows,
                    "rows": [{"month": f"2026-{i + 1:02d}-01", "revenue": i * 10} for i in range(rows)],
                    "issues": issues or [],
                },
                {
                    "id": "orders_table",
                    "type": "table",
                    "dataset": "orders",
                    "resolved_file": None,
                    "columns": [{"name": "id", "inferred_type": "string"}],
                    "row_count": 0,
                    "rows": [],
                    "issues": [{"code": "empty_dataset", "message": "Chart orders_table has no rows"}],
                },
                {"id": "ghost", "issues": [{"code": "unknown_chart", "message": "ghost is not in the spec"}]},
            ],
        }
    )


class TestDashboardSample:
    def test_projects_chart_summaries_with_capped_rows(self) -> None:
        projected = project_tool_result(_SAMPLE, _sample_payload(), tool_input={"path": "artifacts/rev.dashboard.json"})

        assert projected.summary == "3 charts checked, 2 issues"
        result = projected.result
        assert result["kind"] == "dashboard_sample"
        assert result["dashboard_valid"] is True
        assert result["path"] == "artifacts/rev.dashboard.json"
        first = result["charts"][0]
        assert first["id"] == "revenue_by_month" and first["type"] == "line"
        assert first["row_count"] == 12 and first["issue_count"] == 0
        assert first["columns"] == ["month", "revenue"]
        assert len(first["rows"]) == 5 and first["rows"][0] == {"month": "2026-01-01", "revenue": 0}
        assert result["charts"][1]["issues"] == [
            {"code": "empty_dataset", "message": "Chart orders_table has no rows"}
        ]
        assert result["charts"][2] == {
            "id": "ghost",
            "type": "",
            "row_count": 0,
            "issue_count": 1,
            "columns": [],
            "rows": [],
            "issues": [{"code": "unknown_chart", "message": "ghost is not in the spec"}],
        }
        assert projected.result_text is not None

    def test_single_issue_and_no_issue_summaries(self) -> None:
        one = json.dumps(
            {
                "dashboard": {"valid": True, "errors": []},
                "charts": [{"id": "a", "type": "kpi", "columns": [], "row_count": 1, "rows": [], "issues": [{"code": "x", "message": "m"}]}],
            }
        )
        assert project_tool_result(_SAMPLE, one).summary == "1 chart checked, 1 issue"
        none = json.dumps(
            {"dashboard": {"valid": True, "errors": []}, "charts": [{"id": "a", "type": "kpi", "rows": [], "issues": []}]}
        )
        assert project_tool_result(_SAMPLE, none).summary == "1 chart checked, no issues"

    def test_invalid_spec(self) -> None:
        text = json.dumps({"dashboard": {"valid": False, "errors": ["'title' is a required property"]}, "charts": []})
        projected = project_tool_result(_SAMPLE, text)

        assert projected.summary == "Dashboard spec invalid · 1 error"
        assert projected.result["dashboard_valid"] is False
        assert projected.result["charts"] == []
        assert projected.result["errors"] == ["'title' is a required property"]

    def test_non_json_falls_back_to_text(self) -> None:
        projected = project_tool_result(_SAMPLE, "Error: path must start with artifacts/")
        assert projected.result == {"kind": "text"}
        assert projected.summary.startswith("Error: path must start")

    def test_finalize_drops_rows_before_anything_else(self) -> None:
        wide = json.dumps(
            {
                "dashboard": {"valid": True, "errors": []},
                "charts": [
                    {
                        "id": f"c{i}",
                        "type": "table",
                        "columns": [{"name": "blob"}],
                        "row_count": 5,
                        "rows": [{"blob": "x" * 4000} for _ in range(5)],
                        "issues": [],
                    }
                    for i in range(40)
                ],
            }
        )
        projected = project_tool_result(_SAMPLE, wide)
        payload = finalize_payload(
            {
                "tool": _SAMPLE,
                "summary": projected.summary,
                "result": projected.result,
                "result_text": projected.result_text,
                "v": 1,
            }
        )
        assert len(json.dumps(payload, separators=(",", ":")).encode()) <= PAYLOAD_MAX
        assert payload["truncated"] is True
        assert payload["result"]["kind"] == "dashboard_sample"
        assert payload["result"]["rows_truncated"] is True
        assert all(chart["rows"] == [] for chart in payload["result"]["charts"])
        assert len(payload["result"]["charts"]) == 40


class TestDashboardScreenshot:
    def test_projects_render_status(self) -> None:
        text = json.dumps(
            {
                "dashboard": {"valid": True, "errors": []},
                "rendered": ["kpi_total", "revenue_by_month", "orders_table", "share"],
                "failed": [],
                "width": 1280,
                "height": 720,
                "preview_path": ".dashboard-previews/rev-1757000000.png",
            }
        )
        projected = project_tool_result(_SCREENSHOT, text, tool_input={"path": "artifacts/rev.dashboard.json"})

        assert projected.summary == "Rendered 4 charts"
        assert projected.result == {
            "kind": "dashboard_screenshot",
            "dashboard_valid": True,
            "rendered": ["kpi_total", "revenue_by_month", "orders_table", "share"],
            "failed": [],
            "width": 1280,
            "height": 720,
            "preview_path": ".dashboard-previews/rev-1757000000.png",
            "path": "artifacts/rev.dashboard.json",
        }

    def test_failed_charts_in_summary(self) -> None:
        text = json.dumps(
            {
                "dashboard": {"valid": True, "errors": []},
                "rendered": ["a", "b", "c"],
                "failed": [{"id": "d", "code": "missing_column", "message": "Chart d: column x not in [a, b]"}],
                "width": 1280,
                "height": 400,
                "preview_path": ".dashboard-previews/x-1.png",
            }
        )
        projected = project_tool_result(_SCREENSHOT, text)
        assert projected.summary == "Rendered 3 charts, 1 failed"
        assert projected.result["failed"] == [
            {"id": "d", "code": "missing_column", "message": "Chart d: column x not in [a, b]"}
        ]

    def test_content_block_list_uses_the_text_part(self) -> None:
        inner = {"dashboard": {"valid": True, "errors": []}, "rendered": ["a"], "failed": [], "width": 640, "height": 300}
        blocks = [
            {"type": "image", "data": "iVBORw0KGgo=", "mimeType": "image/png"},
            {"type": "text", "text": json.dumps(inner)},
        ]
        projected = project_tool_result(_SCREENSHOT, blocks)
        assert projected.summary == "Rendered 1 chart"
        assert projected.result["rendered"] == ["a"] and projected.result["width"] == 640

    def test_renderer_unavailable_and_invalid_spec(self) -> None:
        missing = json.dumps({"dashboard": {"valid": True, "errors": []}, "error": "renderer_unavailable", "rendered": [], "failed": []})
        projected = project_tool_result(_SCREENSHOT, missing)
        assert projected.summary == "Dashboard renderer unavailable"
        assert projected.result["error"] == "renderer_unavailable"

        invalid = json.dumps({"dashboard": {"valid": False, "errors": ["bad", "worse"]}, "rendered": [], "failed": []})
        projected = project_tool_result(_SCREENSHOT, invalid)
        assert projected.summary == "Dashboard spec invalid · 2 errors"
        assert projected.result["dashboard_valid"] is False and projected.result["errors"] == ["bad", "worse"]


_LIST = "mcp__standalone-chat__dashboard_list_published"
_LOAD = "mcp__standalone-chat__dashboard_load_published"


def _list_entry(i: int, description: str | None = "Monthly revenue") -> dict:
    return {
        "id": f"dash_{i:04d}",
        "slug": f"revenue-{i}",
        "name": f"Revenue {i}",
        "description": description,
        "chart_count": 3,
        "visibility": "org",
        "updated_at": "2026-09-08T10:00:00+00:00",
        "last_refresh_at": None,
        "can_edit": i % 2 == 0,
    }


class TestDashboardList:
    def test_projects_entries_with_the_contract_fields(self) -> None:
        text = json.dumps({"dashboards": [_list_entry(0), _list_entry(1, None)]})
        projected = project_tool_result(_LIST, text)

        assert projected.summary == "2 dashboards"
        assert projected.result["kind"] == "dashboard_list"
        assert projected.result["dashboards"][0] == _list_entry(0)
        assert projected.result["dashboards"][1]["description"] is None
        assert "dashboards_truncated" not in projected.result

    def test_empty_and_single(self) -> None:
        assert project_tool_result(_LIST, json.dumps({"dashboards": []})).summary == "No dashboards"
        assert project_tool_result(_LIST, json.dumps({"dashboards": [_list_entry(0)]})).summary == "1 dashboard"

    def test_caps_entries_and_description(self) -> None:
        text = json.dumps({"dashboards": [_list_entry(i, "d" * 500) for i in range(60)]})
        projected = project_tool_result(_LIST, text)

        assert projected.summary == "60 dashboards"
        assert len(projected.result["dashboards"]) == 50
        assert projected.result["dashboards_truncated"] is True
        assert len(projected.result["dashboards"][0]["description"]) == 200

    def test_non_json_falls_back_to_text(self) -> None:
        projected = project_tool_result(_LIST, "Error: gateway unreachable")
        assert projected.result == {"kind": "text"}

    def test_finalize_shrinks_the_list_before_dropping_the_kind(self) -> None:
        text = json.dumps({"dashboards": [_list_entry(i, "d" * 200) for i in range(50)]})
        projected = project_tool_result(_LIST, text)
        payload = finalize_payload(
            {
                "tool": _LIST,
                "summary": projected.summary,
                "result": projected.result,
                "result_text": "x" * (PAYLOAD_MAX - 2000),
                "v": 1,
            }
        )
        assert len(json.dumps(payload, separators=(",", ":")).encode()) <= PAYLOAD_MAX
        assert payload["truncated"] is True
        assert payload["result"]["kind"] == "dashboard_list"
        assert len(payload["result"]["dashboards"]) == 10
        assert payload["result"]["dashboards_truncated"] is True


def _load_payload() -> dict:
    return {
        "path": "artifacts/revenue.dashboard.json",
        "dashboard": {"id": "dash_0001", "slug": "revenue", "name": "Revenue", "version_no": 3, "chart_count": 4, "extra": 1},
        "datasets": {
            "monthly": {"rows": 12, "snapshot": "artifacts/datasets/monthly.csv"},
            "regions": {"rows": 4, "snapshot": "artifacts/datasets/regions.csv"},
        },
        "next": "Edit the file, then run dashboard_sample_data.",
    }


class TestDashboardLoad:
    def test_projects_a_loaded_dashboard(self) -> None:
        projected = project_tool_result(_LOAD, json.dumps(_load_payload()))

        assert projected.summary == "Loaded Revenue v3"
        assert projected.result == {
            "kind": "dashboard_load",
            "path": "artifacts/revenue.dashboard.json",
            "dashboard": {"id": "dash_0001", "slug": "revenue", "name": "Revenue", "version_no": 3, "chart_count": 4},
            "datasets": {
                "monthly": {"rows": 12, "snapshot": "artifacts/datasets/monthly.csv"},
                "regions": {"rows": 4, "snapshot": "artifacts/datasets/regions.csv"},
            },
        }

    def test_projects_a_failed_load(self) -> None:
        text = json.dumps({"error": "not_found", "message": "No dashboard with slug 'ghost'"})
        projected = project_tool_result(_LOAD, text)

        assert projected.summary == "Load failed: No dashboard with slug 'ghost'"
        assert projected.result == {
            "kind": "dashboard_load",
            "error": "not_found",
            "message": "No dashboard with slug 'ghost'",
        }

    def test_error_without_message_uses_the_code(self) -> None:
        projected = project_tool_result(_LOAD, json.dumps({"error": "forbidden"}))
        assert projected.summary == "Load failed: forbidden"
        assert projected.result["message"] == "forbidden"

    def test_finalize_drops_datasets_first(self) -> None:
        payload_in = _load_payload()
        payload_in["datasets"] = {f"d{i}": {"rows": i, "snapshot": f"artifacts/datasets/d{i}.csv"} for i in range(50)}
        projected = project_tool_result(_LOAD, json.dumps(payload_in))
        payload = finalize_payload(
            {
                "tool": _LOAD,
                "summary": projected.summary,
                "result": projected.result,
                "result_text": "x" * (PAYLOAD_MAX - 1500),
                "v": 1,
            }
        )
        assert len(json.dumps(payload, separators=(",", ":")).encode()) <= PAYLOAD_MAX
        assert payload["truncated"] is True
        assert payload["result"]["kind"] == "dashboard_load"
        assert payload["result"]["datasets"] == {} and payload["result"]["datasets_truncated"] is True
        assert payload["result"]["dashboard"]["slug"] == "revenue"


def test_screenshot_parses_past_the_flattened_image_marker():
    """The runtime hands the projector an "[image]" line followed by the JSON text."""
    text = "[image]\n" + json.dumps(
        {"dashboard": {"valid": True, "errors": []}, "rendered": ["a", "b"], "failed": [], "width": 1280, "height": 400}
    )
    projected = project_tool_result("mcp__standalone-chat__dashboard_screenshot", text)
    assert projected.result["kind"] == "dashboard_screenshot"
    assert projected.result["rendered"] == ["a", "b"]
    assert projected.summary == "Rendered 2 charts"
