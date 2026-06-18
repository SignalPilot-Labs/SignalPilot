from __future__ import annotations

import base64
import importlib
import sys
from types import SimpleNamespace

_stubbed_signalpilot = sys.modules.get("signalpilot")
if getattr(_stubbed_signalpilot, "__spec__", None) is None:
    del sys.modules["signalpilot"]

notion_analysis = importlib.import_module(
    "signalpilot._server.api.endpoints.notion_analysis"
)


def _app_state(tmp_path):
    return SimpleNamespace(
        session_manager=SimpleNamespace(
            workspace=SimpleNamespace(directory=str(tmp_path))
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
