from __future__ import annotations

import asyncio
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


def _body() -> notion_analysis.StartNotionAnalysisRequest:
    return notion_analysis.StartNotionAnalysisRequest(
        discussion_id="slack:T:C:123",
        source_url="https://slack.test/archives/C/p123",
        headline="Analyze dev DB",
        prompt="can you do an analysis of our dev db?",
        created_at="2026-06-19T00:00:00Z",
        previous_messages=["prior context"],
    )


def _record() -> notion_analysis.AnalysisRecord:
    return notion_analysis.AnalysisRecord(
        request_id="notion-test",
        discussion_id="slack:T:C:123",
        session_id="session-notion-test",
        notebook_path="signalpilot-notion-analyses/analyze-dev-db.py",
        trail_url="https://app.test/projects?file=analysis.py",
        status="New",
        headline="Analyze dev DB",
        source_url="https://slack.test/archives/C/p123",
        created_at="2026-06-19T00:00:00Z",
    )


def test_notebook_template_uses_compact_three_cell_scaffold() -> None:
    template = notion_analysis._notebook_template(_body())

    assert template.count("@app.cell") == 3
    assert template.count("@app.cell(hide_code=True)") == 3
    assert "# SignalPilot analysis" in template
    assert "AI generated title" not in template
    assert "**Source request:** https://slack.test/archives/C/p123" in template
    assert "**Source prompt:**" in template
    assert "**Requester prompt:**" not in template
    assert "can you do an analysis of our dev db?" in template
    assert "request_headline =" not in template
    assert "source_url =" not in template
    assert "user_prompt =" not in template
    assert "previous_messages =" not in template
    assert "request_title =" not in template
    assert "## Executive Summary and Explorations" in template
    assert "## Analysis steps" in template
    assert "## Scouting and context notes" not in template
    assert "## Setup and connection selection" not in template
    assert "## Data discovery" not in template
    assert "## Charts and visual evidence" not in template
    assert "## Evidence Trace" not in template


def test_analysis_registry_omits_latest_commit_sha(tmp_path, monkeypatch) -> None:
    record = _record()
    record.latest_commit_sha = "abc123"
    registry_path = tmp_path / "notebooks" / ".signalpilot-analysis-registry.json"
    registry_path.parent.mkdir(parents=True)
    monkeypatch.setattr(notion_analysis, "_registry_path", lambda _app_state: registry_path)

    old_records = dict(notion_analysis._records_by_request_id)
    try:
        notion_analysis._records_by_request_id.clear()
        notion_analysis._records_by_request_id[record.request_id] = record

        notion_analysis._save_registry(object())

        raw = json.loads(registry_path.read_text(encoding="utf-8"))
        assert raw["records"][0]["request_id"] == "notion-test"
        assert "latest_commit_sha" not in raw["records"][0]
    finally:
        notion_analysis._records_by_request_id.clear()
        notion_analysis._records_by_request_id.update(old_records)


def test_project_root_uses_existing_project_checkout(tmp_path, monkeypatch) -> None:
    from signalpilot._server.files import project_sync

    project_root = tmp_path / "projects" / "project-1"
    (project_root / ".git").mkdir(parents=True)
    app_state = SimpleNamespace(
        request=SimpleNamespace(
            headers={
                "x-gateway-project-id": "project-1",
                "x-gateway-branch-id": "analysis/slack/test",
            }
        ),
        session_manager=SimpleNamespace(
            workspace=SimpleNamespace(directory=str(tmp_path / "workspace"))
        ),
    )

    monkeypatch.setattr(project_sync, "local_project_dir", lambda _project_id, _branch="": project_root)
    monkeypatch.setattr(
        project_sync,
        "sync_down",
        lambda *_args, **_kwargs: pytest.fail("sync_down should not run for existing checkout"),
    )

    assert notion_analysis._project_root(app_state) == project_root


def test_project_root_syncs_project_checkout_before_workspace_fallback(tmp_path, monkeypatch) -> None:
    from signalpilot._server.files import project_sync

    project_root = tmp_path / "projects" / "project-1"
    app_state = SimpleNamespace(
        request=SimpleNamespace(
            headers={
                "x-gateway-project-id": "project-1",
                "x-gateway-branch-id": "analysis/slack/test",
            }
        ),
        session_manager=SimpleNamespace(
            workspace=SimpleNamespace(directory=str(tmp_path / "workspace"))
        ),
    )

    def sync_down(_project_id: str, _branch: str) -> dict[str, str]:
        (project_root / ".git").mkdir(parents=True)
        return {"local_dir": str(project_root)}

    monkeypatch.setattr(project_sync, "local_project_dir", lambda _project_id, _branch="": project_root)
    monkeypatch.setattr(project_sync, "sync_down", sync_down)

    assert notion_analysis._project_root(app_state) == project_root


def test_project_root_does_not_fallback_to_workspace_when_project_sync_fails(tmp_path, monkeypatch) -> None:
    from signalpilot._server.files import project_sync

    project_root = tmp_path / "projects" / "project-1"
    app_state = SimpleNamespace(
        request=SimpleNamespace(
            headers={
                "x-gateway-project-id": "project-1",
                "x-gateway-branch-id": "analysis/slack/test",
            }
        ),
        session_manager=SimpleNamespace(
            workspace=SimpleNamespace(directory=str(tmp_path / "workspace"))
        ),
    )

    monkeypatch.setattr(project_sync, "local_project_dir", lambda _project_id, _branch="": project_root)
    monkeypatch.setattr(project_sync, "sync_down", lambda _project_id, _branch: {"error": "clone failed"})

    with pytest.raises(RuntimeError, match="Could not resolve project root"):
        notion_analysis._project_root(app_state)


def test_analysis_agent_runs_from_project_root(tmp_path, monkeypatch) -> None:
    from signalpilot._server.ai.claude_agent import AgentEvent
    from signalpilot._server.ai import chat_store
    from signalpilot._types.ids import SessionId

    class FakeStore:
        async def upsert_thread(self, thread) -> None:
            del thread

        async def clear_events(self, thread_id: str) -> None:
            del thread_id

        async def append_event(self, thread_id: str, event_data: dict) -> int:
            del thread_id, event_data
            return 0

    project_root = tmp_path / "projects" / "project-1"
    project_root.mkdir(parents=True)
    app_state = SimpleNamespace(
        request=SimpleNamespace(app=object(), headers={}),
        session_manager=SimpleNamespace(
            workspace=SimpleNamespace(directory=str(tmp_path / "workspace"))
        ),
    )
    record = _record()
    captured: dict[str, object] = {}

    async def fake_run_notebook_agent(**kwargs):
        captured.update(kwargs)
        yield AgentEvent(
            type="text",
            content=json.dumps(
                {
                    "summary": "Done",
                    "confidenceScore": 0.9,
                    "finalAnswer": "Done",
                }
            ),
        )

    monkeypatch.setattr(notion_analysis, "_project_root", lambda _app_state: project_root)
    monkeypatch.setattr(notion_analysis, "_ensure_session", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(notion_analysis, "_save_registry", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        notion_analysis,
        "_persist_record_completion_artifacts",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(chat_store, "get_gateway_chat_trace_store", lambda: FakeStore())
    monkeypatch.setattr(
        "signalpilot._server.ai.claude_agent.run_notebook_agent",
        fake_run_notebook_agent,
    )

    asyncio.run(
        notion_analysis._run_analysis(
            app_state,
            record,
            _body(),
            new_chat=True,
        )
    )

    assert captured["session_id"] == SessionId(record.session_id)
    assert captured["cwd"] == str(project_root)


def test_analysis_prompt_requires_nearby_query_evidence_branches() -> None:
    prompt = notion_analysis._analysis_prompt(_record(), _body())

    assert "evidence-first" in prompt
    assert "analysis title based on the\n     user's request" in prompt
    assert "request-based title, Source request,\n     Source prompt" in prompt
    assert "not the raw user" in prompt
    assert "not the shortened `headline`" in prompt
    assert "markdown-only cell" in prompt
    assert "Do not add request metadata variables" in prompt
    assert "do not rename this heading" in prompt
    assert "`### Gotchas / Caveats`" in prompt
    assert "`### Confidence Score: X`" in prompt
    assert "assumptions used" in prompt
    assert "exclusions/not-included items" in prompt
    assert "known gaps" in prompt
    assert "sensitivity" in prompt
    assert "source tables, filters, validation checks" in prompt
    assert "issues\n       that would lower or raise confidence" in prompt
    assert "repeated finding branch" in prompt
    assert "`### Finding: ...`" in prompt
    assert "1-3 sentences explaining" in prompt
    assert "visible query cell" in prompt
    assert "visible data preview cell" in prompt
    assert "visible checks cell" in prompt
    assert "Do not write generic \"what I did\" sections" in prompt
    assert "Do not separate a finding from" in prompt
    assert "Example branch shape to imitate" in prompt
    assert "Completed GBP transfer revenue was concentrated in FX margin" in prompt
    assert "q1_gbp_revenue_df = pd.DataFrame(db.query" in prompt
    assert "q1_gbp_revenue_df.head(10)" in prompt
    assert "monthly_revenue_chart" in prompt
    assert "head of\n     the joined table/query result" in prompt
    assert "not just a branch list" in prompt
    assert "finding explanation, exact query, data head/preview" in prompt
    assert "\"Analysis steps\"" in prompt
    assert "\"Evidence Trace\"" not in prompt
    assert "Mermaid" not in prompt
    assert "top-line result" not in prompt
    assert "Confidence methodology/rationale" in prompt
    assert "Queries must not be buried" in prompt
    assert "Previous discussion messages:" in prompt
    assert "Previous Notion discussion messages:" not in prompt
