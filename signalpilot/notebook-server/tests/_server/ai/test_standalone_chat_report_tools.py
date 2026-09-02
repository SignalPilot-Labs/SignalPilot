"""Report catalog, proposal, and publication rules for standalone chat tools."""

from __future__ import annotations

import json
from typing import Any

import pytest
from mcp.types import (
    CallToolRequest,
    CallToolRequestParams,
)

from signalpilot._server.ai.standalone_chat_tools import (
    StandaloneArtifactCollector,
    build_standalone_chat_mcp_server,
)


@pytest.mark.asyncio
async def test_report_tools_require_a_complete_catalog_scan_and_one_valid_proposal():
    collector = StandaloneArtifactCollector(
        artifacts=[
            {
                "kind": "table",
                "filename": "revenue.csv",
                "payload": {
                    "columns": [{"name": "revenue"}],
                    "rows": [{"revenue": 100}],
                    "completeness": "complete",
                    "truncated": False,
                },
            }
        ]
    )

    async def load_catalog(cursor: str | None) -> dict[str, Any]:
        return {
            "items": [],
            "next_cursor": "page-2" if cursor is None else None,
            "catalog_revision": "revision-a",
            "total_reports": 51,
            "proactive_creation_allowed": True,
        }

    config = build_standalone_chat_mcp_server(
        collector,
        report_catalog_loader=load_catalog,
    )
    server = config["instance"]
    await server.request_handlers[CallToolRequest](
        CallToolRequest(
            params=CallToolRequestParams(
                name="list_saved_report_catalog",
                arguments={},
            )
        )
    )
    incomplete = await server.request_handlers[CallToolRequest](
        CallToolRequest(
            params=CallToolRequestParams(
                name="propose_report_action",
                arguments={
                    "action": "create",
                    "artifact_kind": "table",
                    "artifact_filename": "revenue.csv",
                    "title": "Revenue",
                    "reason": "No semantic match exists.",
                },
            )
        )
    )
    assert incomplete.root.isError is True
    assert "every saved report catalog page" in incomplete.root.content[0].text

    final_page = await server.request_handlers[CallToolRequest](
        CallToolRequest(
            params=CallToolRequestParams(
                name="list_saved_report_catalog",
                arguments={"cursor": "page-2"},
            )
        )
    )
    assert final_page.root.isError is False
    proposed = await server.request_handlers[CallToolRequest](
        CallToolRequest(
            params=CallToolRequestParams(
                name="propose_report_action",
                arguments={
                    "action": "create",
                    "artifact_kind": "table",
                    "artifact_filename": "revenue.csv",
                    "title": "Revenue",
                    "reason": "No semantic match exists.",
                },
            )
        )
    )
    assert proposed.root.isError is False
    assert collector.report_proposal == {
        "action": "create",
        "artifact_kind": "table",
        "artifact_filename": "revenue.csv",
        "title": "Revenue",
        "reason": "No semantic match exists.",
        "existing_report_id": None,
        "catalog_revision": "revision-a",
        "catalog_scan_complete": True,
        "proactive_creation_allowed": True,
        "loaded_report_ids": [],
        "attached_report_id": None,
    }
    repeated = await server.request_handlers[CallToolRequest](
        CallToolRequest(
            params=CallToolRequestParams(
                name="propose_report_action",
                arguments={
                    "action": "create",
                    "artifact_kind": "table",
                    "artifact_filename": "revenue.csv",
                    "title": "Revenue copy",
                    "reason": "Try again.",
                },
            )
        )
    )
    assert repeated.root.isError is True
    assert "Only one report action outcome" in repeated.root.content[0].text


@pytest.mark.asyncio
async def test_complete_publication_requires_a_catalog_backed_report_outcome():
    collector = StandaloneArtifactCollector()

    async def load_catalog(_cursor: str | None) -> dict[str, Any]:
        return {
            "items": [],
            "next_cursor": None,
            "catalog_revision": "revision-empty",
            "total_reports": 0,
            "proactive_creation_allowed": True,
        }

    server = build_standalone_chat_mcp_server(
        collector,
        report_catalog_loader=load_catalog,
    )["instance"]
    published = await server.request_handlers[CallToolRequest](
        CallToolRequest(
            params=CallToolRequestParams(
                name="publish_report",
                arguments={
                    "filename": "revenue.html",
                    "html": "<html><body>Revenue</body></html>",
                },
            )
        )
    )
    publication = json.loads(published.root.content[0].text)
    assert publication["published"] is True
    assert publication["next_required_action"].startswith(
        "REQUIRED BEFORE YOUR FINAL ANSWER"
    )

    unscanned = await server.request_handlers[CallToolRequest](
        CallToolRequest(
            params=CallToolRequestParams(
                name="propose_report_action",
                arguments={
                    "action": "no_suggestion",
                    "artifact_kind": "report",
                    "artifact_filename": "revenue.html",
                    "title": "Revenue",
                    "reason": "This is a one-off diagnostic.",
                },
            )
        )
    )
    assert unscanned.root.isError is True
    assert "every saved report catalog page" in unscanned.root.content[0].text

    await server.request_handlers[CallToolRequest](
        CallToolRequest(
            params=CallToolRequestParams(
                name="list_saved_report_catalog",
                arguments={},
            )
        )
    )
    recorded = await server.request_handlers[CallToolRequest](
        CallToolRequest(
            params=CallToolRequestParams(
                name="propose_report_action",
                arguments={
                    "action": "no_suggestion",
                    "artifact_kind": "report",
                    "artifact_filename": "revenue.html",
                    "title": "Revenue",
                    "reason": "This is a one-off diagnostic.",
                },
            )
        )
    )

    assert recorded.root.isError is False
    assert json.loads(recorded.root.content[0].text) == {
        "recorded": True,
        "proposed": False,
        "action": "no_suggestion",
    }
    assert collector.report_proposal is None
    assert collector.report_action_outcome == {
        "action": "no_suggestion",
        "artifact_kind": "report",
        "artifact_filename": "revenue.html",
        "title": "Revenue",
        "reason": "This is a one-off diagnostic.",
        "existing_report_id": None,
        "catalog_revision": "revision-empty",
        "catalog_scan_complete": True,
        "proactive_creation_allowed": True,
        "loaded_report_ids": [],
        "attached_report_id": None,
    }


@pytest.mark.asyncio
async def test_report_creation_fails_closed_above_500_catalog_entries():
    collector = StandaloneArtifactCollector(
        artifacts=[
            {
                "kind": "table",
                "filename": "revenue.csv",
                "payload": {
                    "columns": [{"name": "revenue"}],
                    "rows": [{"revenue": 100}],
                    "completeness": "complete",
                    "truncated": False,
                },
            }
        ]
    )

    async def load_catalog(_cursor: str | None) -> dict[str, Any]:
        return {
            "items": [],
            "next_cursor": None,
            "catalog_revision": "revision-large",
            "total_reports": 501,
            "proactive_creation_allowed": False,
        }

    server = build_standalone_chat_mcp_server(
        collector,
        report_catalog_loader=load_catalog,
    )["instance"]
    scanned = await server.request_handlers[CallToolRequest](
        CallToolRequest(
            params=CallToolRequestParams(
                name="list_saved_report_catalog",
                arguments={},
            )
        )
    )
    assert scanned.root.isError is False

    blocked = await server.request_handlers[CallToolRequest](
        CallToolRequest(
            params=CallToolRequestParams(
                name="propose_report_action",
                arguments={
                    "action": "create",
                    "artifact_kind": "table",
                    "artifact_filename": "revenue.csv",
                    "title": "Revenue",
                    "reason": "No semantic match exists.",
                },
            )
        )
    )
    assert blocked.root.isError is True
    assert (
        "Proactive report creation is unavailable"
        in blocked.root.content[0].text
    )
    assert collector.report_proposal is None


@pytest.mark.asyncio
async def test_report_update_requires_loaded_context_unless_the_report_is_attached():
    artifact = {
        "kind": "chart",
        "filename": "revenue.png",
        "payload": {
            "source": {"completeness": "complete", "truncated": False},
        },
    }

    async def load_context(report_id: str) -> dict[str, Any]:
        return {"report_id": report_id, "title": "Revenue"}

    async def load_catalog(_cursor: str | None) -> dict[str, Any]:
        return {
            "items": [{"report_id": "report-a", "title": "Revenue"}],
            "next_cursor": None,
            "catalog_revision": "revision-a",
            "total_reports": 1,
            "proactive_creation_allowed": True,
        }

    collector = StandaloneArtifactCollector(artifacts=[artifact])
    server = build_standalone_chat_mcp_server(
        collector,
        report_context_loader=load_context,
        report_catalog_loader=load_catalog,
    )["instance"]
    blocked = await server.request_handlers[CallToolRequest](
        CallToolRequest(
            params=CallToolRequestParams(
                name="propose_report_action",
                arguments={
                    "action": "update",
                    "artifact_kind": "chart",
                    "artifact_filename": "revenue.png",
                    "title": "Revenue",
                    "reason": "Only the date range changed.",
                    "existing_report_id": "report-a",
                },
            )
        )
    )
    assert blocked.root.isError is True
    await server.request_handlers[CallToolRequest](
        CallToolRequest(
            params=CallToolRequestParams(
                name="list_saved_report_catalog",
                arguments={},
            )
        )
    )
    await server.request_handlers[CallToolRequest](
        CallToolRequest(
            params=CallToolRequestParams(
                name="load_report_context",
                arguments={"report_id": "report-a"},
            )
        )
    )
    accepted = await server.request_handlers[CallToolRequest](
        CallToolRequest(
            params=CallToolRequestParams(
                name="propose_report_action",
                arguments={
                    "action": "update",
                    "artifact_kind": "chart",
                    "artifact_filename": "revenue.png",
                    "title": "Revenue",
                    "reason": "Only the date range changed.",
                    "existing_report_id": "report-a",
                },
            )
        )
    )
    assert accepted.root.isError is False
