from __future__ import annotations

import importlib
import json
import sys
from types import SimpleNamespace

import pytest

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
        session_id="session-notion-test",
        notebook_path="analysis.py",
        trail_url="http://localhost/projects?file=analysis.py",
        status="Done",
        headline="Analysis",
        source_url="notion://comment",
        created_at="2026-06-18T00:00:00Z",
        output_mode="deliverable",
        data_snapshots=[],
    )


@pytest.fixture(autouse=True)
def _clear_records():
    notion_analysis._records_by_request_id.clear()
    notion_analysis._records_by_discussion_id.clear()
    yield
    notion_analysis._records_by_request_id.clear()
    notion_analysis._records_by_discussion_id.clear()


def test_save_data_snapshot_writes_json_and_status_metadata(tmp_path) -> None:
    app_state = _app_state(tmp_path)
    record = _record()
    notion_analysis._records_by_request_id[record.request_id] = record

    saved = notion_analysis.save_data_snapshot_for_session(
        app_state,
        session_id=record.session_id,
        name="Revenue by month",
        description="Monthly revenue aggregate",
        columns=["month", "revenue"],
        rows=[{"month": "2026-01", "revenue": 100}],
    )

    assert saved["rowCount"] == 1
    snapshot_path = (
        tmp_path
        / "public"
        / "signalpilot-notion-snapshots"
        / record.request_id
        / saved["filename"]
    )
    assert json.loads(snapshot_path.read_text(encoding="utf-8")) == {
        "name": "Revenue by month",
        "description": "Monthly revenue aggregate",
        "columns": ["month", "revenue"],
        "rows": [{"month": "2026-01", "revenue": 100}],
    }

    record.result = notion_analysis.AnalysisResult(summary="Done")
    response = notion_analysis._record_response(record)

    assert response["outputMode"] == "deliverable"
    assert response["dataSnapshots"] == [saved]


def test_save_data_snapshot_enforces_count_and_size(
    tmp_path, monkeypatch
) -> None:
    app_state = _app_state(tmp_path)
    record = _record()
    notion_analysis._records_by_request_id[record.request_id] = record

    for index in range(notion_analysis.MAX_DATA_SNAPSHOTS):
        notion_analysis.save_data_snapshot_for_session(
            app_state,
            session_id=record.session_id,
            name=f"Snapshot {index}",
            description="ok",
            columns=["value"],
            rows=[{"value": index}],
        )

    with pytest.raises(ValueError, match="At most"):
        notion_analysis.save_data_snapshot_for_session(
            app_state,
            session_id=record.session_id,
            name="Too many",
            description="no",
            columns=["value"],
            rows=[{"value": 6}],
        )

    monkeypatch.setenv("SIGNALPILOT_SNAPSHOT_MAX_BYTES", "1024")
    with pytest.raises(ValueError, match="limit"):
        notion_analysis.save_data_snapshot_for_session(
            app_state,
            session_id=record.session_id,
            name="Snapshot 0",
            description="oversize",
            columns=["value"],
            rows=[{"value": "x" * 2000}],
        )


def test_snapshot_project_registry_fallback_rejects_path_traversal(
    tmp_path, monkeypatch
) -> None:
    from signalpilot._server.files import project_sync

    project_root = tmp_path / "projects" / "project-1" / "repo"
    snapshot_dir = (
        project_root
        / "notebooks"
        / "notion"
        / "public"
        / "signalpilot-notion-snapshots"
        / "notion-test"
    )
    snapshot_dir.mkdir(parents=True)
    (snapshot_dir / "snapshot.json").write_text("{}", encoding="utf-8")
    registry = (
        project_root / "notebooks" / ".signalpilot-analysis-registry.json"
    )
    registry.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "request_id": "notion-test",
                        "notebook_path": "notebooks/notion/analysis.py",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(project_sync, "PROJECTS_ROOT", tmp_path / "projects")

    assert (
        notion_analysis._snapshot_file_from_project_registries(
            "notion-test", "snapshot.json"
        )
        == snapshot_dir / "snapshot.json"
    )
    assert (
        notion_analysis._snapshot_file_from_project_registries(
            "notion-test", "../secret.json"
        )
        is None
    )
