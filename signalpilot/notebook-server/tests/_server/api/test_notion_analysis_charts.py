from __future__ import annotations

import base64
import importlib
import json
import sys
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

_stubbed_signalpilot = sys.modules.get("signalpilot")
if getattr(_stubbed_signalpilot, "__spec__", None) is None:
    del sys.modules["signalpilot"]

notion_analysis = importlib.import_module(
    "signalpilot._server.api.endpoints.notion_analysis"
)


def _app_state(tmp_path):
    return SimpleNamespace(
        session_manager=SimpleNamespace(
            workspace=SimpleNamespace(directory=str(tmp_path)),
            get_session=lambda _session_id: None,
        )
    )


def _record() -> notion_analysis.AnalysisRecord:
    return notion_analysis.AnalysisRecord(
        request_id="notion-test",
        discussion_id="discussion",
        session_id="session",
        notebook_path="analysis.py",
        trail_url="http://localhost/projects?file=analysis.py",
        status="Done",
        headline="Analysis",
        source_url="slack://message",
        created_at="2026-06-18T00:00:00Z",
    )


def test_chart_url_carries_project_branch_context(tmp_path) -> None:
    project = "1dbf5492-81e6-4683-835f-f1785c9cfe78"
    branch = "analysis/notion/notion-req-analyze"
    app_state = SimpleNamespace(
        request=SimpleNamespace(headers={}),
        query_params=lambda key: {"project": project, "branch": branch}.get(key),
        session_manager=SimpleNamespace(
            workspace=SimpleNamespace(directory=str(tmp_path)),
            get_session=lambda _session_id: None,
        ),
    )

    url = notion_analysis._chart_url(app_state, _record(), "chart.png")
    parsed = urlparse(url)

    assert parsed.path == "/api/notion-analysis/chart/notion-test/chart.png"
    assert parse_qs(parsed.query) == {
        "project": [project],
        "branch": [branch],
    }


def test_finds_existing_chart_file_from_project_registry(
    tmp_path, monkeypatch
) -> None:
    from signalpilot._server.files import project_sync

    project_root = tmp_path / "projects" / "project-1" / "repo"
    notebook_path = "notebooks/notion/analysis.py"
    chart_dir = (
        project_root
        / "notebooks"
        / "notion"
        / "public"
        / "signalpilot-notion-charts"
    )
    chart_dir.mkdir(parents=True)
    chart_file = chart_dir / "chart.png"
    chart_file.write_bytes(b"png")
    registry = project_root / "notebooks" / ".signalpilot-analysis-registry.json"
    registry.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "request_id": "notion-test",
                        "notebook_path": notebook_path,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(project_sync, "PROJECTS_ROOT", tmp_path / "projects")

    assert (
        notion_analysis._chart_file_from_project_registries(
            "notion-test", "chart.png"
        )
        == chart_file
    )


def test_writes_virtual_file_image_outputs_as_chart_artifacts(
    tmp_path, monkeypatch
) -> None:
    app_state = _app_state(tmp_path)
    record = _record()
    image_bytes = b"fake-png"

    def read_virtual_file(filename: str, byte_length: int) -> bytes:
        assert filename == "chart.png"
        assert byte_length == len(image_bytes)
        return image_bytes

    monkeypatch.setattr(
        notion_analysis, "read_virtual_file", read_virtual_file
    )

    charts = notion_analysis._write_image_chart_artifacts(
        app_state,
        record,
        [
            (
                "cell/1",
                {
                    "text/html": (
                        f'<img src="./@file/{len(image_bytes)}-chart.png" '
                        'alt="Revenue trend" />'
                    )
                },
            )
        ],
    )

    assert len(charts) == 1
    assert charts[0].title == "Revenue trend"
    assert charts[0].url == (
        "/api/notion-analysis/chart/notion-test/"
        "notion-test-cell-1-image-1.png"
    )
    chart_path = (
        tmp_path
        / "public"
        / "signalpilot-notion-charts"
        / "notion-test-cell-1-image-1.png"
    )
    assert chart_path.read_bytes() == image_bytes


def test_writes_image_mime_data_url_outputs_as_chart_artifacts(tmp_path) -> None:
    app_state = _app_state(tmp_path)
    record = _record()
    image_bytes = b"another-fake-png"
    data_url = (
        "data:image/png;base64,"
        + base64.b64encode(image_bytes).decode("ascii")
    )

    charts = notion_analysis._write_image_chart_artifacts(
        app_state,
        record,
        [("cell-2", {"image/png": data_url})],
    )

    assert len(charts) == 1
    assert charts[0].url == (
        "/api/notion-analysis/chart/notion-test/"
        "notion-test-cell-2-image-1.png"
    )
    chart_path = (
        tmp_path
        / "public"
        / "signalpilot-notion-charts"
        / "notion-test-cell-2-image-1.png"
    )
    assert chart_path.read_bytes() == image_bytes


def test_writes_sp_mimebundle_image_outputs_as_chart_artifacts(tmp_path) -> None:
    app_state = _app_state(tmp_path)
    record = _record()
    image_bytes = b"mimebundle-png"
    data_url = (
        "data:image/png;base64,"
        + base64.b64encode(image_bytes).decode("ascii")
    )

    charts = notion_analysis._write_image_chart_artifacts(
        app_state,
        record,
        [
            (
                "matplotlib-cell",
                {
                    "application/vnd.sp+mimebundle": json.dumps(
                        {
                            "image/png": data_url,
                            "__metadata__": {"image/png": {"width": 900}},
                        }
                    )
                },
            )
        ],
    )

    assert len(charts) == 1
    assert charts[0].url == (
        "/api/notion-analysis/chart/notion-test/"
        "notion-test-matplotlib-cell-image-1.png"
    )
    chart_path = (
        tmp_path
        / "public"
        / "signalpilot-notion-charts"
        / "notion-test-matplotlib-cell-image-1.png"
    )
    assert chart_path.read_bytes() == image_bytes


def test_ensure_notion_chart_artifacts_fills_second_page_chart_from_result_table(
    tmp_path,
) -> None:
    app_state = _app_state(tmp_path)
    record = _record()
    chart_dir = tmp_path / "public" / "signalpilot-notion-charts"
    chart_dir.mkdir(parents=True)
    (chart_dir / "provided.png").write_bytes(b"provided-png")
    record.result = notion_analysis.AnalysisResult(
        final_answer=(
            "| Company | Composite Score | Growth |\n"
            "|---------|-----------------|--------|\n"
            "| MapleCloud | 82 | 12% |\n"
            "| Northstar | 71 | 8% |\n"
        ),
        notion_charts=[
            notion_analysis.AnalysisChart(
                title="Provided revenue trend",
                url="/api/notion-analysis/chart/notion-test/provided.png",
                caption="Provided revenue trend",
                alt_text="Provided revenue trend",
                include_in_comment=True,
                include_on_page=True,
            )
        ],
    )

    notion_analysis._ensure_notion_chart_artifacts(app_state, record)

    assert record.result.notion_charts is not None
    assert [chart.title for chart in record.result.notion_charts] == [
        "Provided revenue trend",
        "Operating momentum composite ranking",
    ]
    assert all(chart.include_on_page for chart in record.result.notion_charts)
