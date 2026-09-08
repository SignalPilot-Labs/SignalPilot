"""dashboard_sample_data and dashboard_screenshot tool contracts."""

from __future__ import annotations

import base64
import json
import sys
from typing import TYPE_CHECKING, Any

import pytest

from signalpilot._server.ai.dashboard.tools import (
    dashboard_sample_data,
    dashboard_screenshot,
)

if TYPE_CHECKING:
    from pathlib import Path

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)

FAKE_CLI = """
import base64, json, sys
args = sys.argv[1:]
out = args[args.index("--out") + 1]
width = int(args[args.index("--width") + 1])
theme = args[args.index("--theme") + 1]
payload = json.load(sys.stdin)
png = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
with open(out, "wb") as handle:
    handle.write(png)
ids = payload["chart_ids"] or [c["id"] for c in payload["spec"]["charts"]]
sys.stderr.write("noise\\n")
print("debug line that is not json")
print(json.dumps({
    "ok": True,
    "rendered": ids,
    "failed": [],
    "width": width,
    "height": 400,
    "theme": theme,
    "dataset_names": sorted(payload["datasets"]),
}))
"""


def _write_dashboard(scratch: Path) -> None:
    artifacts = scratch / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "monthly.csv").write_text(
        "month,revenue\n2025-02-01,20\n2025-01-01,10\n2025-03-01,30\n",
        encoding="utf-8",
    )
    spec: dict[str, Any] = {
        "version": 1,
        "title": "Revenue",
        "datasets": {
            "monthly": {"file": "artifacts/monthly.csv"},
            "totals": {"rows": [{"revenue": 60}]},
            "broken": {"file": "artifacts/missing.csv"},
        },
        "charts": [
            {
                "id": "rev",
                "type": "line",
                "title": "Revenue",
                "dataset": "monthly",
                "x": {"column": "month", "type": "date"},
                "y": [{"column": "revenue", "format": "integer"}],
                "sort": {"column": "month", "direction": "desc"},
                "limit": 2,
            },
            {
                "id": "total",
                "type": "kpi",
                "title": "Total",
                "dataset": "totals",
                "value": {"column": "revenue"},
            },
            {
                "id": "lost",
                "type": "kpi",
                "title": "Lost",
                "dataset": "broken",
                "value": {"column": "revenue"},
            },
        ],
    }
    (artifacts / "revenue.dashboard.json").write_text(
        json.dumps(spec), encoding="utf-8"
    )


@pytest.mark.asyncio
async def test_sample_data_happy_path_and_unknown_id(tmp_path: Path):
    _write_dashboard(tmp_path)
    result = await dashboard_sample_data(
        scratch_directory=tmp_path,
        path="artifacts/revenue.dashboard.json",
        chart_ids=["rev", "total", "ghost", "lost"],
        limit=1,
    )
    assert len(result) == 1
    payload = json.loads(result[0].text)
    assert payload["dashboard"] == {"valid": True, "errors": []}
    rev, total, ghost, lost = payload["charts"]
    assert rev["id"] == "rev"
    assert rev["type"] == "line"
    assert rev["dataset"] == "monthly"
    assert rev["resolved_file"] == "artifacts/monthly.csv"
    assert rev["columns"] == [
        {"name": "month", "inferred_type": "date"},
        {"name": "revenue", "inferred_type": "number"},
    ]
    assert rev["row_count"] == 2
    assert rev["rows"] == [{"month": "2025-03-01", "revenue": 30}]
    assert rev["issues"] == []
    assert total["resolved_file"] is None
    assert total["rows"] == [{"revenue": 60}]
    assert ghost == {
        "id": "ghost",
        "issues": [
            {
                "code": "unknown_chart",
                "message": (
                    "Chart 'ghost' is not in the dashboard. Valid ids: rev, "
                    "total, lost."
                ),
            }
        ],
    }
    assert lost["issues"][0]["code"] == "dataset_unreadable"
    assert "artifacts/missing.csv" in lost["issues"][0]["message"]


@pytest.mark.asyncio
async def test_sample_data_invalid_spec_and_bad_paths(tmp_path: Path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "bad.dashboard.json").write_text(
        json.dumps({"version": 2, "title": "", "datasets": {}, "charts": []}),
        encoding="utf-8",
    )
    result = await dashboard_sample_data(
        scratch_directory=tmp_path,
        path="artifacts/bad.dashboard.json",
        chart_ids=["a"],
    )
    payload = json.loads(result[0].text)
    assert payload["dashboard"]["valid"] is False
    assert payload["charts"] == []
    assert any(
        "$.version" in error for error in payload["dashboard"]["errors"]
    )

    (artifacts / "broken.dashboard.json").write_text("{", encoding="utf-8")
    payload = json.loads(
        (
            await dashboard_sample_data(
                scratch_directory=tmp_path,
                path="artifacts/broken.dashboard.json",
                chart_ids=["a"],
            )
        )[0].text
    )
    assert payload["dashboard"]["valid"] is False
    assert "not valid JSON" in payload["dashboard"]["errors"][0]

    for bad in (
        "revenue.dashboard.json",
        "artifacts/revenue.json",
        "artifacts/../revenue.dashboard.json",
        "artifacts/none.dashboard.json",
    ):
        payload = json.loads(
            (
                await dashboard_sample_data(
                    scratch_directory=tmp_path, path=bad, chart_ids=["a"]
                )
            )[0].text
        )
        assert payload["dashboard"]["valid"] is False, bad
        assert payload["charts"] == []

    payload = json.loads(
        (
            await dashboard_sample_data(
                scratch_directory=tmp_path,
                path="artifacts/bad.dashboard.json",
                chart_ids=[],
            )
        )[0].text
    )
    assert payload["dashboard"]["valid"] is False
    assert "chart_ids" in payload["dashboard"]["errors"][0]


@pytest.mark.asyncio
async def test_screenshot_with_fake_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _write_dashboard(tmp_path)
    cli = tmp_path / "render-cli.js"
    cli.write_text(FAKE_CLI, encoding="utf-8")
    monkeypatch.setenv("SP_DASHBOARD_RENDER_CLI", str(cli))
    monkeypatch.setenv("SP_DASHBOARD_NODE", sys.executable)

    result = await dashboard_screenshot(
        scratch_directory=tmp_path,
        path="artifacts/revenue.dashboard.json",
        chart_ids=None,
        width=800,
        theme="dark",
    )
    assert len(result) == 2
    image, text = result
    assert image.type == "image"
    assert image.mimeType == "image/png"
    assert base64.b64decode(image.data) == PNG_1X1
    payload = json.loads(text.text)
    assert payload["dashboard"] == {"valid": True, "errors": []}
    assert payload["rendered"] == ["rev", "total"]
    assert payload["failed"] == [
        {
            "id": "lost",
            "code": "dataset_unreadable",
            "message": (
                "Chart 'lost' dataset 'broken' is unreadable: Dataset file "
                "not found: artifacts/missing.csv"
            ),
        }
    ]
    assert payload["width"] == 800
    assert payload["height"] == 400
    assert payload["preview_path"].startswith(".dashboard-previews/revenue-")
    assert payload["preview_path"].endswith(".png")
    assert (tmp_path / payload["preview_path"]).read_bytes() == PNG_1X1

    subset = await dashboard_screenshot(
        scratch_directory=tmp_path,
        path="artifacts/revenue.dashboard.json",
        chart_ids=["total"],
    )
    assert json.loads(subset[1].text)["rendered"] == ["total"]

    unknown = await dashboard_screenshot(
        scratch_directory=tmp_path,
        path="artifacts/revenue.dashboard.json",
        chart_ids=["ghost"],
    )
    assert len(unknown) == 1
    unknown_payload = json.loads(unknown[0].text)
    assert unknown_payload["dashboard"]["valid"] is False
    assert "ghost" in unknown_payload["dashboard"]["errors"][0]


@pytest.mark.asyncio
async def test_screenshot_renderer_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _write_dashboard(tmp_path)
    monkeypatch.setenv(
        "SP_DASHBOARD_RENDER_CLI", str(tmp_path / "nope" / "render-cli.js")
    )
    result = await dashboard_screenshot(
        scratch_directory=tmp_path,
        path="artifacts/revenue.dashboard.json",
    )
    assert len(result) == 1
    payload = json.loads(result[0].text)
    assert payload["error"] == "renderer_unavailable"
    assert payload["dashboard"] == {"valid": True, "errors": []}
    assert not (tmp_path / ".dashboard-previews").exists()

    cli = tmp_path / "render-cli.js"
    cli.write_text(FAKE_CLI, encoding="utf-8")
    monkeypatch.setenv("SP_DASHBOARD_RENDER_CLI", str(cli))
    monkeypatch.setenv("SP_DASHBOARD_NODE", "no-such-node-binary-xyz")
    result = await dashboard_screenshot(
        scratch_directory=tmp_path,
        path="artifacts/revenue.dashboard.json",
    )
    assert json.loads(result[0].text)["error"] == "renderer_unavailable"


@pytest.mark.asyncio
async def test_screenshot_reports_a_crashing_renderer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _write_dashboard(tmp_path)
    cli = tmp_path / "render-cli.js"
    cli.write_text(
        "import sys\nsys.stderr.write('boom')\nsys.exit(2)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SP_DASHBOARD_RENDER_CLI", str(cli))
    monkeypatch.setenv("SP_DASHBOARD_NODE", sys.executable)
    result = await dashboard_screenshot(
        scratch_directory=tmp_path,
        path="artifacts/revenue.dashboard.json",
    )
    assert len(result) == 1
    payload = json.loads(result[0].text)
    assert payload["error"] == "render_failed"
    assert "boom" in payload["message"]
    assert payload["failed"][0]["id"] == "lost"


@pytest.mark.asyncio
async def test_screenshot_invalid_spec_returns_text_only(tmp_path: Path):
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "artifacts" / "x.dashboard.json").write_text(
        "[]", encoding="utf-8"
    )
    result = await dashboard_screenshot(
        scratch_directory=tmp_path, path="artifacts/x.dashboard.json"
    )
    assert len(result) == 1
    payload = json.loads(result[0].text)
    assert payload["dashboard"]["valid"] is False
    assert payload["rendered"] == []
