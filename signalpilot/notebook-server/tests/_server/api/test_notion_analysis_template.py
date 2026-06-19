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
    assert "**Source request:** {source_url}" in template
    assert "return previous_messages, request_headline, source_url, sp, user_prompt" in template
    assert "## Executive Summary and Explorations" in template
    assert "## Evidence Trace" in template
    assert "## Scouting and context notes" not in template
    assert "## Setup and connection selection" not in template
    assert "## Data discovery" not in template
    assert "## Charts and visual evidence" not in template


def test_analysis_prompt_requires_nearby_query_evidence_branches() -> None:
    prompt = notion_analysis._analysis_prompt(_record(), _body())

    assert "evidence-first" in prompt
    assert "visible SQL/query code cell" in prompt
    assert "df.head()" in prompt
    assert "validation checks" in prompt
    assert "plain markdown trace" in prompt
    assert "Mermaid" not in prompt
    assert "Queries must not be buried" in prompt
    assert "Previous discussion messages:" in prompt
    assert "Previous Notion discussion messages:" not in prompt
