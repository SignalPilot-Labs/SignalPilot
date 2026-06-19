from __future__ import annotations

import importlib
import sys

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
    assert "repeated finding branch" in prompt
    assert "`### Finding: ...`" in prompt
    assert "1-3 sentences explaining" in prompt
    assert "visible query cell" in prompt
    assert "visible data preview cell" in prompt
    assert "visible checks cell" in prompt
    assert "Do not write generic \"what I did\" sections" in prompt
    assert "Do not separate a finding from" in prompt
    assert "head of\n     the joined table/query result" in prompt
    assert "not just a branch list" in prompt
    assert "finding explanation, exact query, data head/preview" in prompt
    assert "\"Analysis steps\"" in prompt
    assert "\"Evidence Trace\"" not in prompt
    assert "Mermaid" not in prompt
    assert "top-line result" not in prompt
    assert "Queries must not be buried" in prompt
    assert "Previous discussion messages:" in prompt
    assert "Previous Notion discussion messages:" not in prompt
