from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from gateway.analysis_delivery import DeliveryPacket, DeliveryResult, WorkerPlan, WorkerProgress
from gateway.db.models import NotionInstallation, NotionInstallationConfig
from gateway.notebooks.session_service import NotebookRuntime
from gateway.notion import analysis as notion_analysis
from gateway.notion import client as notion_client
from gateway.notion.webhooks import RoutedNotionInstallation


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

    async def update_page_properties(*args, **kwargs):
        return None

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
            confidence_score=1.0,
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
    assert render_api_keys == ["sk-ant-user"]


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


def test_analysis_detail_blocks_render_markdown_as_notion_blocks() -> None:
    status = {
        "confidenceScore": 0.82,
        "finalAnswer": (
            "## Executive Summary and Explorations\n\n"
            "- Revenue increased in `orders`.\n\n"
            "## Detailed Research\n\n"
            "See [chart](https://charts.test/revenue.png).\n\n"
            "## Confidence Score: 0.82\n\n"
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
        and block["heading_2"]["rich_text"][0]["text"]["content"] == "Confidence Score: 0.82"
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
        "confidenceScore": 0.72,
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
            "## Confidence Score: 0.72\n\n"
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
async def test_comment_without_trigger_page_mention_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
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
        calls.append("create_comment")

    async def call_notebook(*args, **kwargs):
        calls.append("call_notebook")
        return {}

    monkeypatch.setattr(notion_client, "list_comments", list_comments)
    monkeypatch.setattr(notion_client, "create_comment", create_comment)
    monkeypatch.setattr(notion_client, "is_bot_comment", lambda _comment: False)
    monkeypatch.setattr(notion_client, "comment_has_page_mention", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(notion_analysis, "_call_notebook", call_notebook)

    result = await notion_analysis.process_routed_comment_event(routed, payload, db=MagicMock())

    assert result.status == "ignored"
    assert result.reason == "trigger_page_not_mentioned"
    assert calls == []


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
