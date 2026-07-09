from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.analysis_delivery import DeliveryPacket, DeliveryResult, HtmlDeliverableResult, WorkerPlan, WorkerProgress
from gateway.db.models import GatewayBase, NotionDeliverable, NotionInstallation, NotionInstallationConfig
from gateway.notebooks.session_service import NotebookRuntime
from gateway.notion import analysis as notion_analysis
from gateway.notion import client as notion_client
from gateway.notion.webhooks import RoutedNotionInstallation
from gateway.store import notion as notion_store


def _rich_text_content(rich_text: list[dict]) -> str:
    return "".join(part.get("text", {}).get("content", "") for part in rich_text)


def _block_rich_text(block: dict) -> list[dict]:
    block_type = block["type"]
    rich_text = list(block.get(block_type, {}).get("rich_text", []))
    for child in block.get(block_type, {}).get("children", []):
        rich_text.extend(_block_rich_text(child))
    if block_type == "table":
        for row in block["table"].get("children", []):
            for cell in row.get("table_row", {}).get("cells", []):
                rich_text.extend(cell)
    return rich_text


def _routed_installation_for_followup() -> RoutedNotionInstallation:
    install = NotionInstallation(
        id="install-1",
        org_id="org-1",
        user_id="user-1",
        workspace_id="workspace-1",
        bot_id="bot-1",
        access_token_enc=b"encrypted",
        status="active",
    )
    config = NotionInstallationConfig(
        installation_id="install-1",
        parent_page_id=None,
        trigger_page_id="trigger-1",
        requests_data_source_id="ds-1",
        requests_database_page_id="db-1",
        enabled=True,
        default_project_id="project-1",
        default_branch="main",
    )
    return RoutedNotionInstallation(installation=install, config=config, access_token="token-1")


def _followup_payload(parent_block_id: str = "embed-block-1") -> dict:
    return {
        "id": "event-1",
        "entity": {"id": "comment-1"},
        "data": {"page_id": "page-1", "parent": {"id": parent_block_id}},
        "authors": [{"id": "user-1", "type": "person"}],
    }


@pytest.mark.asyncio
async def test_poll_analysis_uses_project_route_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []
    runtime = NotebookRuntime(
        session_id="session-1",
        internal_base_url="http://notebook.internal",
        public_base_url="https://app.test/notebook/session-1",
    )
    route = notion_analysis.AnalysisRoute(
        source="slack",
        request_id="slack-req-1",
        project_id="project-1",
        branch="analysis/slack/slack-req-1-hi",
        default_branch="main",
        analysis_user_id="analysis:slack:slack-req-1",
    )

    async def call_notebook(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return {"status": "Done"}

    monkeypatch.setattr(notion_analysis, "_call_notebook", call_notebook)

    result = await notion_analysis._poll_analysis(
        "slack-req-1",
        runtime,
        "org-1",
        "user-1",
        route,
    )

    assert result == {"status": "Done"}
    assert calls[0]["args"][:4] == (
        runtime,
        "/api/notion-analysis/status/slack-req-1",
        "org-1",
        "user-1",
    )
    assert calls[0]["args"][4] == {
        "headers": {
            "X-Gateway-Project-Id": "project-1",
            "X-Gateway-Branch-Id": "analysis/slack/slack-req-1-hi",
        }
    }


@pytest.mark.asyncio
async def test_start_comment_is_posted_before_notebook_call_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    install = NotionInstallation(
        id="install-1",
        org_id="org-1",
        user_id="user-1",
        workspace_id="workspace-1",
        bot_id="bot-1",
        access_token_enc=b"encrypted",
        status="active",
    )
    config = NotionInstallationConfig(
        installation_id="install-1",
        parent_page_id=None,
        trigger_page_id="trigger-1",
        requests_data_source_id="ds-1",
        requests_database_page_id="db-1",
        enabled=True,
    )
    routed = RoutedNotionInstallation(installation=install, config=config, access_token="token-1")
    payload = {
        "entity": {"id": "comment-1"},
        "data": {"page_id": "page-1"},
        "authors": [{"id": "user-1", "type": "person"}],
    }
    comment = {"id": "comment-1", "discussion_id": "discussion-1", "rich_text": []}

    async def list_comments(*args, **kwargs):
        return [comment]

    async def query_request_page_by_source(*args, **kwargs):
        return None

    async def create_request_page(*args, **kwargs):
        return {"id": "request-page-1", "url": "https://notion.test/request-page-1"}

    async def update_page_properties(*args, **kwargs):
        calls.append("update_page_properties")

    async def append_page_blocks(*args, **kwargs):
        calls.append("append_page_blocks")

    async def create_comment(*args, **kwargs):
        text = _rich_text_content(kwargs["rich_text"])
        calls.append(f"comment:{text}")

    async def call_notebook(*args, **kwargs):
        calls.append("call_notebook")
        raise RuntimeError("notebook unavailable")

    async def resolve_route(*args, **kwargs):
        return notion_analysis.AnalysisRoute(
            source="notion",
            request_id="notion-req-1",
            project_id="project-1",
            branch="analysis/notion/notion-req-1-hello",
            default_branch="main",
            analysis_user_id="analysis:notion:notion-req-1",
        )

    async def ensure_runtime(*args, **kwargs):
        calls.append("ensure_runtime")
        return NotebookRuntime(
            session_id="session-1",
            internal_base_url="http://10.0.0.5:2718/notebook/session-1",
            public_base_url="https://app.test/notebook/session-1",
        )

    async def seed_trail(*args, **kwargs):
        calls.append("seed_trail")

    monkeypatch.setattr(notion_client, "list_comments", list_comments)
    monkeypatch.setattr(notion_client, "query_request_page_by_source", query_request_page_by_source)
    monkeypatch.setattr(notion_client, "create_request_page", create_request_page)
    monkeypatch.setattr(notion_client, "update_page_properties", update_page_properties)
    monkeypatch.setattr(notion_client, "append_page_blocks", append_page_blocks)
    monkeypatch.setattr(notion_client, "create_comment", create_comment)
    monkeypatch.setattr(notion_client, "is_bot_comment", lambda _comment: False)
    monkeypatch.setattr(notion_client, "comment_has_page_mention", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(notion_client, "extract_comment_text", lambda _comment: "Analyze revenue by month")
    monkeypatch.setattr(notion_analysis, "resolve_configured_analysis_route", resolve_route)
    monkeypatch.setattr(notion_analysis, "ensure_analysis_notebook_session", ensure_runtime)
    monkeypatch.setattr(notion_analysis, "upsert_analysis_trail_seed", seed_trail)
    monkeypatch.setattr(notion_analysis, "_call_notebook", call_notebook)

    with pytest.raises(RuntimeError, match="notebook unavailable"):
        await notion_analysis.process_routed_comment_event(routed, payload, db=MagicMock())

    start_comment_index = next(index for index, call in enumerate(calls) if call.startswith("comment:I'm on it"))
    notebook_index = calls.index("call_notebook")
    assert start_comment_index < notebook_index
    assert "https://notion.test/request-page-1" not in calls[start_comment_index]
    assert "request details" in calls[start_comment_index]


@pytest.mark.asyncio
async def test_missing_default_project_posts_setup_required_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    install = NotionInstallation(
        id="install-1",
        org_id="org-1",
        user_id="user-1",
        workspace_id="workspace-1",
        bot_id="bot-1",
        access_token_enc=b"encrypted",
        status="active",
    )
    config = NotionInstallationConfig(
        installation_id="install-1",
        parent_page_id=None,
        trigger_page_id="trigger-1",
        requests_data_source_id="ds-1",
        requests_database_page_id="db-1",
        enabled=True,
    )
    routed = RoutedNotionInstallation(installation=install, config=config, access_token="token-1")
    payload = {
        "entity": {"id": "comment-1"},
        "data": {"page_id": "page-1"},
        "authors": [{"id": "user-1", "type": "person"}],
    }
    comment = {"id": "comment-1", "discussion_id": "discussion-1", "rich_text": []}

    async def list_comments(*args, **kwargs):
        return [comment]

    async def query_request_page_by_source(*args, **kwargs):
        return None

    async def create_request_page(*args, **kwargs):
        return {"id": "request-page-1", "url": "https://notion.test/request-page-1"}

    async def update_page_properties(*args, **kwargs):
        calls.append("update_page_properties")

    async def append_page_blocks(*args, **kwargs):
        calls.append("append_page_blocks")

    async def create_comment(*args, **kwargs):
        calls.append(f"comment:{_rich_text_content(kwargs['rich_text'])}")

    async def call_notebook(*args, **kwargs):
        calls.append("call_notebook")

    monkeypatch.setattr(notion_client, "list_comments", list_comments)
    monkeypatch.setattr(notion_client, "query_request_page_by_source", query_request_page_by_source)
    monkeypatch.setattr(notion_client, "create_request_page", create_request_page)
    monkeypatch.setattr(notion_client, "update_page_properties", update_page_properties)
    monkeypatch.setattr(notion_client, "append_page_blocks", append_page_blocks)
    monkeypatch.setattr(notion_client, "create_comment", create_comment)
    monkeypatch.setattr(notion_client, "is_bot_comment", lambda _comment: False)
    monkeypatch.setattr(notion_client, "comment_has_page_mention", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(notion_client, "extract_comment_text", lambda _comment: "Analyze revenue by month")
    monkeypatch.setattr(notion_analysis, "_call_notebook", call_notebook)

    result = await notion_analysis.process_routed_comment_event(routed, payload, db=MagicMock())

    assert result.status == "processed"
    assert "call_notebook" not in calls
    assert any("default dbt project" in call for call in calls if call.startswith("comment:"))


@pytest.mark.asyncio
async def test_notion_preflight_greeting_posts_direct_reply_without_request_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    install = NotionInstallation(
        id="install-1",
        org_id="org-1",
        user_id="user-1",
        workspace_id="workspace-1",
        bot_id="bot-1",
        access_token_enc=b"encrypted",
        status="active",
    )
    config = NotionInstallationConfig(
        installation_id="install-1",
        parent_page_id=None,
        trigger_page_id="trigger-1",
        requests_data_source_id="ds-1",
        requests_database_page_id="db-1",
        enabled=True,
    )
    routed = RoutedNotionInstallation(installation=install, config=config, access_token="token-1")
    payload = {"entity": {"id": "comment-1"}, "data": {"page_id": "page-1"}}
    comment = {"id": "comment-1", "discussion_id": "discussion-1", "rich_text": []}

    async def list_comments(*args, **kwargs):
        return [comment]

    async def create_comment(*args, **kwargs):
        calls.append(f"comment:{_rich_text_content(kwargs['rich_text'])}")

    async def fail_create_request_page(*args, **kwargs):
        raise AssertionError("greeting should not create a request page")

    async def fail_call_notebook(*args, **kwargs):
        raise AssertionError("greeting should not call notebook")

    monkeypatch.setattr(notion_client, "list_comments", list_comments)
    monkeypatch.setattr(notion_client, "create_comment", create_comment)
    monkeypatch.setattr(notion_client, "create_request_page", fail_create_request_page)
    monkeypatch.setattr(notion_client, "is_bot_comment", lambda _comment: False)
    monkeypatch.setattr(notion_client, "comment_has_page_mention", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(notion_client, "extract_comment_text", lambda _comment: "hi")
    monkeypatch.setattr(notion_analysis, "_call_notebook", fail_call_notebook)

    result = await notion_analysis.process_routed_comment_event(routed, payload, db=MagicMock())

    assert result.status == "processed"
    assert calls == ["comment:Hi. Send me a specific data question and I will run it through SignalPilot."]


def test_start_comment_links_request_details_without_raw_url() -> None:
    url = "https://notion.test/request-page-1"

    rich_text = notion_analysis._start_comment_rich_text(url)

    assert url not in _rich_text_content(rich_text)
    assert any(part.get("text", {}).get("content") == "request details" for part in rich_text)
    assert any(part.get("text", {}).get("link", {}).get("url") == url for part in rich_text)


@pytest.mark.asyncio
async def test_notion_trace_progress_updates_comment_only(monkeypatch: pytest.MonkeyPatch) -> None:
    packet = DeliveryPacket(
        user_request="Analyze revenue",
        plan=WorkerPlan(steps=["Explore schema", "Analyze financials", "Write answer"]),
        latest_progress=WorkerProgress(
            current_step="Analyze financials",
            completed_steps=["Explore schema"],
            status="running governed queries",
        ),
    )
    calls: dict[str, str | dict] = {}

    async def load_delivery_packet(*args, **kwargs):
        return packet

    async def update_page_properties(*_args, **_kwargs):
        calls["properties"] = "unexpected"

    async def update_comment(_token, _comment_id, *, rich_text):
        calls["comment"] = _rich_text_content(rich_text)

    monkeypatch.setattr(notion_analysis, "load_delivery_packet", load_delivery_packet)
    monkeypatch.setattr(notion_client, "update_page_properties", update_page_properties)
    monkeypatch.setattr(notion_client, "update_comment", update_comment)

    reporter = notion_analysis._NotionTraceProgressReporter(
        token="token-1",
        request_page_url="https://notion.test/request-page-1",
        progress_comment_id="comment-1",
        db=MagicMock(),
        org_id="org-1",
        user_id="user-1",
        thread_id="session-notion-1",
        user_request="Analyze revenue",
    )

    await reporter.tick({})

    assert "properties" not in calls
    comment_text = str(calls["comment"])
    assert comment_text.startswith("I'm on it and will post the answer back soon.")
    assert "- [x] Explore schema" in comment_text
    assert "- [ ] Analyze financials (current)" in comment_text
    assert "Working on: Analyze financials." in comment_text
    assert "Loading:" not in comment_text


@pytest.mark.asyncio
async def test_process_routed_comment_event_uses_user_secret_for_delivery_renderer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    render_api_keys: list[str | None] = []
    property_updates: list[dict[str, object]] = []
    notebook_requests: list[dict] = []
    install = NotionInstallation(
        id="install-1",
        org_id="org-1",
        user_id="user-1",
        workspace_id="workspace-1",
        bot_id="bot-1",
        access_token_enc=b"encrypted",
        status="active",
    )
    config = NotionInstallationConfig(
        installation_id="install-1",
        parent_page_id=None,
        trigger_page_id="trigger-1",
        requests_data_source_id="ds-1",
        requests_database_page_id="db-1",
        enabled=True,
        default_project_id="project-1",
        default_branch="main",
        analysis_branch_mode="per_request",
    )
    routed = RoutedNotionInstallation(installation=install, config=config, access_token="token-1")
    db = MagicMock()
    payload = {
        "id": "event-1",
        "entity": {"id": "comment-1"},
        "data": {"page_id": "page-1"},
        "authors": [{"id": "notion-user-1", "type": "person"}],
    }
    comment = {"id": "comment-1", "discussion_id": "discussion-1", "rich_text": []}
    runtime = NotebookRuntime(
        session_id="runtime-1",
        internal_base_url="http://notebook.internal/notebook/runtime-1",
        public_base_url="https://app.test/notebook/runtime-1",
    )
    route = notion_analysis.AnalysisRoute(
        source="notion",
        request_id="notion-req-1",
        project_id="project-1",
        branch="analysis/notion/notion-req-1-revenue",
        default_branch="main",
        analysis_user_id="analysis:notion:notion-req-1",
    )

    async def list_comments(*args, **kwargs):
        return [comment]

    async def query_request_page_by_source(*args, **kwargs):
        return None

    async def create_request_page(*args, **kwargs):
        return {"id": "request-page-1", "url": "https://notion.test/request-page-1"}

    async def update_page_properties(_token, _page_id, properties):
        property_updates.append(properties)

    async def append_page_blocks(*args, **kwargs):
        return None

    async def create_comment(*args, **kwargs):
        return {"id": "progress-comment-1"}

    async def delete_comment(*args, **kwargs):
        return None

    async def resolve_route(*args, **kwargs):
        return route

    async def ensure_runtime(*args, **kwargs):
        return runtime

    async def noop_async(*args, **kwargs):
        return None

    async def call_notebook(*args, **kwargs):
        notebook_requests.append(args[4])
        return {"requestId": "notion-req-1", "trailUrl": "https://app.test/projects?file=analysis.py"}

    async def poll_analysis(*args, **kwargs):
        return {
            "status": "Done",
            "requestId": "notion-req-1",
            "sessionId": "session-notion-req-1",
            "summary": "Done",
        }

    async def load_delivery_packet(*args, **kwargs):
        assert kwargs["user_id"] == "user-1"
        return DeliveryPacket(user_request="Analyze revenue by month", status="done")

    async def delivery_api_key_for_user(*args, **kwargs):
        assert args == (db,)
        assert kwargs == {"org_id": "org-1", "user_id": "user-1"}
        return "sk-ant-user"

    async def render_delivery(packet, *, api_key=None, renderer=None):
        del packet, renderer
        render_api_keys.append(api_key)
        return DeliveryResult(
            summary="Done",
            slack_message="- Done",
            notion_comment="- Done",
            final_answer="- Done",
            confidence_score="high",
        )

    async def upload_chart_images_to_notion(_token, status, _runtime):
        return status

    monkeypatch.setattr(notion_client, "list_comments", list_comments)
    monkeypatch.setattr(notion_client, "query_request_page_by_source", query_request_page_by_source)
    monkeypatch.setattr(notion_client, "create_request_page", create_request_page)
    monkeypatch.setattr(notion_client, "update_page_properties", update_page_properties)
    monkeypatch.setattr(notion_client, "append_page_blocks", append_page_blocks)
    monkeypatch.setattr(notion_client, "create_comment", create_comment)
    monkeypatch.setattr(notion_client, "delete_comment", delete_comment)
    monkeypatch.setattr(notion_client, "is_bot_comment", lambda _comment: False)
    monkeypatch.setattr(notion_client, "comment_has_page_mention", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(notion_client, "extract_comment_text", lambda _comment: "Analyze revenue by month")
    monkeypatch.setattr(notion_analysis, "resolve_configured_analysis_route", resolve_route)
    monkeypatch.setattr(notion_analysis, "ensure_analysis_notebook_session", ensure_runtime)
    monkeypatch.setattr(notion_analysis, "upsert_analysis_trail_seed", noop_async)
    monkeypatch.setattr(notion_analysis, "upsert_analysis_trail_from_status", noop_async)
    monkeypatch.setattr(notion_analysis, "update_analysis_trail_from_status", noop_async)
    monkeypatch.setattr(notion_analysis, "_call_notebook", call_notebook)
    monkeypatch.setattr(notion_analysis, "_poll_analysis", poll_analysis)
    monkeypatch.setattr(notion_analysis, "_with_public_chart_urls", lambda status, runtime: status)
    monkeypatch.setattr(notion_analysis, "_upload_chart_images_to_notion", upload_chart_images_to_notion)
    monkeypatch.setattr(notion_analysis, "load_delivery_packet", load_delivery_packet)
    monkeypatch.setattr(notion_analysis, "delivery_api_key_for_user", delivery_api_key_for_user)
    monkeypatch.setattr(notion_analysis, "render_delivery", render_delivery)

    result = await notion_analysis.process_routed_comment_event(routed, payload, db=db)

    assert result.status == "processed"
    assert notebook_requests[0]["json"]["theme"]["chartSeries"][0] == "#087a3d"
    assert notebook_requests[0]["json"]["theme"]["bg"] == "#050505"
    assert render_api_keys == ["sk-ant-user"]
    confidence_updates = [update["Confidence score"] for update in property_updates if "Confidence score" in update]
    assert confidence_updates
    assert "number" not in confidence_updates[-1]
    assert _rich_text_content(confidence_updates[-1]["rich_text"]) == "high"


@pytest.mark.asyncio
async def test_insert_html_deliverable_lets_empty_user_key_use_gateway_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received_api_keys: list[str | None] = []
    recorded_deliverables: list[dict] = []
    install = NotionInstallation(
        id="install-1",
        org_id="org-1",
        user_id="user-1",
        workspace_id="workspace-1",
        bot_id="bot-1",
        access_token_enc=b"encrypted",
        status="active",
    )
    config = NotionInstallationConfig(installation_id="install-1")
    routed = RoutedNotionInstallation(installation=install, config=config, access_token="token-1")
    route = notion_analysis.AnalysisRoute(
        source="notion",
        request_id="notion-req-1",
        project_id="project-1",
        branch="analysis/notion/notion-req-1-dashboard",
        default_branch="main",
        analysis_user_id="analysis:notion:notion-req-1",
    )

    async def render_html_deliverable(packet, *, api_key=None, fetch_snapshot=None, orchestrator=None, theme=None):
        del packet, fetch_snapshot, orchestrator, theme
        received_api_keys.append(api_key)
        return HtmlDeliverableResult(
            kind="dashboard",
            title="Database Dashboard",
            html='<!doctype html><html><body><script type="application/json" id="sp-data">{}</script></body></html>',
            data_json={"rows": []},
        )

    async def insert_report(*args, **kwargs):
        return SimpleNamespace(id="report-1")

    async def insert_html_deliverable(*args, **kwargs):
        return SimpleNamespace(
            block_id="embed-block-1",
            file_upload_id="file-upload-1",
            fallback_url=None,
            archived_block_id=None,
        )

    async def record_deliverable(*args, **kwargs):
        recorded_deliverables.append(kwargs)

    monkeypatch.setattr(notion_analysis, "render_html_deliverable", render_html_deliverable)
    monkeypatch.setattr(notion_analysis.reports_store, "insert_report", insert_report)
    monkeypatch.setattr(notion_analysis.notion_dashboards, "insert_html_deliverable", insert_html_deliverable)
    monkeypatch.setattr(notion_analysis.notion_store, "record_deliverable", record_deliverable)

    delivered = await notion_analysis._insert_html_deliverable(
        db=MagicMock(),
        token="token-1",
        routed=routed,
        route=route,
        page_id="page-1",
        request_page_id="request-page-1",
        discussion_id="discussion-1",
        anchor_block_id=None,
        packet=DeliveryPacket(user_request="Build a database dashboard", status="done"),
        api_key="",
        runtime=None,
        session_id="session-notion-req-1",
    )

    assert delivered is True
    assert received_api_keys == [None]
    assert recorded_deliverables[0]["report_id"] == "report-1"


def test_public_signalpilot_url_preserves_durable_notebooks_trail_url() -> None:
    runtime = NotebookRuntime(
        session_id="runtime-session-1",
        internal_base_url="http://10.0.0.5:2718/notebook/runtime-session-1",
        public_base_url="https://app.signalpilot.ai/notebook/runtime-session-1",
    )
    durable_url = (
        "https://app.signalpilot.ai/projects?"
        "file=signalpilot-notion-analyses%2Fanalysis.py&session_id=session-notion-abc123"
    )

    rewritten = notion_analysis._public_signalpilot_url(durable_url, runtime)

    assert rewritten == durable_url
    assert "/notebook/runtime-session-1/notebooks" not in rewritten


@pytest.mark.asyncio
async def test_deliverable_lookup_normalizes_embed_block_ids() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(GatewayBase.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with factory() as session:
            row = NotionDeliverable(
                id="deliverable-1",
                org_id="org-1",
                installation_id="install-1",
                page_id="page-1",
                request_id="notion-req-1",
                report_id="report-1",
                kind="dashboard",
                embed_block_id="11111111-2222-3333-4444-555555555555",
                file_upload_id="file-1",
            )
            session.add(row)
            await session.commit()

            found = await notion_store.find_deliverable_by_embed_block(
                session,
                org_id="org-1",
                installation_id="install-1",
                embed_block_id="11111111222233334444555555555555",
            )

        assert found is not None
        assert found.id == "deliverable-1"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_deliverable_lookup_normalizes_discussion_ids() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(GatewayBase.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with factory() as session:
            row = NotionDeliverable(
                id="deliverable-1",
                org_id="org-1",
                installation_id="install-1",
                page_id="page-1",
                request_id="notion-req-1",
                report_id="report-1",
                kind="dashboard",
                discussion_id="11111111-2222-3333-4444-555555555555",
                embed_block_id="embed-block-1",
                file_upload_id="file-1",
            )
            session.add(row)
            await session.commit()

            found = await notion_store.find_deliverable_by_discussion(
                session,
                org_id="org-1",
                installation_id="install-1",
                discussion_id="11111111222233334444555555555555",
            )

        assert found is not None
        assert found.id == "deliverable-1"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_update_deliverable_discussion_preserves_initial_discussion() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(GatewayBase.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with factory() as session:
            row = NotionDeliverable(
                id="deliverable-1",
                org_id="org-1",
                installation_id="install-1",
                page_id="page-1",
                request_id="notion-req-1",
                report_id="report-1",
                kind="dashboard",
                discussion_id="build-discussion-1",
                embed_block_id="embed-block-1",
                file_upload_id="file-1",
            )
            session.add(row)
            await session.commit()

            updated = await notion_store.update_deliverable_discussion(
                session,
                deliverable_id="deliverable-1",
                discussion_id="embed-discussion-1",
            )

        assert updated is not None
        assert updated.discussion_id == "embed-discussion-1"
        assert updated.metadata_json["initial_discussion_id"] == "build-discussion-1"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_refresh_followup_bypasses_generic_preflight_and_replaces_same_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []
    routed = _routed_installation_for_followup()
    deliverable = SimpleNamespace(
        id="deliverable-1",
        report_id="report-1",
        embed_block_id="embed-block-1",
        file_upload_id="file-old",
    )
    report = SimpleNamespace(
        id="report-1",
        kind="dashboard",
        title="Revenue Dashboard",
        html="<html>old</html>",
        data_json={"old": True},
    )
    context = SimpleNamespace(
        base_notebook_code="import signalpilot as sp\n",
        base_chat_events=[{"type": "user", "content": "build dashboard"}],
        base_final_packet={"userRequest": "build dashboard"},
        base_notebook_path="notebooks/notion/original.py",
        project_id="project-1",
        branch="analysis/notion/notion-req-1-dashboard",
    )

    async def list_comments(*args, **kwargs):
        return [{"id": "comment-1", "discussion_id": "discussion-1", "rich_text": []}]

    async def create_comment(*args, **kwargs):
        calls.append(("comment", _rich_text_content(kwargs["rich_text"])))

    async def find_deliverable(*args, **kwargs):
        calls.append(("lookup", kwargs["embed_block_id"]))
        return deliverable

    async def create_update(*args, **kwargs):
        calls.append(("create_update", kwargs))
        return SimpleNamespace(id="update-1")

    async def get_report(*args, **kwargs):
        return report

    async def latest_context(*args, **kwargs):
        return context

    async def delivery_api_key(*args, **kwargs):
        return ""

    async def run_refresh(*args, **kwargs):
        calls.append(("refresh", kwargs["data_instruction"]))
        return DeliveryPacket(user_request=kwargs["data_instruction"], data_snapshots=[{"name": "fresh"}]), None

    async def render_followup(*args, **kwargs):
        calls.append(("render", {"instruction": args[0], "mode": args[3], "packet": args[2]}))
        return HtmlDeliverableResult(
            kind="dashboard",
            title="Revenue Dashboard",
            html="<html>new</html>",
            data_json={"fresh": True},
        )

    async def replace_html(*args, **kwargs):
        calls.append(("replace", kwargs))
        return SimpleNamespace(block_id=kwargs["embed_block_id"], file_upload_id="file-new")

    async def update_report(*args, **kwargs):
        calls.append(("update_report", kwargs))
        return report

    async def mark_success(*args, **kwargs):
        calls.append(("success", kwargs))

    monkeypatch.setattr(notion_client, "list_comments", list_comments)
    monkeypatch.setattr(notion_client, "create_comment", create_comment)
    monkeypatch.setattr(notion_client, "is_bot_comment", lambda _comment: False)
    monkeypatch.setattr(notion_client, "comment_has_page_mention", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(notion_client, "extract_comment_text", lambda _comment: "refresh this")
    monkeypatch.setattr(notion_analysis.notion_store, "find_deliverable_by_embed_block", find_deliverable)
    monkeypatch.setattr(
        notion_analysis,
        "classify_analysis_request",
        lambda _prompt: (_ for _ in ()).throw(AssertionError("preflight should not run")),
    )
    monkeypatch.setattr(notion_analysis.reports_store, "get_report", get_report)
    monkeypatch.setattr(notion_analysis.notion_store, "create_deliverable_update", create_update)
    monkeypatch.setattr(notion_analysis.notion_store, "latest_deliverable_context_snapshot", latest_context)
    monkeypatch.setattr(notion_analysis, "_run_ephemeral_deliverable_refresh", run_refresh)
    monkeypatch.setattr(notion_analysis, "delivery_api_key_for_user", delivery_api_key)
    monkeypatch.setattr(notion_analysis, "render_followup", render_followup)
    monkeypatch.setattr(notion_analysis.notion_dashboards, "replace_html_deliverable", replace_html)
    monkeypatch.setattr(notion_analysis.reports_store, "update_report_html", update_report)
    monkeypatch.setattr(notion_analysis.notion_store, "mark_deliverable_update_succeeded", mark_success)

    result = await notion_analysis.process_routed_comment_event(routed, _followup_payload(), db=MagicMock())

    assert result.status == "processed"
    assert ("lookup", "embed-block-1") in calls
    assert any(name == "refresh" for name, _ in calls)
    render_call = next(payload for name, payload in calls if name == "render")
    assert render_call["mode"] == "refresh_data"
    replace_call = next(payload for name, payload in calls if name == "replace")
    assert replace_call["embed_block_id"] == "embed-block-1"
    update_call = next(payload for name, payload in calls if name == "update_report")
    assert update_call["report_id"] == "report-1"
    assert any(
        payload == "Updated this dashboard/report with fresh data." for name, payload in calls if name == "comment"
    )


@pytest.mark.asyncio
async def test_edit_only_followup_does_not_call_notebook_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, object]] = []
    routed = _routed_installation_for_followup()
    deliverable = SimpleNamespace(
        id="deliverable-1",
        report_id="report-1",
        embed_block_id="embed-block-1",
        file_upload_id="file-old",
    )
    report = SimpleNamespace(
        id="report-1",
        kind="dashboard",
        title="Revenue Dashboard",
        html="<html>old</html>",
        data_json={"rows": []},
    )

    async def list_comments(*args, **kwargs):
        return [{"id": "comment-1", "discussion_id": "discussion-1", "rich_text": []}]

    async def create_update(*args, **kwargs):
        return SimpleNamespace(id="update-1")

    async def find_deliverable(*args, **kwargs):
        return deliverable

    async def get_report(*args, **kwargs):
        return report

    async def delivery_api_key(*args, **kwargs):
        return ""

    async def mark_success(*args, **kwargs):
        return None

    async def render_followup(*args, **kwargs):
        calls.append(
            ("render", {"mode": args[3], "packet": args[2], "existing": args[1], "api_key": kwargs["api_key"]})
        )
        return HtmlDeliverableResult(kind="dashboard", title="Revenue Dashboard", html="<html>edited</html>")

    async def replace_html(*args, **kwargs):
        calls.append(("replace", kwargs))
        return SimpleNamespace(block_id=kwargs["embed_block_id"], file_upload_id="file-new")

    async def update_report(*args, **kwargs):
        calls.append(("update_report", kwargs))

    async def create_comment(*args, **kwargs):
        calls.append(("comment", _rich_text_content(kwargs["rich_text"])))

    monkeypatch.setattr(notion_client, "list_comments", list_comments)
    monkeypatch.setattr(notion_client, "create_comment", create_comment)
    monkeypatch.setattr(notion_client, "is_bot_comment", lambda _comment: False)
    monkeypatch.setattr(notion_client, "comment_has_page_mention", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(notion_client, "extract_comment_text", lambda _comment: "make the main chart a bar chart")
    monkeypatch.setattr(notion_analysis.notion_store, "find_deliverable_by_embed_block", find_deliverable)
    monkeypatch.setattr(notion_analysis.reports_store, "get_report", get_report)
    monkeypatch.setattr(notion_analysis.notion_store, "create_deliverable_update", create_update)
    monkeypatch.setattr(
        notion_analysis,
        "_run_ephemeral_deliverable_refresh",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("refresh should not run")),
    )
    monkeypatch.setattr(notion_analysis, "delivery_api_key_for_user", delivery_api_key)
    monkeypatch.setattr(notion_analysis, "render_followup", render_followup)
    monkeypatch.setattr(notion_analysis.notion_dashboards, "replace_html_deliverable", replace_html)
    monkeypatch.setattr(notion_analysis.reports_store, "update_report_html", update_report)
    monkeypatch.setattr(notion_analysis.notion_store, "mark_deliverable_update_succeeded", mark_success)

    result = await notion_analysis.process_routed_comment_event(routed, _followup_payload(), db=MagicMock())

    assert result.status == "processed"
    render_call = next(payload for name, payload in calls if name == "render")
    assert render_call["mode"] == "edit_existing"
    assert render_call["packet"] is None
    assert render_call["existing"]["report_id"] == "report-1"
    assert render_call["api_key"] is None
    assert any(payload == "Updated this dashboard/report." for name, payload in calls if name == "comment")


@pytest.mark.asyncio
async def test_followup_refuses_fallback_link_deliverable_before_render_or_patch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []
    routed = _routed_installation_for_followup()
    deliverable = SimpleNamespace(
        id="deliverable-1",
        report_id="report-1",
        embed_block_id="fallback-paragraph-1",
        file_upload_id=None,
        metadata_json={"fallback_url": "https://app.test/reports?report=report-1"},
    )
    report = SimpleNamespace(
        id="report-1",
        kind="dashboard",
        title="Revenue Dashboard",
        html="<html>old</html>",
        data_json={"rows": []},
    )

    async def list_comments(*args, **kwargs):
        return [{"id": "comment-1", "discussion_id": "discussion-1", "rich_text": []}]

    async def find_deliverable(*args, **kwargs):
        return deliverable

    async def get_report(*args, **kwargs):
        return report

    async def create_comment(*args, **kwargs):
        calls.append(("comment", _rich_text_content(kwargs["rich_text"])))

    monkeypatch.setattr(notion_client, "list_comments", list_comments)
    monkeypatch.setattr(notion_client, "create_comment", create_comment)
    monkeypatch.setattr(notion_client, "is_bot_comment", lambda _comment: False)
    monkeypatch.setattr(notion_client, "comment_has_page_mention", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(notion_client, "extract_comment_text", lambda _comment: "make the main chart a bar chart")
    monkeypatch.setattr(notion_analysis.notion_store, "find_deliverable_by_embed_block", find_deliverable)
    monkeypatch.setattr(notion_analysis.reports_store, "get_report", get_report)
    monkeypatch.setattr(
        notion_analysis.notion_store,
        "create_deliverable_update",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("update should not be created")),
    )
    monkeypatch.setattr(
        notion_analysis,
        "render_followup",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("render should not run")),
    )
    monkeypatch.setattr(
        notion_analysis.notion_dashboards,
        "replace_html_deliverable",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("patch should not run")),
    )

    result = await notion_analysis.process_routed_comment_event(routed, _followup_payload(), db=MagicMock())

    assert result.status == "processed"
    comment = next(payload for name, payload in calls if name == "comment")
    assert "delivered as a link" in comment
    assert "inline embed limit" in comment


@pytest.mark.asyncio
async def test_followup_reply_routes_by_discussion_when_parent_is_not_embed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []
    routed = _routed_installation_for_followup()
    deliverable = SimpleNamespace(
        id="deliverable-1",
        report_id="report-1",
        embed_block_id="embed-block-1",
        file_upload_id="file-old",
    )
    report = SimpleNamespace(
        id="report-1",
        kind="dashboard",
        title="Revenue Dashboard",
        html="<html>old</html>",
        data_json={"rows": []},
    )

    async def list_comments(*args, **kwargs):
        return [{"id": "comment-1", "discussion_id": "discussion-1", "rich_text": []}]

    async def find_by_embed(*args, **kwargs):
        calls.append(("embed_lookup", kwargs["embed_block_id"]))

    async def find_by_discussion(*args, **kwargs):
        calls.append(("discussion_lookup", kwargs["discussion_id"]))
        return deliverable

    async def create_update(*args, **kwargs):
        return SimpleNamespace(id="update-1")

    async def get_report(*args, **kwargs):
        return report

    async def delivery_api_key(*args, **kwargs):
        return "key-1"

    async def render_followup(*args, **kwargs):
        calls.append(("render", {"mode": args[3], "packet": args[2]}))
        return HtmlDeliverableResult(kind="dashboard", title="Revenue Dashboard", html="<html>edited</html>")

    async def replace_html(*args, **kwargs):
        calls.append(("replace", kwargs))
        return SimpleNamespace(block_id=kwargs["embed_block_id"], file_upload_id="file-new")

    async def update_report(*args, **kwargs):
        calls.append(("update_report", kwargs))

    async def mark_success(*args, **kwargs):
        return None

    async def create_comment(*args, **kwargs):
        calls.append(("comment", _rich_text_content(kwargs["rich_text"])))

    monkeypatch.setattr(notion_client, "list_comments", list_comments)
    monkeypatch.setattr(notion_client, "create_comment", create_comment)
    monkeypatch.setattr(notion_client, "is_bot_comment", lambda _comment: False)
    monkeypatch.setattr(notion_client, "comment_has_page_mention", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        notion_client, "extract_comment_text", lambda _comment: "breakdown monthly revenue using bar chart"
    )
    monkeypatch.setattr(notion_analysis.notion_store, "find_deliverable_by_embed_block", find_by_embed)
    monkeypatch.setattr(notion_analysis.notion_store, "find_deliverable_by_discussion", find_by_discussion)
    monkeypatch.setattr(
        notion_analysis,
        "classify_analysis_request",
        lambda _prompt: (_ for _ in ()).throw(AssertionError("preflight should not run")),
    )
    monkeypatch.setattr(notion_analysis.reports_store, "get_report", get_report)
    monkeypatch.setattr(notion_analysis.notion_store, "create_deliverable_update", create_update)
    monkeypatch.setattr(
        notion_analysis,
        "_run_ephemeral_deliverable_refresh",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("refresh should not run")),
    )
    monkeypatch.setattr(notion_analysis, "delivery_api_key_for_user", delivery_api_key)
    monkeypatch.setattr(notion_analysis, "render_followup", render_followup)
    monkeypatch.setattr(notion_analysis.notion_dashboards, "replace_html_deliverable", replace_html)
    monkeypatch.setattr(notion_analysis.reports_store, "update_report_html", update_report)
    monkeypatch.setattr(notion_analysis.notion_store, "mark_deliverable_update_succeeded", mark_success)

    result = await notion_analysis.process_routed_comment_event(
        routed,
        _followup_payload(parent_block_id="request-page-block-1"),
        db=MagicMock(),
    )

    assert result.status == "processed"
    assert ("embed_lookup", "request-page-block-1") in calls
    assert ("discussion_lookup", "discussion-1") in calls
    replace_call = next(payload for name, payload in calls if name == "replace")
    assert replace_call["embed_block_id"] == "embed-block-1"
    assert any(payload == "Updated this dashboard/report." for name, payload in calls if name == "comment")


@pytest.mark.asyncio
async def test_refresh_without_context_refuses_rebuild_and_does_not_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []
    routed = _routed_installation_for_followup()
    deliverable = SimpleNamespace(
        id="deliverable-1",
        report_id="report-1",
        embed_block_id="embed-block-1",
        file_upload_id="file-old",
    )
    report = SimpleNamespace(id="report-1", kind="dashboard", title="Dashboard", html="<html></html>", data_json={})

    async def list_comments(*args, **kwargs):
        return [{"id": "comment-1", "discussion_id": "discussion-1", "rich_text": []}]

    async def create_update(*args, **kwargs):
        return SimpleNamespace(id="update-1")

    async def find_deliverable(*args, **kwargs):
        return deliverable

    async def get_report(*args, **kwargs):
        return report

    async def latest_context(*args, **kwargs):
        return None

    async def mark_failed(*args, **kwargs):
        calls.append(("failed", kwargs["error"]))

    async def create_comment(*args, **kwargs):
        calls.append(("comment", _rich_text_content(kwargs["rich_text"])))

    monkeypatch.setattr(notion_client, "list_comments", list_comments)
    monkeypatch.setattr(notion_client, "create_comment", create_comment)
    monkeypatch.setattr(notion_client, "is_bot_comment", lambda _comment: False)
    monkeypatch.setattr(notion_client, "comment_has_page_mention", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(notion_client, "extract_comment_text", lambda _comment: "refresh this")
    monkeypatch.setattr(notion_analysis.notion_store, "find_deliverable_by_embed_block", find_deliverable)
    monkeypatch.setattr(notion_analysis.reports_store, "get_report", get_report)
    monkeypatch.setattr(notion_analysis.notion_store, "create_deliverable_update", create_update)
    monkeypatch.setattr(notion_analysis.notion_store, "latest_deliverable_context_snapshot", latest_context)
    monkeypatch.setattr(
        notion_analysis,
        "_run_ephemeral_deliverable_refresh",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("refresh should not run")),
    )
    monkeypatch.setattr(
        notion_analysis,
        "render_followup",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("render should not run")),
    )
    monkeypatch.setattr(
        notion_analysis.notion_dashboards,
        "replace_html_deliverable",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("replace should not run")),
    )
    monkeypatch.setattr(notion_analysis.notion_store, "mark_deliverable_update_failed", mark_failed)

    result = await notion_analysis.process_routed_comment_event(routed, _followup_payload(), db=MagicMock())

    assert result.status == "processed"
    assert any("rebuild once" in str(payload) for name, payload in calls if name == "failed")
    assert any("rebuild once" in str(payload) for name, payload in calls if name == "comment")


@pytest.mark.asyncio
async def test_patch_failure_does_not_update_report_or_success_pointers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    routed = _routed_installation_for_followup()
    deliverable = SimpleNamespace(
        id="deliverable-1",
        report_id="report-1",
        embed_block_id="embed-block-1",
        file_upload_id="file-old",
    )
    report = SimpleNamespace(id="report-1", kind="dashboard", title="Dashboard", html="<html>old</html>", data_json={})

    async def list_comments(*args, **kwargs):
        return [{"id": "comment-1", "discussion_id": "discussion-1", "rich_text": []}]

    async def create_update(*args, **kwargs):
        return SimpleNamespace(id="update-1")

    async def find_deliverable(*args, **kwargs):
        return deliverable

    async def get_report(*args, **kwargs):
        return report

    async def delivery_api_key(*args, **kwargs):
        return ""

    async def render_followup(*args, **kwargs):
        return HtmlDeliverableResult(kind="dashboard", title="Dashboard", html="<html>new</html>")

    async def replace_html(*args, **kwargs):
        calls.append("replace")
        raise RuntimeError("notion patch failed")

    async def mark_failed(*args, **kwargs):
        calls.append("failed")

    async def fail_update_report(*args, **kwargs):
        raise AssertionError("report should not update after patch failure")

    async def fail_mark_success(*args, **kwargs):
        raise AssertionError("success should not be recorded")

    async def create_comment(*args, **kwargs):
        calls.append("comment")

    monkeypatch.setattr(notion_client, "list_comments", list_comments)
    monkeypatch.setattr(notion_client, "create_comment", create_comment)
    monkeypatch.setattr(notion_client, "is_bot_comment", lambda _comment: False)
    monkeypatch.setattr(notion_client, "comment_has_page_mention", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(notion_client, "extract_comment_text", lambda _comment: "make the title shorter")
    monkeypatch.setattr(notion_analysis.notion_store, "find_deliverable_by_embed_block", find_deliverable)
    monkeypatch.setattr(notion_analysis.reports_store, "get_report", get_report)
    monkeypatch.setattr(notion_analysis.notion_store, "create_deliverable_update", create_update)
    monkeypatch.setattr(notion_analysis, "delivery_api_key_for_user", delivery_api_key)
    monkeypatch.setattr(notion_analysis, "render_followup", render_followup)
    monkeypatch.setattr(notion_analysis.notion_dashboards, "replace_html_deliverable", replace_html)
    monkeypatch.setattr(notion_analysis.reports_store, "update_report_html", fail_update_report)
    monkeypatch.setattr(notion_analysis.notion_store, "mark_deliverable_update_succeeded", fail_mark_success)
    monkeypatch.setattr(notion_analysis.notion_store, "mark_deliverable_update_failed", mark_failed)

    result = await notion_analysis.process_routed_comment_event(routed, _followup_payload(), db=MagicMock())

    assert result.status == "processed"
    assert calls == ["comment", "replace", "failed", "comment"]
    assert deliverable.file_upload_id == "file-old"


def test_public_signalpilot_url_rewrites_internal_notebooks_trail_to_app_origin() -> None:
    runtime = NotebookRuntime(
        session_id="runtime-session-1",
        internal_base_url="http://172.31.11.176:2718/notebook/runtime-session-1",
        public_base_url="https://app.signalpilot.ai/notebook/runtime-session-1",
    )
    wrong_url = (
        "http://172.31.11.176:2718/notebooks?"
        "file=signalpilot-notion-analyses/do-an-analysis-of-my-db-9a50e7.py"
        "&session_id=session-notion-97728a45b49a50e7"
    )

    rewritten = notion_analysis._public_signalpilot_url(wrong_url, runtime)

    assert (
        rewritten == "https://app.signalpilot.ai/projects?"
        "file=signalpilot-notion-analyses/do-an-analysis-of-my-db-9a50e7.py"
        "&session_id=session-notion-97728a45b49a50e7"
    )
    assert "172.31.11.176" not in rewritten
    assert "/notebook/runtime-session-1/notebooks" not in rewritten


def test_public_signalpilot_url_rewrites_relative_notebooks_trail_to_app_origin() -> None:
    runtime = NotebookRuntime(
        session_id="runtime-session-1",
        internal_base_url="http://10.0.0.5:2718/notebook/runtime-session-1",
        public_base_url="https://app.signalpilot.ai/notebook/runtime-session-1",
    )

    for url in (
        "/notebooks?file=signalpilot-notion-analyses/analysis.py&session_id=session-notion-abc123",
        "notebooks?file=signalpilot-notion-analyses/analysis.py&session_id=session-notion-abc123",
        "/projects?file=signalpilot-notion-analyses/analysis.py&session_id=session-notion-abc123",
    ):
        rewritten = notion_analysis._public_signalpilot_url(url, runtime)

        assert (
            rewritten == "https://app.signalpilot.ai/projects?"
            "file=signalpilot-notion-analyses/analysis.py&session_id=session-notion-abc123"
        )


def test_public_signalpilot_url_rewrites_runtime_urls_to_public_runtime_proxy() -> None:
    runtime = NotebookRuntime(
        session_id="runtime-session-1",
        internal_base_url="http://10.0.0.5:2718/notebook/runtime-session-1",
        public_base_url="https://app.signalpilot.ai/notebook/runtime-session-1",
    )

    rewritten = notion_analysis._public_signalpilot_url(
        "http://10.0.0.5:2718/notebook/runtime-session-1/api/notion-analysis/chart/notion-1/chart.png",
        runtime,
    )

    expected = "https://app.signalpilot.ai/notebook/runtime-session-1/api/notion-analysis/chart/notion-1/chart.png"
    assert rewritten == expected


def test_final_comment_rich_text_formats_bullets_links_and_code() -> None:
    request_url = "https://notion.test/request-page-1"
    status = {
        "notionComment": "- Query `orders`\n- See https://charts.test/revenue.png",
        "summary": "Revenue increased.",
    }

    rich_text = notion_analysis._final_comment_rich_text(status, request_url)
    content = _rich_text_content(rich_text)

    assert "• Query " in content
    assert any(
        part.get("text", {}).get("content") == "orders" and part.get("annotations", {}).get("code") is True
        for part in rich_text
    )
    assert any(
        part.get("text", {}).get("link", {}).get("url") == "https://charts.test/revenue.png" for part in rich_text
    )
    assert any(part.get("text", {}).get("link", {}).get("url") == request_url for part in rich_text)


def test_final_comment_rich_text_appends_confidence_score() -> None:
    rich_text = notion_analysis._final_comment_rich_text(
        {
            "notionComment": "- Northstar leads revenue.",
            "confidenceScore": "medium",
        },
        "https://notion.test/request-page-1",
    )
    content = _rich_text_content(rich_text)

    assert "• Northstar leads revenue." in content
    assert "• Confidence score: medium" in content
    assert content.index("Confidence score: medium") < content.index("Request page:")


def test_final_comment_rich_text_does_not_duplicate_existing_confidence_score() -> None:
    rich_text = notion_analysis._final_comment_rich_text(
        {
            "notionComment": "- Northstar leads revenue.\n- Confidence score: medium",
            "confidenceScore": "medium",
        },
        "https://notion.test/request-page-1",
    )
    content = _rich_text_content(rich_text)

    assert content.count("Confidence score: medium") == 1


def test_final_comment_rich_text_avoids_duplicate_bullet_markers_and_formats_bold() -> None:
    rich_text = notion_analysis._final_comment_rich_text(
        {
            "notionComment": (
                "• **MapleCloud Software** has the best overall operating momentum.\n"
                "- • **Northstar Logistics** ranks second."
            )
        },
        "https://notion.test/request-page-1",
    )
    content = _rich_text_content(rich_text)

    assert "- •" not in content
    assert content.startswith("• MapleCloud Software")
    assert "\n• Northstar Logistics" in content
    assert any(
        part.get("text", {}).get("content") == "MapleCloud Software" and part.get("annotations", {}).get("bold") is True
        for part in rich_text
    )


def test_final_comment_rich_text_formats_italic_and_strikethrough() -> None:
    rich_text = notion_analysis._final_comment_rich_text(
        {
            "notionComment": (
                "- *Expansion revenue* improved.\n- _Pipeline coverage_ strengthened.\n- ~~Legacy score~~ was removed."
            )
        },
        "https://notion.test/request-page-1",
    )
    content = _rich_text_content(rich_text)

    assert "*Expansion revenue*" not in content
    assert "_Pipeline coverage_" not in content
    assert "~~Legacy score~~" not in content
    assert any(
        part.get("text", {}).get("content") == "Expansion revenue" and part.get("annotations", {}).get("italic") is True
        for part in rich_text
    )
    assert any(
        part.get("text", {}).get("content") == "Pipeline coverage" and part.get("annotations", {}).get("italic") is True
        for part in rich_text
    )
    assert any(
        part.get("text", {}).get("content") == "Legacy score"
        and part.get("annotations", {}).get("strikethrough") is True
        for part in rich_text
    )


def test_final_comment_rich_text_mentions_attached_charts() -> None:
    rich_text = notion_analysis._final_comment_rich_text(
        {
            "notionComment": "- MapleCloud leads.",
            "notionCharts": [
                {
                    "title": "Momentum ranking",
                    "url": "/api/notion-analysis/chart/req/ranking.png",
                    "fileUploadId": "upload-1",
                    "includeInComment": True,
                    "includeOnPage": True,
                }
            ],
        },
        "https://notion.test/request-page-1",
    )
    content = _rich_text_content(rich_text)

    assert "Charts attached:" in content
    assert "Momentum ranking" in content


def test_final_comment_rich_text_omits_placeholder_chart_titles() -> None:
    status = {
        "notionComment": "- MapleCloud leads.",
        "notionCharts": [
            {
                "title": "Notebook image 1",
                "url": "/api/notion-analysis/chart/req/image-1.png",
                "fileUploadId": "upload-1",
                "includeInComment": True,
                "includeOnPage": True,
            },
            {
                "title": "Notebook image 1",
                "url": "/api/notion-analysis/chart/req/image-2.png",
                "fileUploadId": "upload-2",
                "includeInComment": True,
                "includeOnPage": True,
            },
        ],
    }

    rich_text = notion_analysis._final_comment_rich_text(status, "https://notion.test/request-page-1")
    content = _rich_text_content(rich_text)

    assert "Charts attached:" not in content
    assert "Notebook image" not in content
    assert notion_analysis._comment_attachments(status) == [
        {"type": "file_upload", "file_upload_id": "upload-1"},
        {"type": "file_upload", "file_upload_id": "upload-2"},
    ]


def test_analysis_detail_blocks_omit_placeholder_chart_captions() -> None:
    blocks = notion_analysis._analysis_detail_blocks(
        {
            "summary": "MapleCloud leads.",
            "notionCharts": [
                {
                    "title": "Notebook image 1",
                    "caption": "Chart 1",
                    "url": "/api/notion-analysis/chart/req/image-1.png",
                    "fileUploadId": "upload-1",
                    "includeInComment": True,
                    "includeOnPage": True,
                }
            ],
        }
    )

    image = next(block["image"] for block in blocks if block.get("type") == "image")

    assert image["caption"] == []
    assert image["file_upload"] == {"id": "upload-1"}


def test_analysis_detail_blocks_prepend_uploaded_chart_images() -> None:
    blocks = notion_analysis._analysis_detail_blocks(
        {
            "summary": "MapleCloud leads.",
            "finalAnswer": "## Executive Summary and Explorations\n\n- MapleCloud leads.",
            "notionCharts": [
                {
                    "title": "Momentum ranking",
                    "caption": "**MapleCloud** leads the composite ranking.",
                    "url": "/api/notion-analysis/chart/req/ranking.png",
                    "fileUploadId": "upload-1",
                    "includeInComment": True,
                    "includeOnPage": True,
                }
            ],
        }
    )

    assert blocks[0]["type"] == "heading_2"
    assert blocks[0]["heading_2"]["rich_text"][0]["text"]["content"] == "Charts"
    assert blocks[1]["type"] == "image"
    assert blocks[1]["image"]["type"] == "file_upload"
    assert blocks[1]["image"]["file_upload"]["id"] == "upload-1"
    assert any(
        part.get("text", {}).get("content") == "MapleCloud" and part.get("annotations", {}).get("bold") is True
        for part in blocks[1]["image"]["caption"]
    )


def test_incomplete_analysis_fallback_skips_html_deliverable() -> None:
    assert notion_analysis._is_incomplete_analysis_fallback(
        {
            "status": "Done",
            "summary": "Analysis could not be completed.",
            "finalAnswer": ("The agent did not emit the required FINAL_STATEMENT marker. API Error: Overloaded"),
        }
    )
    assert not notion_analysis._is_incomplete_analysis_fallback(
        {
            "status": "Done",
            "summary": "Portfolio revenue grew.",
            "finalAnswer": "Portfolio revenue grew and margin expanded.",
        }
    )


@pytest.mark.asyncio
async def test_upload_chart_images_to_notion_uploads_unique_chart_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fetch_chart_image(chart: dict):
        assert chart["url"].endswith(".png")
        return b"png-bytes", "image/png"

    async def upload_file(*args, **kwargs):
        return {"id": f"upload-{kwargs['filename']}"}

    monkeypatch.setattr(notion_analysis, "_fetch_chart_image", fetch_chart_image)
    monkeypatch.setattr(notion_client, "upload_file", upload_file)

    status = {
        "notionCharts": [
            {
                "title": "Momentum ranking",
                "url": "/api/notion-analysis/chart/req/ranking.png",
                "includeInComment": True,
                "includeOnPage": True,
            },
            {
                "title": "Momentum ranking duplicate",
                "url": "/api/notion-analysis/chart/req/ranking.png",
                "includeInComment": True,
                "includeOnPage": True,
            },
        ]
    }

    uploaded = await notion_analysis._upload_chart_images_to_notion("token-1", status)

    assert uploaded["notionCharts"][0]["fileUploadId"].startswith("upload-momentum-ranking")
    assert uploaded["notionCharts"][1]["fileUploadId"].startswith("upload-momentum-ranking")


@pytest.mark.asyncio
async def test_create_final_comment_retries_without_chart_attachments(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    async def create_comment(*args, **kwargs):
        calls.append(
            {
                "attachments": kwargs.get("attachments"),
                "text": _rich_text_content(kwargs["rich_text"]),
            }
        )
        if kwargs.get("attachments"):
            raise RuntimeError("attachments rejected")

    monkeypatch.setattr(notion_client, "create_comment", create_comment)

    await notion_analysis._create_final_comment(
        "token-1",
        "discussion-1",
        {
            "notionComment": "- MapleCloud leads.",
            "notionCharts": [
                {
                    "title": "Momentum ranking",
                    "url": "/api/notion-analysis/chart/req/ranking.png",
                    "fileUploadId": "upload-1",
                    "includeInComment": True,
                    "includeOnPage": True,
                }
            ],
        },
        "https://notion.test/request-page-1",
    )

    assert calls[0]["attachments"] == [{"type": "file_upload", "file_upload_id": "upload-1"}]
    assert calls[1]["attachments"] is None
    assert "Charts attached:" in str(calls[0]["text"])
    assert "Charts attached:" not in str(calls[1]["text"])


@pytest.mark.asyncio
async def test_create_final_comment_deletes_progress_comment_then_posts_attached_final(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []

    async def delete_comment(_token, comment_id):
        calls.append(("delete", comment_id))

    async def create_comment(*args, **kwargs):
        calls.append(
            (
                "create",
                {
                    "text": _rich_text_content(kwargs["rich_text"]),
                    "attachments": kwargs.get("attachments"),
                },
            )
        )

    monkeypatch.setattr(notion_client, "delete_comment", delete_comment)
    monkeypatch.setattr(notion_client, "create_comment", create_comment)

    await notion_analysis._create_final_comment(
        "token-1",
        "discussion-1",
        {
            "notionComment": "- MapleCloud leads.",
            "notionCharts": [
                {
                    "title": "Momentum ranking",
                    "url": "/api/notion-analysis/chart/req/ranking.png",
                    "fileUploadId": "upload-1",
                    "includeInComment": True,
                    "includeOnPage": True,
                }
            ],
        },
        "https://notion.test/request-page-1",
        comment_id="comment-1",
    )

    assert calls == [
        ("delete", "comment-1"),
        (
            "create",
            {
                "text": (
                    "• MapleCloud leads.\n\nRequest page: request details\n\nCharts attached:\n• Momentum ranking"
                ),
                "attachments": [
                    {
                        "type": "file_upload",
                        "file_upload_id": "upload-1",
                    }
                ],
            },
        ),
    ]


def test_failure_comment_rich_text_links_page_and_marks_error_as_code() -> None:
    request_url = "https://notion.test/request-page-1"

    rich_text = notion_analysis._failure_comment_rich_text("ValueError: relation orders not found", request_url)

    assert any(part.get("text", {}).get("content") == "failure details" for part in rich_text)
    assert any(part.get("text", {}).get("link", {}).get("url") == request_url for part in rich_text)
    assert any(
        "ValueError" in part.get("text", {}).get("content", "") and part.get("annotations", {}).get("code") is True
        for part in rich_text
    )


def test_notion_comment_note_appends_html_delivery_status_once() -> None:
    status = {"notionComment": "- Done"}

    updated = notion_analysis._with_notion_comment_note(status, "- HTML block inserted on this Notion page.")
    updated_again = notion_analysis._with_notion_comment_note(updated, "- HTML block inserted on this Notion page.")

    assert updated["notionComment"] == "- Done\n- HTML block inserted on this Notion page."
    assert updated_again["notionComment"] == updated["notionComment"]
    assert status["notionComment"] == "- Done"


def test_analysis_detail_blocks_render_markdown_as_notion_blocks() -> None:
    status = {
        "confidenceScore": "high",
        "finalAnswer": (
            "## Executive Summary and Explorations\n\n"
            "- Revenue increased in `orders`.\n\n"
            "## Detailed Research\n\n"
            "See [chart](https://charts.test/revenue.png).\n\n"
            "## Confidence Score: high\n\n"
            "- Source data was complete."
        ),
        "gotchas": ["Source data was complete."],
    }

    blocks = notion_analysis._analysis_detail_blocks(status)
    block_types = [block["type"] for block in blocks]
    block_text = "".join(
        rich_text.get("text", {}).get("content", "") for block in blocks for rich_text in _block_rich_text(block)
    )

    assert block_types.count("heading_2") == 3
    assert "bulleted_list_item" in block_types
    assert any(
        block["type"] == "heading_2"
        and block["heading_2"]["rich_text"][0]["text"]["content"] == "Detailed Research"
        and block["heading_2"].get("is_toggleable") is True
        for block in blocks
    )
    assert any(
        block["type"] == "heading_2"
        and block["heading_2"]["rich_text"][0]["text"]["content"] == "Confidence Score: high"
        and block["heading_2"].get("is_toggleable") is True
        for block in blocks
    )
    assert "##" not in block_text
    assert any(
        rich_text.get("text", {}).get("content") == "orders" and rich_text.get("annotations", {}).get("code") is True
        for block in blocks
        for rich_text in _block_rich_text(block)
    )
    assert any(
        rich_text.get("text", {}).get("content") == "chart"
        and rich_text.get("text", {}).get("link", {}).get("url") == "https://charts.test/revenue.png"
        for block in blocks
        for rich_text in _block_rich_text(block)
    )


def test_analysis_detail_blocks_render_markdown_tables_and_bold_text() -> None:
    status = {
        "confidenceScore": "medium",
        "finalAnswer": (
            "## Executive Summary and Explorations\n\n"
            "**MapleCloud Software (79.3)** dominates.\n\n"
            "## Detailed Research\n\n"
            "The *expansion revenue* signal improved while ~~legacy score~~ was removed.\n\n"
            "### Raw Metrics\n\n"
            "| Company | Revenue Growth | EBITDA Margin Δ |\n"
            "|---------|---------------|-----------------|\n"
            "| Canopy Industrial Supply | 12.95% | +2.72 pp |\n"
            "| MapleCloud Software | 10.33% | +2.83 pp |\n\n"
            "## Confidence Score: medium\n\n"
            "- Strong evidence."
        ),
        "gotchas": ["Strong evidence."],
    }

    blocks = notion_analysis._analysis_detail_blocks(status)
    detail = next(
        block
        for block in blocks
        if block["type"] == "heading_2" and block["heading_2"]["rich_text"][0]["text"]["content"] == "Detailed Research"
    )
    children = detail["heading_2"]["children"]

    assert detail["heading_2"]["is_toggleable"] is True
    assert any(block["type"] == "table" for block in children)
    assert any(
        rich_text.get("text", {}).get("content") == "MapleCloud Software (79.3)"
        and rich_text.get("annotations", {}).get("bold") is True
        for block in blocks
        for rich_text in _block_rich_text(block)
    )
    assert any(
        rich_text.get("text", {}).get("content") == "expansion revenue"
        and rich_text.get("annotations", {}).get("italic") is True
        for block in blocks
        for rich_text in _block_rich_text(block)
    )
    assert any(
        rich_text.get("text", {}).get("content") == "legacy score"
        and rich_text.get("annotations", {}).get("strikethrough") is True
        for block in blocks
        for rich_text in _block_rich_text(block)
    )


@pytest.mark.asyncio
async def test_comment_without_trigger_page_mention_is_processed(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    install = NotionInstallation(
        id="install-1",
        org_id="org-1",
        user_id="user-1",
        workspace_id="workspace-1",
        bot_id="bot-1",
        access_token_enc=b"encrypted",
        status="active",
    )
    config = NotionInstallationConfig(
        installation_id="install-1",
        parent_page_id=None,
        trigger_page_id="trigger-1",
        requests_data_source_id="ds-1",
        requests_database_page_id="db-1",
        enabled=True,
    )
    routed = RoutedNotionInstallation(installation=install, config=config, access_token="token-1")
    payload = {
        "id": "event-1",
        "entity": {"id": "comment-1"},
        "data": {"page_id": "page-1"},
    }
    comment = {"id": "comment-1", "discussion_id": "discussion-1", "rich_text": []}

    async def list_comments(*args, **kwargs):
        return [comment]

    async def create_comment(*args, **kwargs):
        calls.append(f"comment:{_rich_text_content(kwargs['rich_text'])}")

    async def fail_create_request_page(*args, **kwargs):
        raise AssertionError("greeting should not create a request page")

    monkeypatch.setattr(notion_client, "list_comments", list_comments)
    monkeypatch.setattr(notion_client, "create_comment", create_comment)
    monkeypatch.setattr(notion_client, "create_request_page", fail_create_request_page)
    monkeypatch.setattr(notion_client, "is_bot_comment", lambda _comment: False)
    monkeypatch.setattr(
        notion_client,
        "comment_has_page_mention",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("trigger page mention should not be checked")),
    )
    monkeypatch.setattr(notion_client, "extract_comment_text", lambda _comment: "hi")

    result = await notion_analysis.process_routed_comment_event(routed, payload, db=MagicMock())

    assert result.status == "processed"
    assert calls == ["comment:Hi. Send me a specific data question and I will run it through SignalPilot."]


@pytest.mark.asyncio
async def test_call_notebook_uses_runtime_pod_url_not_static_env(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[dict] = []
    runtime = NotebookRuntime(
        session_id="session-1",
        internal_base_url="http://10.0.0.5:2718/notebook/session-1",
        public_base_url="https://app.test/notebook/session-1",
    )

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"requestId": "request-1"}

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def request(self, method, url, headers=None, json=None):
            requests.append({"method": method, "url": url, "headers": headers, "json": json})
            return _Response()

    monkeypatch.setenv("SIGNALPILOT_NOTEBOOK_INTERNAL_URL", "http://old-notebook:2718")
    monkeypatch.setattr(notion_analysis.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(notion_analysis, "mint_internal_notebook_jwt", lambda *args, **kwargs: "jwt-1")

    result = await notion_analysis._call_notebook(
        runtime,
        "/api/notion-analysis/start",
        "org-1",
        "user-1",
        {"method": "POST", "json": {"prompt": "hello"}},
    )

    assert result == {"requestId": "request-1"}
    assert requests[0]["method"] == "POST"
    assert requests[0]["url"] == "http://10.0.0.5:2718/notebook/session-1/api/notion-analysis/start"
    assert "old-notebook" not in requests[0]["url"]
    assert requests[0]["headers"]["Authorization"] == "Bearer jwt-1"
