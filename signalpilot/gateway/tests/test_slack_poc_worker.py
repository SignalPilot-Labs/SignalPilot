from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import time
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from urllib.parse import parse_qs

import httpx
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.analysis_delivery import DeliveryResult, IntakeTerminalAction
from gateway.analysis_delivery.intake_actions import IntakeAnalysisStatus
from gateway.db.models import GatewayBase, GatewaySlackThreadWatch, SlackInstallation, SlackInstallationConfig
from gateway.slack_poc import worker as worker_module
from gateway.slack_poc.progress import COMPLETING_PROGRESS_TEXT, INITIAL_PROGRESS_TEXT
from gateway.slack_poc.worker import (
    SlackApiClient,
    SlackFileUpload,
    SlackPoCConfig,
    SlackPoCWorker,
    SlackRequest,
    _apply_local_runtime_defaults,
    _EventDeduper,
    _remove_bot_mention,
    create_http_app,
)


@pytest.fixture(autouse=True)
def clear_slack_dm_reset_epochs():
    worker_module._SLACK_DM_RESET_EPOCHS.clear()
    worker_module._SLACK_DEBOUNCE_PENDING.clear()
    worker_module._SLACK_CHART_BUNDLES.clear()
    yield
    worker_module._SLACK_DM_RESET_EPOCHS.clear()
    worker_module._SLACK_DEBOUNCE_PENDING.clear()
    worker_module._SLACK_CHART_BUNDLES.clear()


@pytest_asyncio.fixture
async def gateway_session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
def stub_slack_intake(monkeypatch: pytest.MonkeyPatch):
    async def intake_api_key(_self):
        return "sk-ant-test"

    async def run_intake_agent(session, **_kwargs):
        return SimpleNamespace(
            action=IntakeTerminalAction(
                name="start_notebook_analysis",
                arguments={"prompt": session.prompt, "output_mode": "answer"},
            )
        )

    monkeypatch.setattr(worker_module.SlackPoCWorker, "_intake_api_key_for_org", intake_api_key)
    monkeypatch.setattr(worker_module, "run_intake_agent", run_intake_agent)


def test_remove_bot_mention_removes_configured_mention_and_fallback_mentions() -> None:
    assert _remove_bot_mention("<@U123> analyze revenue <@U999>", "U123") == "analyze revenue"


def test_event_deduper_bounds_size_and_expires_old_events() -> None:
    deduper = _EventDeduper(max_size=2, ttl_seconds=10)

    assert deduper.add("event-1", now=100)
    assert not deduper.add("event-1", now=101)
    assert deduper.add("event-2", now=102)
    assert deduper.add("event-3", now=103)
    assert len(deduper) == 2
    assert deduper.add("event-1", now=104)

    expiring = _EventDeduper(max_size=10, ttl_seconds=5)
    assert expiring.add("event-1", now=100)
    assert expiring.add("event-1", now=106)


@pytest.mark.asyncio
async def test_run_http_server_defaults_to_loopback_host(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeServer:
        def __init__(self, config):
            captured["host"] = config.host

        async def serve(self) -> None:
            captured["served"] = True

    monkeypatch.delenv("SLACK_POC_HTTP_HOST", raising=False)
    monkeypatch.setattr(worker_module.uvicorn, "Server", FakeServer)

    await worker_module.run_http_server(
        SlackPoCConfig(
            bot_token="xoxb-test",
            app_token="xapp-test",
            signing_secret="test-secret",
            bot_user_id="UBOT",
        )
    )

    assert captured == {"host": worker_module.SLACK_POC_HTTP_DEFAULT_HOST, "served": True}


@pytest.mark.asyncio
async def test_slack_upload_file_uses_form_encoded_external_upload_flow() -> None:
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/files.getUploadURLExternal"):
            body = parse_qs(request.content.decode("utf-8"))
            assert body["filename"] == ["chart.png"]
            assert body["length"] == ["9"]
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "upload_url": "https://upload.slack.test/chart",
                    "file_id": "F123",
                },
            )
        if request.url.host == "upload.slack.test":
            assert request.content == b"png-bytes"
            assert request.headers["content-type"] == "image/png"
            return httpx.Response(200, text="OK")
        if request.url.path.endswith("/files.completeUploadExternal"):
            body = parse_qs(request.content.decode("utf-8"))
            assert json.loads(body["files"][0]) == [{"id": "F123", "title": "Revenue trend"}]
            assert body["channel_id"] == ["C1"]
            assert body["thread_ts"] == ["1.0"]
            return httpx.Response(200, json={"ok": True})
        raise AssertionError(f"unexpected request: {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    slack = SlackApiClient("xoxb-test", "xapp-test", http_client=client)
    try:
        await slack.upload_file(
            channel="C1",
            thread_ts="1.0",
            filename="chart.png",
            title="Revenue trend",
            content=b"png-bytes",
            content_type="image/png",
        )
    finally:
        await slack.aclose()

    assert [call.url.path for call in calls] == [
        "/api/files.getUploadURLExternal",
        "/chart",
        "/api/files.completeUploadExternal",
    ]


@pytest.mark.asyncio
async def test_slack_upload_files_completes_multiple_files_in_one_call() -> None:
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/files.getUploadURLExternal"):
            body = parse_qs(request.content.decode("utf-8"))
            filename = body["filename"][0]
            if filename == "revenue.png":
                assert body["length"] == ["9"]
                return httpx.Response(
                    200,
                    json={
                        "ok": True,
                        "upload_url": "https://upload.slack.test/revenue",
                        "file_id": "F-revenue",
                    },
                )
            if filename == "margin.png":
                assert body["length"] == ["10"]
                return httpx.Response(
                    200,
                    json={
                        "ok": True,
                        "upload_url": "https://upload.slack.test/margin",
                        "file_id": "F-margin",
                    },
                )
            raise AssertionError(f"unexpected filename: {filename}")
        if request.url.host == "upload.slack.test":
            if request.url.path == "/revenue":
                assert request.content == b"rev-bytes"
            elif request.url.path == "/margin":
                assert request.content == b"margin-img"
            else:
                raise AssertionError(f"unexpected upload URL: {request.url}")
            assert request.headers["content-type"] == "image/png"
            return httpx.Response(200, text="OK")
        if request.url.path.endswith("/files.completeUploadExternal"):
            body = parse_qs(request.content.decode("utf-8"))
            assert json.loads(body["files"][0]) == [
                {"id": "F-revenue", "title": "Revenue"},
                {"id": "F-margin", "title": "Margin"},
            ]
            assert body["channel_id"] == ["C1"]
            assert body["thread_ts"] == ["1.0"]
            return httpx.Response(200, json={"ok": True})
        raise AssertionError(f"unexpected request: {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    slack = SlackApiClient("xoxb-test", "xapp-test", http_client=client)
    try:
        file_ids = await slack.upload_files(
            channel="C1",
            thread_ts="1.0",
            files=[
                SlackFileUpload(
                    filename="revenue.png",
                    title="Revenue",
                    content=b"rev-bytes",
                    content_type="image/png",
                ),
                SlackFileUpload(
                    filename="margin.png",
                    title="Margin",
                    content=b"margin-img",
                    content_type="image/png",
                ),
            ],
        )
    finally:
        await slack.aclose()

    assert file_ids == ["F-revenue", "F-margin"]
    assert [call.url.path for call in calls] == [
        "/api/files.getUploadURLExternal",
        "/revenue",
        "/api/files.getUploadURLExternal",
        "/margin",
        "/api/files.completeUploadExternal",
    ]


@pytest.mark.asyncio
async def test_slack_upload_files_finalizes_private_files_for_chat_update() -> None:
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/files.getUploadURLExternal"):
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "upload_url": "https://upload.slack.test/chart",
                    "file_id": "F-chart",
                },
            )
        if request.url.host == "upload.slack.test":
            return httpx.Response(200, text="OK")
        if request.url.path.endswith("/files.completeUploadExternal"):
            body = parse_qs(request.content.decode("utf-8"))
            assert json.loads(body["files"][0]) == [{"id": "F-chart", "title": "Revenue"}]
            assert "channel_id" not in body
            assert "thread_ts" not in body
            return httpx.Response(200, json={"ok": True})
        if request.url.path.endswith("/chat.update"):
            body = json.loads(request.content.decode("utf-8"))
            assert body["channel"] == "C1"
            assert body["ts"] == "progress-ts"
            assert body["file_ids"] == ["F-chart"]
            return httpx.Response(200, json={"ok": True})
        raise AssertionError(f"unexpected request: {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    slack = SlackApiClient("xoxb-test", "xapp-test", http_client=client)
    try:
        file_ids = await slack.upload_files(
            channel=None,
            thread_ts=None,
            files=[
                SlackFileUpload(
                    filename="revenue.png",
                    title="Revenue",
                    content=b"png-bytes",
                    content_type="image/png",
                )
            ],
        )
        await slack.update_message(
            channel="C1",
            ts="progress-ts",
            text="Analysis complete",
            file_ids=file_ids,
        )
    finally:
        await slack.aclose()

    assert file_ids == ["F-chart"]
    assert [call.url.path for call in calls] == [
        "/api/files.getUploadURLExternal",
        "/chart",
        "/api/files.completeUploadExternal",
        "/api/chat.update",
    ]


@pytest.mark.asyncio
async def test_slack_read_methods_use_form_encoded_payloads() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = parse_qs(request.content.decode("utf-8"))
        if request.url.path.endswith("/chat.getPermalink"):
            assert body["channel"] == ["C1"]
            assert body["message_ts"] == ["1.0"]
            return httpx.Response(200, json={"ok": True, "permalink": "https://slack.test/p1"})
        if request.url.path.endswith("/conversations.replies"):
            assert body["channel"] == ["C1"]
            assert body["ts"] == ["1.0"]
            assert body["limit"] == ["20"]
            return httpx.Response(200, json={"ok": True, "messages": [{"text": "hello"}]})
        if request.url.path.endswith("/conversations.history"):
            assert body["channel"] == ["D1"]
            assert body["latest"] == ["2.0"]
            assert body["inclusive"] == ["true"]
            assert body["limit"] == ["20"]
            return httpx.Response(200, json={"ok": True, "messages": [{"text": "dm hello"}]})
        raise AssertionError(f"unexpected request: {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    slack = SlackApiClient("xoxb-test", "xapp-test", http_client=client)
    try:
        assert await slack.permalink(channel="C1", message_ts="1.0") == "https://slack.test/p1"
        assert await slack.thread_messages(channel="C1", thread_ts="1.0") == [{"text": "hello"}]
        assert await slack.channel_messages(channel="D1", latest="2.0") == [{"text": "dm hello"}]
    finally:
        await slack.aclose()


@pytest.mark.asyncio
async def test_slack_update_message_uses_chat_update() -> None:
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/chat.update"):
            body = json.loads(request.content.decode("utf-8"))
            assert body["channel"] == "C1"
            assert body["ts"] == "2.0"
            assert body["text"] == "Querying database..."
            assert body["mrkdwn"] is True
            return httpx.Response(200, json={"ok": True})
        raise AssertionError(f"unexpected request: {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    slack = SlackApiClient("xoxb-test", "xapp-test", http_client=client)
    try:
        await slack.update_message(channel="C1", ts="2.0", text="Querying database...")
    finally:
        await slack.aclose()

    assert [call.url.path for call in calls] == ["/api/chat.update"]


@pytest.mark.asyncio
async def test_slack_update_message_attaches_uploaded_files() -> None:
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/chat.update"):
            body = json.loads(request.content.decode("utf-8"))
            assert body["channel"] == "C1"
            assert body["ts"] == "2.0"
            assert body["text"] == "*Analysis complete*"
            assert body["file_ids"] == ["F-revenue", "F-margin"]
            return httpx.Response(200, json={"ok": True})
        raise AssertionError(f"unexpected request: {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    slack = SlackApiClient("xoxb-test", "xapp-test", http_client=client)
    try:
        await slack.update_message(
            channel="C1",
            ts="2.0",
            text="**Analysis complete**",
            file_ids=["F-revenue", "F-margin"],
        )
    finally:
        await slack.aclose()

    assert [call.url.path for call in calls] == ["/api/chat.update"]


@pytest.mark.asyncio
async def test_slack_messages_convert_standard_markdown_to_slack_mrkdwn() -> None:
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/chat.postMessage"):
            body = json.loads(request.content.decode("utf-8"))
            assert body["text"] == "*Revenue*\nUse *gross revenue* from <https://app.test/report|the report>."
            assert body["mrkdwn"] is True
            return httpx.Response(200, json={"ok": True, "ts": "2.0"})
        raise AssertionError(f"unexpected request: {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    slack = SlackApiClient("xoxb-test", "xapp-test", http_client=client)
    try:
        await slack.post_message(
            channel="C1",
            text="# Revenue\nUse **gross revenue** from [the report](https://app.test/report).",
        )
    finally:
        await slack.aclose()

    assert [call.url.path for call in calls] == ["/api/chat.postMessage"]


@pytest.mark.asyncio
async def test_slack_reactions_use_reactions_api_and_ignore_duplicate_remove_absence() -> None:
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        body = json.loads(request.content.decode("utf-8"))
        if request.url.path.endswith("/reactions.add"):
            assert body == {"channel": "C1", "timestamp": "1.0", "name": "eyes"}
            return httpx.Response(200, json={"ok": False, "error": "already_reacted"})
        if request.url.path.endswith("/reactions.remove"):
            assert body == {"channel": "C1", "timestamp": "1.0", "name": "eyes"}
            return httpx.Response(200, json={"ok": False, "error": "no_reaction"})
        raise AssertionError(f"unexpected request: {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    slack = SlackApiClient("xoxb-test", "xapp-test", http_client=client)
    try:
        await slack.add_reaction(channel="C1", timestamp="1.0", name="eyes")
        await slack.remove_reaction(channel="C1", timestamp="1.0", name="eyes")
    finally:
        await slack.aclose()

    assert [call.url.path for call in calls] == ["/api/reactions.add", "/api/reactions.remove"]


def test_cloud_mode_does_not_apply_local_notebook_direct_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
    monkeypatch.delenv("SP_NOTEBOOK_DIRECT_URL", raising=False)

    _apply_local_runtime_defaults()

    assert "SP_NOTEBOOK_DIRECT_URL" not in os.environ


def test_http_config_defaults_agent_start_delay_to_eight_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "test-secret")
    monkeypatch.setenv("SLACK_AGENT_START_DELAY_SECONDS", "")

    config = worker_module.load_http_config_from_env()

    assert config.agent_start_delay_seconds == 8.0


@pytest.mark.asyncio
async def test_worker_uses_explicit_config_user_id_before_notion_installation() -> None:
    worker = SlackPoCWorker(
        SlackPoCConfig(bot_token="xoxb-test", app_token="xapp-test", user_id="user-explicit"),
        AsyncMock(spec=SlackApiClient),
        AsyncMock(),
    )

    assert await worker._analysis_user_id(AsyncMock()) == "user-explicit"


@pytest.mark.asyncio
async def test_worker_returns_none_when_user_id_unset() -> None:
    worker = SlackPoCWorker(
        SlackPoCConfig(bot_token="xoxb-test", app_token="xapp-test", org_id="org-1"),
        AsyncMock(spec=SlackApiClient),
        AsyncMock(),
    )

    assert await worker._analysis_user_id("db") is None
    assert not hasattr(worker_module, "_latest_notion_installation_user_id")


@pytest.mark.asyncio
async def test_worker_releases_db_session_before_long_notebook_analysis(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    progress_seen = asyncio.Event()
    slack_events: list[tuple[str, str]] = []
    render_api_keys: list[str | None] = []

    class SessionContext:
        async def __aenter__(self):
            events.append("db_enter")
            return "db"

        async def __aexit__(self, exc_type, exc, tb):
            events.append("db_exit")
            return False

    def session_factory():
        return SessionContext()

    async def resolve_route(*args, **kwargs):
        events.append("resolve_route")
        return worker_module.notebook_analysis.AnalysisRoute(
            source="slack",
            request_id="slack-req-1",
            project_id="project-1",
            branch="analysis/slack/slack-req-1-analyze-revenue",
            default_branch="main",
            analysis_user_id="analysis:slack:slack-req-1",
        )

    async def ensure_session(
        db,
        *,
        org_id: str,
        source: str,
        request_id: str,
        project_id: str,
        branch: str,
        credential_user_id: str | None,
    ):
        assert db == "db"
        assert org_id == "org-1"
        assert source == "slack"
        assert request_id == "slack-req-1"
        assert project_id == "project-1"
        assert branch == "analysis/slack/slack-req-1-analyze-revenue"
        assert credential_user_id is None
        events.append("ensure_session")
        return worker_module.NotebookRuntime(
            session_id="session-1",
            internal_base_url="http://notebook.internal",
            public_base_url="https://app.test/notebook/session-1",
        )

    async def upsert_trail(*args, **kwargs):
        events.append("upsert")

    async def seed_trail(*args, **kwargs):
        events.append("seed")

    async def update_trail(*args, **kwargs):
        events.append("update")

    async def poll_analysis(*args, **kwargs):
        events.append("poll")
        assert events.index("db_exit") < events.index("start")
        await asyncio.wait_for(progress_seen.wait(), timeout=1)
        return {"status": "Done", "notionComment": "Done", "confidenceScore": "high"}

    monkeypatch.setattr(worker_module.notebook_analysis, "resolve_analysis_route_for_defaults", resolve_route)
    monkeypatch.setattr(worker_module, "ensure_analysis_notebook_session", ensure_session)
    monkeypatch.setattr(worker_module.notebook_analysis, "upsert_analysis_trail_seed", seed_trail)
    monkeypatch.setattr(worker_module.notebook_analysis, "upsert_analysis_trail_from_status", upsert_trail)
    monkeypatch.setattr(worker_module.notebook_analysis, "update_analysis_trail_from_status", update_trail)
    monkeypatch.setattr(worker_module.notebook_analysis, "_poll_analysis", poll_analysis)
    monkeypatch.setattr(worker_module.notebook_analysis, "_public_signalpilot_url", lambda url, runtime: url)
    monkeypatch.setattr(worker_module.notebook_analysis, "_with_public_chart_urls", lambda status, runtime: status)
    monkeypatch.setattr(worker_module, "resolve_anthropic_key", AsyncMock(return_value="sk-ant-org"))

    async def delivery_api_key_for_org(*args, **kwargs):
        assert args == ("db",)
        assert kwargs == {"org_id": "org-1"}
        return "sk-ant-org"

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

    monkeypatch.setattr(worker_module, "delivery_api_key_for_org", delivery_api_key_for_org)
    monkeypatch.setattr(worker_module, "render_delivery", render_delivery)

    slack = AsyncMock(spec=SlackApiClient)
    slack.thread_messages.return_value = []
    slack.add_reaction.return_value = None
    slack.remove_reaction.return_value = None

    async def post_message(**kwargs):
        text = kwargs["text"]
        slack_events.append(("post", text))
        if text == INITIAL_PROGRESS_TEXT:
            return "progress-ts"
        return f"ts-{len(slack_events)}"

    async def update_message(**kwargs):
        slack_events.append(("update", kwargs["text"]))

    slack.post_message.side_effect = post_message
    slack.update_message.side_effect = update_message
    worker = SlackPoCWorker(
        SlackPoCConfig(
            bot_token="xoxb-test",
            app_token="xapp-test",
            org_id="org-1",
            default_project_id="project-1",
        ),
        slack,
        session_factory,
    )

    async def start_analysis(*args, **kwargs):
        events.append("start")
        assert events[-2] == "db_exit"
        return {"requestId": "req-1", "trailUrl": "https://app.test/notebook/session-1"}

    monkeypatch.setattr(worker, "_start_analysis", start_analysis)
    monkeypatch.setattr(worker, "_post_busy_reply_if_active", AsyncMock(return_value=False))

    async def run_progress_reporter(*, stop_event, thread_id, source_prompt, channel_id, message_ts, user_id):
        assert thread_id == "session-slack-req-1"
        assert source_prompt == "analyze revenue"
        assert channel_id == "C1"
        assert message_ts == "progress-ts"
        assert user_id == "analysis:slack:slack-req-1"
        await slack.update_message(channel=channel_id, ts=message_ts, text="Querying database...")
        progress_seen.set()
        await stop_event.wait()

    monkeypatch.setattr(worker, "_run_progress_reporter", run_progress_reporter)

    await worker._process_request(
        SlackRequest(
            event_id="Ev1",
            team_id="T1",
            channel_id="C1",
            user_id="U1",
            text="analyze revenue",
            event_ts="1.0",
            thread_ts="1.0",
            source_url="https://slack.test/archives/C1/p10",
        )
    )

    assert events == [
        "db_enter",
        "db_exit",
        "db_enter",
        "resolve_route",
        "ensure_session",
        "seed",
        "db_exit",
        "start",
        "db_enter",
        "upsert",
        "db_exit",
        "poll",
        "db_enter",
        "update",
        "db_exit",
        "db_enter",
        "db_exit",
    ]
    assert slack_events[0] == ("post", INITIAL_PROGRESS_TEXT)
    assert ("update", "Querying database...") in slack_events[1:]
    assert ("update", COMPLETING_PROGRESS_TEXT) in slack_events[1:]
    assert slack_events[-1][0] == "update"
    assert "*Analysis complete*" in slack_events[-1][1]
    assert slack.post_message.await_count == 1
    assert render_api_keys == ["sk-ant-org"]
    slack.add_reaction.assert_any_await(channel="C1", timestamp="1.0", name="eyes")
    slack.add_reaction.assert_any_await(channel="C1", timestamp="1.0", name="white_check_mark")
    slack.remove_reaction.assert_any_await(channel="C1", timestamp="1.0", name="eyes")
    slack.remove_reaction.assert_any_await(channel="C1", timestamp="1.0", name="x")


@pytest.mark.asyncio
async def test_worker_adds_error_reaction_when_analysis_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    class SessionContext:
        async def __aenter__(self):
            return "db"

        async def __aexit__(self, exc_type, exc, tb):
            return False

    slack = AsyncMock(spec=SlackApiClient)
    slack.post_message.return_value = "progress-ts"
    slack.add_reaction.return_value = None
    slack.remove_reaction.return_value = None

    worker = SlackPoCWorker(
        SlackPoCConfig(bot_token="xoxb-test", app_token="xapp-test", org_id="org-1", user_id="user-1"),
        slack,
        lambda: SessionContext(),
    )

    async def fail_previous_messages(_request):
        raise RuntimeError("notebook auth missing")

    monkeypatch.setattr(worker, "_previous_thread_messages", fail_previous_messages)
    monkeypatch.setattr(worker, "_post_busy_reply_if_active", AsyncMock(return_value=False))
    monkeypatch.setattr(worker_module, "resolve_anthropic_key", AsyncMock(return_value="sk-ant-org"))

    await worker._process_request(
        SlackRequest(
            event_id="Ev1",
            team_id="T1",
            channel_id="C1",
            user_id="U1",
            text="analyze revenue",
            event_ts="1.0",
            thread_ts="1.0",
            source_url="https://slack.test/archives/C1/p10",
        )
    )

    slack.add_reaction.assert_any_await(channel="C1", timestamp="1.0", name="eyes")
    slack.add_reaction.assert_any_await(channel="C1", timestamp="1.0", name="x")
    added_reactions = [call.kwargs["name"] for call in slack.add_reaction.await_args_list]
    assert "white_check_mark" not in added_reactions
    slack.remove_reaction.assert_any_await(channel="C1", timestamp="1.0", name="eyes")
    slack.remove_reaction.assert_any_await(channel="C1", timestamp="1.0", name="white_check_mark")
    slack.update_message.assert_awaited_once()
    assert "could not complete the analysis" in slack.update_message.call_args.kwargs["text"]


@pytest.mark.asyncio
async def test_worker_posts_admin_nudge_when_org_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    class SessionContext:
        async def __aenter__(self):
            return "db"

        async def __aexit__(self, exc_type, exc, tb):
            return False

    slack = AsyncMock(spec=SlackApiClient)
    slack.post_message.return_value = "nudge-ts"
    slack.add_reaction.return_value = None
    slack.remove_reaction.return_value = None
    monkeypatch.setenv("SP_WEB_URL", "https://app.test")
    monkeypatch.setattr(worker_module, "resolve_anthropic_key", AsyncMock(return_value=None))

    worker = SlackPoCWorker(
        SlackPoCConfig(bot_token="xoxb-test", app_token="xapp-test", org_id="org-1"),
        slack,
        lambda: SessionContext(),
    )
    previous_messages = AsyncMock()
    monkeypatch.setattr(worker, "_previous_thread_messages", previous_messages)
    monkeypatch.setattr(worker, "_post_busy_reply_if_active", AsyncMock(return_value=False))

    await worker._process_request(
        SlackRequest(
            event_id="Ev1",
            team_id="T1",
            channel_id="C1",
            user_id="U1",
            text="analyze revenue",
            event_ts="1.0",
            thread_ts="1.0",
            source_url="https://slack.test/archives/C1/p10",
        )
    )

    slack.post_message.assert_awaited_once()
    message = slack.post_message.await_args.kwargs["text"]
    assert message == (
        "SignalPilot needs an Anthropic API key. "
        "Ask your admin to add it on the integrations page: https://app.test/integrations"
    )
    assert "Notion" not in message
    previous_messages.assert_not_awaited()
    slack.add_reaction.assert_any_await(channel="C1", timestamp="1.0", name="x")


@pytest.mark.asyncio
async def test_worker_uploads_chart_images_as_slack_thread_files(monkeypatch: pytest.MonkeyPatch) -> None:
    slack = AsyncMock(spec=SlackApiClient)
    slack.fetch_bytes.return_value = (b"png-bytes", "image/png")
    slack.upload_files.return_value = ["F-revenue"]
    worker = SlackPoCWorker(
        SlackPoCConfig(bot_token="xoxb-test", app_token="xapp-test", bot_user_id="UBOT"),
        slack,
        AsyncMock(),
    )

    monkeypatch.setattr(
        "gateway.slack_poc.worker.notebook_analysis._internal_signalpilot_url",
        lambda url, runtime: f"http://notebook.test{url}",
    )

    await worker._post_chart_attachments(
        SlackRequest(
            event_id="Ev1",
            team_id="T1",
            channel_id="C1",
            user_id="U1",
            text="analyze revenue",
            event_ts="1.0",
            thread_ts="1.0",
            source_url="slack://channel/C1/p10",
        ),
        {
            "notionCharts": [
                {
                    "title": "Revenue trend",
                    "url": "/api/notion-analysis/chart/notion-1/chart.png",
                }
            ]
        },
        AsyncMock(),
    )

    slack.fetch_bytes.assert_awaited_once_with("http://notebook.test/api/notion-analysis/chart/notion-1/chart.png")
    slack.upload_files.assert_awaited_once()
    kwargs = slack.upload_files.await_args.kwargs
    assert kwargs["channel"] == "C1"
    assert kwargs["thread_ts"] == "1.0"
    assert kwargs["files"] == [
        SlackFileUpload(
            filename="revenue-trend.png",
            title="Revenue trend",
            content=b"png-bytes",
            content_type="image/png",
        )
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("channel_id", "channel_type", "thread_ts"),
    [("C1", "channel", "1.0"), ("D1", "im", "")],
)
async def test_worker_attaches_charts_when_updating_final_progress(
    monkeypatch: pytest.MonkeyPatch,
    channel_id: str,
    channel_type: str,
    thread_ts: str,
) -> None:
    slack = AsyncMock(spec=SlackApiClient)
    slack.fetch_bytes.return_value = (b"png-bytes", "image/png")
    slack.upload_files.return_value = ["F-revenue"]
    worker = SlackPoCWorker(
        SlackPoCConfig(bot_token="xoxb-test", app_token="xapp-test", bot_user_id="UBOT"),
        slack,
        AsyncMock(),
    )

    monkeypatch.setattr(
        "gateway.slack_poc.worker.notebook_analysis._internal_signalpilot_url",
        lambda url, runtime: f"http://notebook.test{url}",
    )

    attached = await worker._post_chart_attachments(
        SlackRequest(
            event_id="Ev1",
            team_id="T1",
            channel_id=channel_id,
            user_id="U1",
            text="analyze revenue",
            event_ts="1.0",
            thread_ts=thread_ts,
            source_url=f"slack://channel/{channel_id}/p10",
            channel_type=channel_type,
        ),
        {
            "notionCharts": [
                {
                    "title": "Revenue trend",
                    "url": "/api/notion-analysis/chart/notion-1/chart.png",
                }
            ]
        },
        AsyncMock(),
        message_ts="progress-ts",
        message_text="Analysis complete",
    )

    assert attached is True
    slack.upload_files.assert_awaited_once()
    upload = slack.upload_files.await_args.kwargs
    assert upload["channel"] is None
    assert upload["thread_ts"] is None
    slack.update_message.assert_awaited_once_with(
        channel=channel_id,
        ts="progress-ts",
        text="Analysis complete",
        file_ids=["F-revenue"],
    )
    slack.post_message.assert_not_called()


@pytest.mark.asyncio
async def test_worker_omits_placeholder_chart_file_titles(monkeypatch: pytest.MonkeyPatch) -> None:
    slack = AsyncMock(spec=SlackApiClient)
    slack.fetch_bytes.return_value = (b"png-bytes", "image/png")
    slack.upload_files.return_value = ["F-chart"]
    worker = SlackPoCWorker(
        SlackPoCConfig(bot_token="xoxb-test", app_token="xapp-test", bot_user_id="UBOT"),
        slack,
        AsyncMock(),
    )

    monkeypatch.setattr(
        "gateway.slack_poc.worker.notebook_analysis._internal_signalpilot_url",
        lambda url, runtime: f"http://notebook.test{url}",
    )

    await worker._post_chart_attachments(
        SlackRequest(
            event_id="Ev1",
            team_id="T1",
            channel_id="C1",
            user_id="U1",
            text="analyze revenue",
            event_ts="1.0",
            thread_ts="1.0",
            source_url="slack://channel/C1/p10",
        ),
        {
            "notionCharts": [
                {
                    "title": "Notebook image 1",
                    "fileName": "notebook-image-1.png",
                    "url": "/api/notion-analysis/chart/notion-1/image-1.png",
                }
            ]
        },
        AsyncMock(),
    )

    slack.upload_files.assert_awaited_once()
    files = slack.upload_files.await_args.kwargs["files"]
    assert files[0].title is None
    assert files[0].filename == "chart-1.png"
    slack.post_message.assert_not_called()


@pytest.mark.asyncio
async def test_worker_replaces_previous_chart_bundle_on_followup(monkeypatch: pytest.MonkeyPatch) -> None:
    slack = AsyncMock(spec=SlackApiClient)
    slack.fetch_bytes.return_value = (b"png-bytes", "image/png")
    slack.upload_files.side_effect = [["F-old-1", "F-old-2"], ["F-new"]]
    slack.delete_file.side_effect = RuntimeError("delete failed")
    worker = SlackPoCWorker(
        SlackPoCConfig(bot_token="xoxb-test", app_token="xapp-test", bot_user_id="UBOT"),
        slack,
        AsyncMock(),
    )

    monkeypatch.setattr(
        "gateway.slack_poc.worker.notebook_analysis._internal_signalpilot_url",
        lambda url, runtime: f"http://notebook.test{url}",
    )
    request = SlackRequest(
        event_id="Ev1",
        team_id="T1",
        channel_id="C1",
        user_id="U1",
        text="analyze revenue",
        event_ts="1.0",
        thread_ts="1.0",
        source_url="slack://channel/C1/p10",
        discussion_id="slack:T1:C1:1.0",
    )

    await worker._post_chart_attachments(
        request,
        {
            "notionCharts": [
                {"title": "Revenue trend", "url": "/api/notion-analysis/chart/notion-1/revenue.png"},
                {"title": "Margin trend", "url": "/api/notion-analysis/chart/notion-1/margin.png"},
            ]
        },
        AsyncMock(),
    )
    await worker._post_chart_attachments(
        request,
        {
            "notionCharts": [
                {"title": "Latest revenue", "url": "/api/notion-analysis/chart/notion-2/revenue.png"},
            ]
        },
        AsyncMock(),
    )

    assert slack.upload_files.await_count == 2
    first_upload = slack.upload_files.await_args_list[0].kwargs
    second_upload = slack.upload_files.await_args_list[1].kwargs
    assert len(first_upload["files"]) == 2
    assert len(second_upload["files"]) == 1
    slack.delete_file.assert_any_await(file_id="F-old-1")
    slack.delete_file.assert_any_await(file_id="F-old-2")
    assert slack.post_message.await_count == 0


def test_http_events_url_verification_returns_challenge() -> None:
    signing_secret = "test-secret"
    payload = {"type": "url_verification", "challenge": "challenge-value"}
    raw_body = json.dumps(payload).encode("utf-8")
    timestamp = str(int(time.time()))
    signature = _slack_signature(signing_secret, timestamp, raw_body)
    app = create_http_app(
        SlackPoCConfig(
            bot_token="xoxb-test",
            app_token="xapp-test",
            signing_secret=signing_secret,
            bot_user_id="UBOT",
        ),
        slack=AsyncMock(spec=SlackApiClient),
    )

    with TestClient(app) as client:
        response = client.post(
            "/slack/events",
            content=raw_body,
            headers={
                "x-slack-request-timestamp": timestamp,
                "x-slack-signature": signature,
                "content-type": "application/json",
            },
        )

    assert response.status_code == 200
    assert response.text == "challenge-value"


def test_http_events_rejects_invalid_signature() -> None:
    app = create_http_app(
        SlackPoCConfig(
            bot_token="xoxb-test",
            app_token="xapp-test",
            signing_secret="test-secret",
            bot_user_id="UBOT",
        ),
        slack=AsyncMock(spec=SlackApiClient),
    )

    with TestClient(app) as client:
        response = client.post(
            "/slack/events",
            json={"type": "url_verification", "challenge": "challenge-value"},
            headers={
                "x-slack-request-timestamp": str(int(time.time())),
                "x-slack-signature": "v0=bad",
            },
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_self_serve_dispatch_uses_stored_installation(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(UTC)
    install = SlackInstallation(
        id="slack-install-1",
        org_id="org-1",
        user_id="user-1",
        team_id="T1",
        team_name="Demo",
        app_id="A1",
        bot_user_id="UBOT",
        bot_access_token_enc=b"encrypted",
        scopes=["app_mentions:read", "chat:write"],
        status="active",
        created_at=now,
        updated_at=now,
    )
    config = SlackInstallationConfig(
        installation_id="slack-install-1",
        enabled=True,
        default_project_id="project-1",
        default_branch="main",
        analysis_branch_mode="per_request",
        allowed_channel_ids=["C1"],
    )
    captured: list[SlackPoCConfig] = []

    class Factory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return object()

        async def __aexit__(self, *_args):
            return None

    async def records(_db, team_id: str):
        assert team_id == "T1"
        return [(install, config, "installed-bot-token")]

    async def handle(self, payload):
        captured.append(self.config)
        assert payload["event"]["text"] == "<@UBOT> analyze revenue"

    async def drain(self):
        return None

    monkeypatch.setattr(worker_module, "get_session_factory", lambda: Factory())
    monkeypatch.setattr(worker_module.slack_store, "list_active_installation_records_for_team", records)
    monkeypatch.setattr(SlackPoCWorker, "handle_events_api_payload", handle)
    monkeypatch.setattr(SlackPoCWorker, "drain", drain)

    await worker_module._dispatch_self_serve_payload(
        {
            "event_id": "Ev1",
            "team_id": "T1",
            "event": {
                "type": "app_mention",
                "team": "T1",
                "channel": "C1",
                "user": "U1",
                "text": "<@UBOT> analyze revenue",
                "ts": "1.0",
            },
        },
        SlackPoCConfig(signing_secret="secret", ack_text="I'm on it."),
    )

    assert len(captured) == 1
    assert captured[0].bot_token == "installed-bot-token"
    assert captured[0].org_id == "org-1"
    assert captured[0].user_id == "user-1"
    assert captured[0].bot_user_id == "UBOT"
    assert captured[0].default_project_id == "project-1"
    assert captured[0].allowed_channel_ids == frozenset({"C1"})


@pytest.mark.asyncio
async def test_self_serve_dispatch_rejects_ambiguous_installations(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(UTC)
    install_1 = SlackInstallation(
        id="slack-install-1",
        org_id="org-1",
        user_id="user-1",
        team_id="T1",
        app_id="A1",
        bot_user_id="UBOT1",
        bot_access_token_enc=b"encrypted",
        scopes=[],
        status="active",
        created_at=now,
        updated_at=now,
    )
    install_2 = SlackInstallation(
        id="slack-install-2",
        org_id="org-2",
        user_id="user-2",
        team_id="T1",
        app_id="A1",
        bot_user_id="UBOT2",
        bot_access_token_enc=b"encrypted",
        scopes=[],
        status="active",
        created_at=now,
        updated_at=now,
    )
    config = SlackInstallationConfig(
        installation_id="slack-install-1",
        enabled=True,
        default_project_id="project-1",
        default_branch="main",
        analysis_branch_mode="per_request",
        allowed_channel_ids=[],
    )

    class Factory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return object()

        async def __aexit__(self, *_args):
            return None

    async def records(_db, team_id: str):
        assert team_id == "T1"
        return [(install_1, config, "bot-token-1"), (install_2, config, "bot-token-2")]

    async def fail_handle(self, payload):
        raise AssertionError("ambiguous install should not dispatch")

    monkeypatch.setattr(worker_module, "get_session_factory", lambda: Factory())
    monkeypatch.setattr(worker_module.slack_store, "list_active_installation_records_for_team", records)
    monkeypatch.setattr(SlackPoCWorker, "handle_events_api_payload", fail_handle)

    await worker_module._dispatch_self_serve_payload(
        {
            "event_id": "Ev1",
            "team_id": "T1",
            "event": {
                "type": "app_mention",
                "team": "T1",
                "channel": "C1",
                "user": "U1",
                "text": "<@UBOT> analyze revenue",
                "ts": "1.0",
            },
        },
        SlackPoCConfig(signing_secret="secret"),
    )


@pytest.mark.asyncio
async def test_worker_ignores_non_mention_channel_message() -> None:
    slack = AsyncMock(spec=SlackApiClient)
    worker = SlackPoCWorker(
        SlackPoCConfig(bot_token="xoxb-test", app_token="xapp-test", bot_user_id="UBOT"),
        slack,
        AsyncMock(),
    )

    await worker.handle_events_api_payload(
        {
            "event_id": "Ev1",
            "team_id": "T1",
            "event": {
                "type": "message",
                "channel": "C1",
                "user": "U1",
                "text": "hello",
                "ts": "1.0",
            },
        }
    )

    slack.post_message.assert_not_called()


@pytest.mark.asyncio
async def test_worker_posts_empty_prompt_guidance_for_bare_mention() -> None:
    slack = AsyncMock(spec=SlackApiClient)
    slack.permalink.return_value = "https://slack.test/archives/C1/p1000"
    worker = SlackPoCWorker(
        SlackPoCConfig(bot_token="xoxb-test", app_token="xapp-test", bot_user_id="UBOT"),
        slack,
        AsyncMock(),
    )

    await worker.handle_events_api_payload(
        {
            "event_id": "Ev1",
            "team_id": "T1",
            "event": {
                "type": "app_mention",
                "channel": "C1",
                "user": "U1",
                "text": "<@UBOT>",
                "ts": "1.0",
            },
        }
    )

    slack.post_message.assert_called_once()
    assert "Ask me a data question" in slack.post_message.call_args.kwargs["text"]


@pytest.mark.asyncio
async def test_worker_intake_direct_reply_does_not_spawn_analysis(monkeypatch: pytest.MonkeyPatch) -> None:
    slack = AsyncMock(spec=SlackApiClient)
    slack.permalink.return_value = "https://slack.test/archives/C1/p1000"
    worker = SlackPoCWorker(
        SlackPoCConfig(bot_token="xoxb-test", app_token="xapp-test", bot_user_id="UBOT"),
        slack,
        AsyncMock(),
    )

    async def run_intake_agent(_session, **_kwargs):
        return SimpleNamespace(
            action=IntakeTerminalAction(name="respond_to_user", arguments={"text": "Hi. What should I check?"})
        )

    async def fail_process_request(_request):
        raise AssertionError("direct reply should not spawn analysis")

    monkeypatch.setattr(worker_module, "run_intake_agent", run_intake_agent)
    monkeypatch.setattr(worker, "_process_request", fail_process_request)

    await worker.handle_events_api_payload(
        {
            "event_id": "Ev1",
            "team_id": "T1",
            "event": {
                "type": "app_mention",
                "channel": "C1",
                "user": "U1",
                "text": "<@UBOT> hi",
                "ts": "1.0",
            },
        }
    )
    await worker.drain()

    slack.post_message.assert_awaited_once()
    assert slack.post_message.call_args.kwargs["text"] == "Hi. What should I check?"


@pytest.mark.asyncio
async def test_worker_zero_delay_intake_runs_outside_event_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    slack = AsyncMock(spec=SlackApiClient)
    slack.permalink.return_value = "https://slack.test/archives/C1/p1000"
    intake_started = asyncio.Event()
    release_intake = asyncio.Event()
    worker = SlackPoCWorker(
        SlackPoCConfig(
            bot_token="xoxb-test",
            app_token="xapp-test",
            bot_user_id="UBOT",
            agent_start_delay_seconds=0,
        ),
        slack,
        AsyncMock(),
    )

    async def handle_intake(_request: SlackRequest) -> None:
        intake_started.set()
        await release_intake.wait()

    monkeypatch.setattr(worker, "_handle_intake", handle_intake)

    await asyncio.wait_for(
        worker.handle_events_api_payload(
            {
                "event_id": "Ev-zero-delay",
                "team_id": "T1",
                "event": {
                    "type": "app_mention",
                    "channel": "C1",
                    "user": "U1",
                    "text": "<@UBOT> hello",
                    "ts": "1.0",
                },
            }
        ),
        timeout=0.1,
    )
    await asyncio.wait_for(intake_started.wait(), timeout=0.1)

    release_intake.set()
    await worker.drain()


@pytest.mark.asyncio
async def test_worker_intake_can_start_analysis_for_old_ambiguous_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    slack = AsyncMock(spec=SlackApiClient)
    slack.permalink.return_value = "https://slack.test/archives/C1/p1000"
    processed = []
    worker = SlackPoCWorker(
        SlackPoCConfig(bot_token="xoxb-test", app_token="xapp-test", bot_user_id="UBOT"),
        slack,
        AsyncMock(),
    )

    async def process_request(request):
        processed.append(request)

    monkeypatch.setattr(worker, "_process_request", process_request)

    await worker.handle_events_api_payload(
        {
            "event_id": "Ev1",
            "team_id": "T1",
            "event": {
                "type": "app_mention",
                "channel": "C1",
                "user": "U1",
                "text": "<@UBOT> revenue",
                "ts": "1.0",
            },
        }
    )
    await worker.drain()

    assert len(processed) == 1
    assert processed[0].text == "revenue"
    slack.post_message.assert_not_called()


@pytest.mark.asyncio
async def test_worker_debounces_dm_messages_and_moves_eye_reaction(monkeypatch: pytest.MonkeyPatch) -> None:
    slack = AsyncMock(spec=SlackApiClient)
    slack.permalink.side_effect = lambda *, channel, message_ts: f"https://slack.test/archives/{channel}/p{message_ts}"
    processed: list[SlackRequest] = []
    worker = SlackPoCWorker(
        SlackPoCConfig(
            bot_token="xoxb-test",
            app_token="xapp-test",
            bot_user_id="UBOT",
            agent_start_delay_seconds=0.01,
        ),
        slack,
        AsyncMock(),
    )

    async def no_latest_dm_trail(_prefix: str):
        return None

    async def handle_intake(request: SlackRequest) -> SlackRequest:
        return request

    async def process_request(request: SlackRequest) -> None:
        processed.append(request)

    monkeypatch.setattr(worker, "_latest_slack_trail_for_source_thread_prefix", no_latest_dm_trail)
    monkeypatch.setattr(worker, "_handle_intake", handle_intake)
    monkeypatch.setattr(worker, "_process_request", process_request)

    await worker.handle_events_api_payload(
        {
            "event_id": "Ev1",
            "team_id": "T1",
            "event": {
                "type": "message",
                "channel_type": "im",
                "channel": "D1",
                "user": "U1",
                "text": "build a dashboard",
                "ts": "1.0",
            },
        }
    )
    await worker.handle_events_api_payload(
        {
            "event_id": "Ev2",
            "team_id": "T1",
            "event": {
                "type": "message",
                "channel_type": "im",
                "channel": "D1",
                "user": "U1",
                "text": "with revenue data",
                "ts": "2.0",
            },
        }
    )
    await worker.drain()

    assert [request.event_id for request in processed] == ["Ev2"]
    assert processed[0].text == "with revenue data"
    slack.add_reaction.assert_any_await(channel="D1", timestamp="1.0", name="eyes")
    slack.remove_reaction.assert_any_await(channel="D1", timestamp="1.0", name="eyes")
    slack.add_reaction.assert_any_await(channel="D1", timestamp="2.0", name="eyes")


@pytest.mark.asyncio
async def test_worker_debounces_watched_public_thread_reply_and_moves_eye_reaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slack = AsyncMock(spec=SlackApiClient)
    slack.permalink.side_effect = lambda *, channel, message_ts: f"https://slack.test/archives/{channel}/p{message_ts}"
    processed: list[SlackRequest] = []
    worker = SlackPoCWorker(
        SlackPoCConfig(
            bot_token="xoxb-test",
            app_token="xapp-test",
            bot_user_id="UBOT",
            agent_start_delay_seconds=0.01,
        ),
        slack,
        AsyncMock(),
    )

    async def no_latest_thread(_source_thread_id: str):
        return None

    async def handle_intake(request: SlackRequest) -> SlackRequest:
        return request

    async def process_request(request: SlackRequest) -> None:
        processed.append(request)

    monkeypatch.setattr(worker, "_latest_slack_trail_for_source_thread_id", no_latest_thread)
    monkeypatch.setattr(worker, "_handle_intake", handle_intake)
    monkeypatch.setattr(worker, "_process_request", process_request)

    await worker.handle_events_api_payload(
        {
            "event_id": "Ev1",
            "team_id": "T1",
            "event": {
                "type": "app_mention",
                "channel_type": "channel",
                "channel": "C1",
                "user": "U1",
                "text": "<@UBOT> analyze revenue",
                "ts": "1.0",
            },
        }
    )
    await worker.handle_events_api_payload(
        {
            "event_id": "Ev2",
            "team_id": "T1",
            "event": {
                "type": "message",
                "channel_type": "channel",
                "channel": "C1",
                "user": "U1",
                "text": "use gross revenue",
                "thread_ts": "1.0",
                "ts": "2.0",
            },
        }
    )
    await worker.drain()

    assert [request.event_id for request in processed] == ["Ev2"]
    assert processed[0].text == "use gross revenue"
    assert processed[0].thread_ts == "1.0"
    assert processed[0].discussion_id == "slack:T1:C1:1.0"
    slack.add_reaction.assert_any_await(channel="C1", timestamp="1.0", name="eyes")
    slack.remove_reaction.assert_any_await(channel="C1", timestamp="1.0", name="eyes")
    slack.add_reaction.assert_any_await(channel="C1", timestamp="2.0", name="eyes")


@pytest.mark.asyncio
async def test_worker_debounced_thread_react_or_ignore_clears_eye_reaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slack = AsyncMock(spec=SlackApiClient)
    slack.permalink.side_effect = lambda *, channel, message_ts: f"https://slack.test/archives/{channel}/p{message_ts}"
    slack.thread_messages.return_value = []
    worker = SlackPoCWorker(
        SlackPoCConfig(
            bot_token="xoxb-test",
            app_token="xapp-test",
            bot_user_id="UBOT",
            agent_start_delay_seconds=0.01,
        ),
        slack,
        AsyncMock(),
    )

    async def no_latest_thread(_source_thread_id: str):
        return None

    async def run_intake_agent(_session, **_kwargs):
        return SimpleNamespace(
            action=IntakeTerminalAction(
                name="react_or_ignore",
                arguments={"mode": "ignore"},
            )
        )

    async def fail_process_request(_request):
        raise AssertionError("react_or_ignore should not spawn analysis")

    monkeypatch.setattr(worker, "_latest_slack_trail_for_source_thread_id", no_latest_thread)
    monkeypatch.setattr(worker_module, "run_intake_agent", run_intake_agent)
    monkeypatch.setattr(worker, "_process_request", fail_process_request)

    await worker.handle_events_api_payload(
        {
            "event_id": "Ev1",
            "team_id": "T1",
            "event": {
                "type": "app_mention",
                "channel_type": "channel",
                "channel": "C1",
                "user": "U1",
                "text": "<@UBOT> analyze revenue",
                "ts": "1.0",
            },
        }
    )
    await worker.handle_events_api_payload(
        {
            "event_id": "Ev2",
            "team_id": "T1",
            "event": {
                "type": "message",
                "channel_type": "channel",
                "channel": "C1",
                "user": "U1",
                "text": "thanks",
                "thread_ts": "1.0",
                "ts": "2.0",
            },
        }
    )
    await worker.drain()

    slack.add_reaction.assert_any_await(channel="C1", timestamp="2.0", name="eyes")
    slack.remove_reaction.assert_any_await(channel="C1", timestamp="2.0", name="eyes")
    slack.post_message.assert_not_called()


@pytest.mark.asyncio
async def test_worker_accepts_plain_thread_reply_from_durable_watch_without_slack_trail(
    monkeypatch: pytest.MonkeyPatch,
    gateway_session_factory,
) -> None:
    slack = AsyncMock(spec=SlackApiClient)
    slack.permalink.side_effect = lambda *, channel, message_ts: f"https://slack.test/archives/{channel}/p{message_ts}"
    first_worker = SlackPoCWorker(
        SlackPoCConfig(bot_token="xoxb-test", app_token="xapp-test", bot_user_id="UBOT", org_id="org-1"),
        slack,
        gateway_session_factory,
    )
    second_worker = SlackPoCWorker(
        SlackPoCConfig(bot_token="xoxb-test", app_token="xapp-test", bot_user_id="UBOT", org_id="org-1"),
        slack,
        gateway_session_factory,
    )
    processed: list[SlackRequest] = []

    async def no_thread(_source_thread_id: str):
        return None

    async def ignore_intake(_request: SlackRequest) -> None:
        return None

    async def handle_intake(request: SlackRequest) -> SlackRequest:
        return request

    async def process_request(request: SlackRequest) -> None:
        processed.append(request)

    monkeypatch.setattr(first_worker, "_handle_intake", ignore_intake)
    monkeypatch.setattr(second_worker, "_latest_slack_trail_for_source_thread_id", no_thread)
    monkeypatch.setattr(second_worker, "_handle_intake", handle_intake)
    monkeypatch.setattr(second_worker, "_process_request", process_request)

    await first_worker.handle_events_api_payload(
        {
            "event_id": "Ev1",
            "team_id": "T1",
            "event": {
                "type": "app_mention",
                "channel_type": "channel",
                "channel": "C1",
                "user": "U1",
                "text": "<@UBOT> analyze revenue",
                "ts": "1.0",
            },
        }
    )
    await first_worker.drain()

    async with gateway_session_factory() as db:
        watch = (
            await db.execute(
                select(GatewaySlackThreadWatch).where(
                    GatewaySlackThreadWatch.org_id == "org-1",
                    GatewaySlackThreadWatch.team_id == "T1",
                    GatewaySlackThreadWatch.channel_id == "C1",
                    GatewaySlackThreadWatch.thread_ts == "1.0",
                )
            )
        ).scalar_one()
        assert watch.status == "active"
        assert watch.source_thread_id == "slack:T1:C1:1.0"

    await second_worker.handle_events_api_payload(
        {
            "event_id": "Ev2",
            "team_id": "T1",
            "event": {
                "type": "message",
                "channel_type": "channel",
                "channel": "C1",
                "user": "U1",
                "text": "show revenue by month",
                "thread_ts": "1.0",
                "ts": "2.0",
            },
        }
    )
    await second_worker.drain()

    assert [request.event_id for request in processed] == ["Ev2"]
    assert processed[0].discussion_id == "slack:T1:C1:1.0"
    assert processed[0].is_continuation is True


@pytest.mark.asyncio
async def test_worker_schedules_valid_app_mention(monkeypatch: pytest.MonkeyPatch) -> None:
    slack = AsyncMock(spec=SlackApiClient)
    slack.permalink.return_value = "https://slack.test/archives/C1/p1000"
    processed = []
    worker = SlackPoCWorker(
        SlackPoCConfig(bot_token="xoxb-test", app_token="xapp-test", bot_user_id="UBOT"),
        slack,
        AsyncMock(),
    )

    async def process_request(request):
        processed.append(request)

    monkeypatch.setattr(worker, "_process_request", process_request)

    await worker.handle_events_api_payload(
        {
            "event_id": "Ev1",
            "team_id": "T1",
            "event": {
                "type": "app_mention",
                "channel": "C1",
                "user": "U1",
                "text": "<@UBOT> analyze revenue",
                "ts": "1.0",
            },
        }
    )
    await worker.drain()

    assert len(processed) == 1
    assert processed[0].text == "analyze revenue"
    assert processed[0].thread_ts == "1.0"


@pytest.mark.asyncio
async def test_worker_dm_first_message_creates_epoch_discussion_id(monkeypatch: pytest.MonkeyPatch) -> None:
    slack = AsyncMock(spec=SlackApiClient)
    slack.permalink.return_value = "https://slack.test/archives/D1/p1000"
    processed = []
    worker = SlackPoCWorker(
        SlackPoCConfig(bot_token="xoxb-test", app_token="xapp-test", bot_user_id="UBOT"),
        slack,
        AsyncMock(),
    )

    async def latest_dm_prefix(prefix: str):
        assert prefix == "slack:T1:D1:dm-"
        return

    async def process_request(request):
        processed.append(request)

    monkeypatch.setattr(worker, "_latest_slack_trail_for_source_thread_prefix", latest_dm_prefix)
    monkeypatch.setattr(worker, "_process_request", process_request)

    await worker.handle_events_api_payload(
        {
            "event_id": "Ev1",
            "team_id": "T1",
            "event": {
                "type": "message",
                "channel_type": "im",
                "channel": "D1",
                "user": "U1",
                "text": "analyze revenue by month",
                "ts": "1.0",
            },
        }
    )
    await worker.drain()

    assert len(processed) == 1
    assert processed[0].discussion_id == "slack:T1:D1:dm-1.0"
    assert processed[0].channel_type == "im"
    assert processed[0].is_continuation is False


@pytest.mark.asyncio
async def test_worker_dm_followup_reuses_latest_dm_trail(monkeypatch: pytest.MonkeyPatch) -> None:
    slack = AsyncMock(spec=SlackApiClient)
    slack.permalink.return_value = "https://slack.test/archives/D1/p2000"
    processed = []
    worker = SlackPoCWorker(
        SlackPoCConfig(bot_token="xoxb-test", app_token="xapp-test", bot_user_id="UBOT"),
        slack,
        AsyncMock(),
    )

    async def latest_dm_prefix(_prefix: str):
        return SimpleNamespace(source_thread_id="slack:T1:D1:dm-1.0")

    async def process_request(request):
        processed.append(request)

    monkeypatch.setattr(worker, "_latest_slack_trail_for_source_thread_prefix", latest_dm_prefix)
    monkeypatch.setattr(worker, "_process_request", process_request)

    await worker.handle_events_api_payload(
        {
            "event_id": "Ev2",
            "team_id": "T1",
            "event": {
                "type": "message",
                "channel_type": "im",
                "channel": "D1",
                "user": "U1",
                "text": "show revenue by month",
                "ts": "2.0",
            },
        }
    )
    await worker.drain()

    assert len(processed) == 1
    assert processed[0].discussion_id == "slack:T1:D1:dm-1.0"
    assert processed[0].is_continuation is True


@pytest.mark.asyncio
async def test_worker_dm_reset_only_posts_confirmation_without_analysis(monkeypatch: pytest.MonkeyPatch) -> None:
    slack = AsyncMock(spec=SlackApiClient)
    worker = SlackPoCWorker(
        SlackPoCConfig(bot_token="xoxb-test", app_token="xapp-test", bot_user_id="UBOT"),
        slack,
        AsyncMock(),
    )

    async def fail_process_request(_request):
        raise AssertionError("reset-only command should not spawn analysis")

    monkeypatch.setattr(worker, "_process_request", fail_process_request)

    await worker.handle_events_api_payload(
        {
            "event_id": "Ev1",
            "team_id": "T1",
            "event": {
                "type": "message",
                "channel_type": "im",
                "channel": "D1",
                "user": "U1",
                "text": "RESET!!!",
                "ts": "3.0",
            },
        }
    )
    await worker.drain()

    slack.post_message.assert_awaited_once()
    assert slack.post_message.await_args.kwargs == {
        "channel": "D1",
        "text": worker_module.SLACK_RESET_CONFIRMATION_TEXT,
    }
    slack.permalink.assert_not_called()


@pytest.mark.asyncio
async def test_worker_dm_reset_only_rotates_epoch_for_next_question(monkeypatch: pytest.MonkeyPatch) -> None:
    slack = AsyncMock(spec=SlackApiClient)
    slack.permalink.return_value = "https://slack.test/archives/D1/p5000"
    processed = []
    worker = SlackPoCWorker(
        SlackPoCConfig(bot_token="xoxb-test", app_token="xapp-test", bot_user_id="UBOT"),
        slack,
        AsyncMock(),
    )

    async def latest_dm_prefix(_prefix: str):
        return SimpleNamespace(source_thread_id="slack:T1:D1:dm-1.0")

    async def process_request(request):
        processed.append(request)

    monkeypatch.setattr(worker, "_latest_slack_trail_for_source_thread_prefix", latest_dm_prefix)
    monkeypatch.setattr(worker, "_process_request", process_request)

    await worker.handle_events_api_payload(
        {
            "event_id": "Ev-reset",
            "team_id": "T1",
            "event": {
                "type": "message",
                "channel_type": "im",
                "channel": "D1",
                "user": "U1",
                "text": "new conversation.",
                "ts": "5.0",
            },
        }
    )
    await worker.handle_events_api_payload(
        {
            "event_id": "Ev-question",
            "team_id": "T1",
            "event": {
                "type": "message",
                "channel_type": "im",
                "channel": "D1",
                "user": "U1",
                "text": "analyze revenue by month",
                "ts": "6.0",
            },
        }
    )
    await worker.drain()

    assert len(processed) == 1
    assert processed[0].discussion_id == "slack:T1:D1:dm-5.0"
    assert processed[0].is_continuation is False


@pytest.mark.asyncio
async def test_worker_dm_reset_plus_question_rotates_epoch(monkeypatch: pytest.MonkeyPatch) -> None:
    slack = AsyncMock(spec=SlackApiClient)
    slack.permalink.return_value = "https://slack.test/archives/D1/p4000"
    processed = []
    worker = SlackPoCWorker(
        SlackPoCConfig(bot_token="xoxb-test", app_token="xapp-test", bot_user_id="UBOT"),
        slack,
        AsyncMock(),
    )

    async def fail_latest_dm_prefix(_prefix: str):
        raise AssertionError("reset plus question should not reuse the old DM trail")

    async def process_request(request):
        processed.append(request)

    monkeypatch.setattr(worker, "_latest_slack_trail_for_source_thread_prefix", fail_latest_dm_prefix)
    monkeypatch.setattr(worker, "_process_request", process_request)

    await worker.handle_events_api_payload(
        {
            "event_id": "Ev1",
            "team_id": "T1",
            "event": {
                "type": "message",
                "channel_type": "im",
                "channel": "D1",
                "user": "U1",
                "text": "Start over: analyze revenue by month",
                "ts": "4.0",
            },
        }
    )
    await worker.drain()

    assert len(processed) == 1
    assert processed[0].text == "analyze revenue by month"
    assert processed[0].discussion_id == "slack:T1:D1:dm-4.0"
    assert processed[0].is_continuation is False


@pytest.mark.asyncio
async def test_worker_accepts_plain_thread_reply_when_slack_trail_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    slack = AsyncMock(spec=SlackApiClient)
    slack.permalink.return_value = "https://slack.test/archives/C1/p2000"
    processed = []
    worker = SlackPoCWorker(
        SlackPoCConfig(bot_token="xoxb-test", app_token="xapp-test", bot_user_id="UBOT"),
        slack,
        AsyncMock(),
    )

    async def latest_thread(source_thread_id: str):
        assert source_thread_id == "slack:T1:C1:1.0"
        return SimpleNamespace(source_thread_id=source_thread_id)

    async def process_request(request):
        processed.append(request)

    monkeypatch.setattr(worker, "_latest_slack_trail_for_source_thread_id", latest_thread)
    monkeypatch.setattr(worker, "_process_request", process_request)

    await worker.handle_events_api_payload(
        {
            "event_id": "Ev2",
            "team_id": "T1",
            "event": {
                "type": "message",
                "channel_type": "channel",
                "channel": "C1",
                "user": "U1",
                "text": "show revenue by month",
                "thread_ts": "1.0",
                "ts": "2.0",
            },
        }
    )
    await worker.drain()

    assert len(processed) == 1
    assert processed[0].discussion_id == "slack:T1:C1:1.0"
    assert processed[0].is_continuation is True


@pytest.mark.asyncio
async def test_worker_ignores_plain_thread_reply_without_slack_trail(monkeypatch: pytest.MonkeyPatch) -> None:
    slack = AsyncMock(spec=SlackApiClient)
    worker = SlackPoCWorker(
        SlackPoCConfig(bot_token="xoxb-test", app_token="xapp-test", bot_user_id="UBOT"),
        slack,
        AsyncMock(),
    )

    async def no_thread(_source_thread_id: str):
        return None

    async def fail_process_request(_request):
        raise AssertionError("thread without SignalPilot trail should be silent")

    monkeypatch.setattr(worker, "_latest_slack_trail_for_source_thread_id", no_thread)
    monkeypatch.setattr(worker, "_process_request", fail_process_request)

    await worker.handle_events_api_payload(
        {
            "event_id": "Ev2",
            "team_id": "T1",
            "event": {
                "type": "message",
                "channel_type": "channel",
                "channel": "C1",
                "user": "U1",
                "text": "show revenue by month",
                "thread_ts": "1.0",
                "ts": "2.0",
            },
        }
    )
    await worker.drain()

    slack.post_message.assert_not_called()
    slack.permalink.assert_not_called()


@pytest.mark.asyncio
async def test_worker_busy_active_trail_posts_busy_reply_without_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SessionContext:
        async def __aenter__(self):
            return "db"

        async def __aexit__(self, exc_type, exc, tb):
            return False

    slack = AsyncMock(spec=SlackApiClient)
    slack.post_message.return_value = "busy-ts"
    worker = SlackPoCWorker(
        SlackPoCConfig(bot_token="xoxb-test", app_token="xapp-test", org_id="org-1"),
        slack,
        lambda: SessionContext(),
    )
    monkeypatch.setattr(
        worker_module.analysis_trails,
        "get_trail",
        AsyncMock(return_value=SimpleNamespace(status="active", updated_at=time.time())),
    )
    monkeypatch.setattr(worker_module, "resolve_anthropic_key", AsyncMock(side_effect=AssertionError("duplicate")))

    await worker._process_request(
        SlackRequest(
            event_id="Ev2",
            team_id="T1",
            channel_id="C1",
            user_id="U1",
            text="show revenue by month",
            event_ts="2.0",
            thread_ts="1.0",
            source_url="https://slack.test/archives/C1/p20",
            channel_type="channel",
            is_continuation=True,
            discussion_id="slack:T1:C1:1.0",
        )
    )

    slack.post_message.assert_awaited_once_with(
        channel="C1",
        thread_ts="1.0",
        text=worker_module.SLACK_BUSY_TEXT,
    )
    slack.add_reaction.assert_not_called()
    slack.update_message.assert_not_called()


@pytest.mark.asyncio
async def test_worker_busy_gate_allows_done_and_stale_active_trails(monkeypatch: pytest.MonkeyPatch) -> None:
    class SessionContext:
        async def __aenter__(self):
            return "db"

        async def __aexit__(self, exc_type, exc, tb):
            return False

    slack = AsyncMock(spec=SlackApiClient)
    worker = SlackPoCWorker(
        SlackPoCConfig(bot_token="xoxb-test", app_token="xapp-test", org_id="org-1"),
        slack,
        lambda: SessionContext(),
    )
    request = SlackRequest(
        event_id="Ev2",
        team_id="T1",
        channel_id="C1",
        user_id="U1",
        text="show revenue by month",
        event_ts="2.0",
        thread_ts="1.0",
        source_url="https://slack.test/archives/C1/p20",
        discussion_id="slack:T1:C1:1.0",
    )
    get_trail = AsyncMock(return_value=SimpleNamespace(status="done", updated_at=time.time()))
    monkeypatch.setattr(worker_module.analysis_trails, "get_trail", get_trail)

    assert await worker._post_busy_reply_if_active(request) is False
    get_trail.return_value = SimpleNamespace(status="active", updated_at=time.time() - 31 * 60)
    assert await worker._post_busy_reply_if_active(request) is False

    slack.post_message.assert_not_called()


@pytest.mark.asyncio
async def test_worker_continuation_react_action_reacts_only(monkeypatch: pytest.MonkeyPatch) -> None:
    slack = AsyncMock(spec=SlackApiClient)
    worker = SlackPoCWorker(
        SlackPoCConfig(bot_token="xoxb-test", app_token="xapp-test", bot_user_id="UBOT"),
        slack,
        AsyncMock(),
    )

    async def run_intake_agent(_session, **_kwargs):
        return SimpleNamespace(
            action=IntakeTerminalAction(
                name="react_or_ignore",
                arguments={"mode": "react", "reaction": "+1"},
            )
        )

    monkeypatch.setattr(worker_module, "run_intake_agent", run_intake_agent)

    request_to_process = await worker._handle_intake(
        SlackRequest(
            event_id="Ev2",
            team_id="T1",
            channel_id="C1",
            user_id="U1",
            text="thanks",
            event_ts="2.0",
            thread_ts="1.0",
            source_url="https://slack.test/archives/C1/p20",
            is_continuation=True,
            discussion_id="slack:T1:C1:1.0",
        )
    )

    assert request_to_process is None
    slack.add_reaction.assert_awaited_once_with(channel="C1", timestamp="2.0", name="+1")
    slack.post_message.assert_not_called()


@pytest.mark.asyncio
async def test_worker_update_notebook_action_preserves_discussion_id(monkeypatch: pytest.MonkeyPatch) -> None:
    slack = AsyncMock(spec=SlackApiClient)
    worker = SlackPoCWorker(
        SlackPoCConfig(bot_token="xoxb-test", app_token="xapp-test", bot_user_id="UBOT"),
        slack,
        AsyncMock(),
    )

    async def run_intake_agent(_session, **_kwargs):
        return SimpleNamespace(
            action=IntakeTerminalAction(
                name="update_notebook_analysis",
                arguments={"prompt": "Add a product breakdown", "output_mode": "answer"},
            )
        )

    monkeypatch.setattr(worker_module, "run_intake_agent", run_intake_agent)
    trail = SimpleNamespace(
        request_id=worker_module.notebook_analysis._analysis_request_id("slack", "slack:T1:C1:1.0"),
        project_id="project-1",
        branch="analysis/slack/original",
        default_branch="main",
        notebook_path="notebooks/slack/original.py",
        analysis_user_id="analysis-user-1",
    )
    monkeypatch.setattr(
        worker,
        "_notebook_update_status",
        AsyncMock(return_value=IntakeAnalysisStatus(status="safe_to_update", trail=trail)),
    )

    request = SlackRequest(
        event_id="Ev2",
        team_id="T1",
        channel_id="C1",
        user_id="U1",
        text="add product breakdown",
        event_ts="2.0",
        thread_ts="1.0",
        source_url="https://slack.test/archives/C1/p20",
        is_continuation=True,
        discussion_id="slack:T1:C1:1.0",
    )

    request_to_process = await worker._handle_intake(request)

    assert request_to_process is not None
    assert request_to_process.text == "Add a product breakdown"
    assert request_to_process.discussion_id == "slack:T1:C1:1.0"
    assert request_to_process.output_mode == "answer"
    assert request_to_process.update_trail is trail
    assert request_to_process.analysis_action == "update_notebook_analysis"


@pytest.mark.asyncio
async def test_worker_update_uses_existing_trail_route_and_notebook_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SessionContext:
        async def __aenter__(self):
            return "db"

        async def __aexit__(self, exc_type, exc, tb):
            return False

    discussion_id = "slack:T1:C1:1.0"
    request_id = worker_module.notebook_analysis._analysis_request_id("slack", discussion_id)
    trail = SimpleNamespace(
        request_id=request_id,
        thread_id=f"session-{request_id}",
        runtime_session_id="runtime-original",
        project_id="project-original",
        branch="analysis/slack/original-branch",
        default_branch="main",
        notebook_path="notebooks/slack/original.py",
        analysis_user_id="analysis-user-original",
    )
    slack = AsyncMock(spec=SlackApiClient)
    slack.post_message.return_value = "progress-ts"
    worker = SlackPoCWorker(
        SlackPoCConfig(
            bot_token="xoxb-test",
            app_token="xapp-test",
            org_id="org-1",
            default_project_id="project-new",
            progress_enabled=False,
        ),
        slack,
        lambda: SessionContext(),
    )
    resolve_route = AsyncMock(side_effect=AssertionError("update route must not be re-resolved"))
    captured: dict[str, Any] = {}

    async def ensure_session(_db, **kwargs):
        captured["session"] = kwargs
        return worker_module.NotebookRuntime(
            session_id="runtime-original",
            internal_base_url="http://notebook.internal",
            public_base_url="https://app.test/notebook/runtime-original",
        )

    async def call_notebook(_runtime, path, _org_id, user_id, init):
        captured["path"] = path
        captured["user_id"] = user_id
        captured["init"] = init
        return {
            "requestId": request_id,
            "sessionId": f"session-{request_id}",
            "notebookPath": trail.notebook_path,
            "trailUrl": "https://app.test/notebook/runtime-original",
            "status": "Analyzing",
        }

    monkeypatch.setattr(worker_module, "resolve_anthropic_key", AsyncMock(return_value="sk-ant-org"))
    monkeypatch.setattr(worker_module.notebook_analysis, "resolve_analysis_route_for_defaults", resolve_route)
    monkeypatch.setattr(worker_module, "ensure_analysis_notebook_session", ensure_session)
    monkeypatch.setattr(worker_module.analysis_trails, "update_trail", AsyncMock())
    monkeypatch.setattr(worker_module.notebook_analysis, "_call_notebook", call_notebook)
    monkeypatch.setattr(
        worker_module.notebook_analysis,
        "upsert_analysis_trail_from_status",
        AsyncMock(),
    )
    monkeypatch.setattr(
        worker_module.notebook_analysis,
        "update_analysis_trail_from_status",
        AsyncMock(),
    )
    monkeypatch.setattr(
        worker_module.notebook_analysis,
        "_poll_analysis",
        AsyncMock(return_value={"status": "Done", "notionComment": "Done"}),
    )
    monkeypatch.setattr(worker_module.notebook_analysis, "_public_signalpilot_url", lambda url, _runtime: url)
    monkeypatch.setattr(worker_module.notebook_analysis, "_with_public_chart_urls", lambda status, _runtime: status)
    monkeypatch.setattr(worker, "_post_busy_reply_if_active", AsyncMock(return_value=False))
    monkeypatch.setattr(worker, "_previous_thread_messages", AsyncMock(return_value=["original prompt"]))
    monkeypatch.setattr(
        worker,
        "_prior_analysis_trace_messages",
        AsyncMock(return_value=["Prior analysis trace summary: revenue increased"]),
    )
    monkeypatch.setattr(worker, "_analysis_user_id", AsyncMock(return_value="credential-user"))
    monkeypatch.setattr(worker_module, "delivery_api_key_for_org", AsyncMock(return_value="sk-ant-org"))
    monkeypatch.setattr(worker_module, "load_delivery_packet", AsyncMock(return_value=object()))
    monkeypatch.setattr(
        worker_module,
        "render_delivery",
        AsyncMock(
            return_value=DeliveryResult(
                summary="Done",
                slack_message="Done",
                notion_comment="Done",
                final_answer="Done",
                confidence_score="high",
            )
        ),
    )
    monkeypatch.setattr(worker_module, "delivery_result_to_status", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(worker_module, "render_slack_final_message", lambda *_args, **_kwargs: "Done")
    monkeypatch.setattr(worker, "_update_or_post_result_message", AsyncMock())
    monkeypatch.setattr(worker, "_update_progress_message", AsyncMock())
    monkeypatch.setattr(worker, "_mark_request_done", AsyncMock())
    monkeypatch.setattr(worker, "_post_chart_attachments", AsyncMock())

    await worker._process_request(
        SlackRequest(
            event_id="Ev2",
            team_id="T1",
            channel_id="C1",
            user_id="U1",
            text="what changed?",
            event_ts="2.0",
            thread_ts="1.0",
            source_url="https://slack.test/archives/C1/p20",
            is_continuation=True,
            discussion_id=discussion_id,
            analysis_action="update_notebook_analysis",
            update_trail=trail,
        )
    )

    resolve_route.assert_not_awaited()
    assert captured["session"]["project_id"] == trail.project_id
    assert captured["session"]["branch"] == trail.branch
    assert captured["session"]["runtime_session_id"] == trail.runtime_session_id
    assert captured["session"]["analysis_user_id"] == trail.analysis_user_id
    assert captured["user_id"] == trail.analysis_user_id
    assert captured["init"]["headers"]["X-Gateway-Branch-Id"] == trail.branch
    assert captured["init"]["json"]["existingNotebookPath"] == trail.notebook_path
    assert captured["init"]["json"]["discussionId"] == discussion_id


@pytest.mark.asyncio
async def test_worker_update_notebook_action_rejects_incomplete_trail(monkeypatch: pytest.MonkeyPatch) -> None:
    slack = AsyncMock(spec=SlackApiClient)
    worker = SlackPoCWorker(
        SlackPoCConfig(bot_token="xoxb-test", app_token="xapp-test", bot_user_id="UBOT"),
        slack,
        AsyncMock(),
    )

    async def run_intake_agent(_session, **_kwargs):
        return SimpleNamespace(
            action=IntakeTerminalAction(
                name="update_notebook_analysis",
                arguments={"prompt": "Update it", "output_mode": "answer"},
            )
        )

    trail = SimpleNamespace(
        request_id=worker_module.notebook_analysis._analysis_request_id("slack", "slack:T1:C1:1.0"),
        project_id="project-1",
        branch="",
        default_branch="main",
        notebook_path="notebooks/slack/original.py",
        analysis_user_id=None,
    )
    monkeypatch.setattr(worker_module, "run_intake_agent", run_intake_agent)
    monkeypatch.setattr(
        worker,
        "_notebook_update_status",
        AsyncMock(return_value=IntakeAnalysisStatus(status="safe_to_update", trail=trail)),
    )

    result = await worker._handle_intake(
        SlackRequest(
            event_id="Ev2",
            team_id="T1",
            channel_id="C1",
            user_id="U1",
            text="update it",
            event_ts="2.0",
            thread_ts="1.0",
            source_url="https://slack.test/archives/C1/p20",
            is_continuation=True,
            discussion_id="slack:T1:C1:1.0",
        )
    )

    assert result is None
    assert "notebook route is incomplete" in slack.post_message.await_args.kwargs["text"]


@pytest.mark.asyncio
async def test_worker_update_notebook_action_without_trail_does_not_start_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slack = AsyncMock(spec=SlackApiClient)
    worker = SlackPoCWorker(
        SlackPoCConfig(bot_token="xoxb-test", app_token="xapp-test", bot_user_id="UBOT"),
        slack,
        AsyncMock(),
    )

    async def run_intake_agent(_session, **_kwargs):
        return SimpleNamespace(
            action=IntakeTerminalAction(
                name="update_notebook_analysis",
                arguments={"prompt": "Update it", "output_mode": "answer"},
            )
        )

    monkeypatch.setattr(worker_module, "run_intake_agent", run_intake_agent)
    monkeypatch.setattr(
        worker,
        "_notebook_update_status",
        AsyncMock(return_value=IntakeAnalysisStatus(status="not_found")),
    )

    result = await worker._handle_intake(
        SlackRequest(
            event_id="Ev2",
            team_id="T1",
            channel_id="C1",
            user_id="U1",
            text="update it",
            event_ts="2.0",
            thread_ts="1.0",
            source_url="https://slack.test/archives/C1/p20",
            is_continuation=True,
            discussion_id="slack:T1:C1:1.0",
        )
    )

    assert result is None
    assert "could not find an earlier SignalPilot analysis" in slack.post_message.await_args.kwargs["text"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("channel_type", "expected_discussion_id"),
    [
        ("im", "slack:T1:D1:dm-2.0"),
        ("channel", "slack:T1:D1:1.0:run-2.0"),
    ],
)
async def test_worker_explicit_fresh_analysis_rotates_notebook_identity(
    monkeypatch: pytest.MonkeyPatch,
    channel_type: str,
    expected_discussion_id: str,
) -> None:
    slack = AsyncMock(spec=SlackApiClient)
    worker = SlackPoCWorker(
        SlackPoCConfig(bot_token="xoxb-test", app_token="xapp-test", bot_user_id="UBOT", org_id="org-1"),
        slack,
        AsyncMock(),
    )

    async def run_intake_agent(_session, **_kwargs):
        return SimpleNamespace(
            action=IntakeTerminalAction(
                name="start_notebook_analysis",
                arguments={"prompt": "Start fresh", "output_mode": "answer", "fresh": True},
            )
        )

    monkeypatch.setattr(worker_module, "run_intake_agent", run_intake_agent)
    request = SlackRequest(
        event_id="Ev2",
        team_id="T1",
        channel_id="D1",
        user_id="U1",
        text="start fresh",
        event_ts="2.0",
        thread_ts="1.0",
        source_url="https://slack.test/archives/D1/p20",
        channel_type=channel_type,
        is_continuation=True,
        discussion_id="slack:T1:D1:dm-1.0" if channel_type == "im" else "slack:T1:D1:1.0",
    )

    result = await worker._handle_intake(request)

    assert result is not None
    assert result.discussion_id == expected_discussion_id
    assert result.analysis_action == "start_notebook_analysis"


@pytest.mark.asyncio
async def test_worker_channel_followup_reuses_latest_fresh_run_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slack = AsyncMock(spec=SlackApiClient)
    slack.permalink.return_value = "https://slack.test/archives/C1/p300"
    worker = SlackPoCWorker(
        SlackPoCConfig(bot_token="xoxb-test", app_token="xapp-test", bot_user_id="UBOT"),
        slack,
        AsyncMock(),
    )
    latest_fresh = SimpleNamespace(source_thread_id="slack:T1:C1:1.0:run-2.0")
    monkeypatch.setattr(
        worker,
        "_latest_slack_trail_for_source_thread_prefix",
        AsyncMock(return_value=latest_fresh),
    )
    exact_lookup = AsyncMock()
    monkeypatch.setattr(worker, "_latest_slack_trail_for_source_thread_id", exact_lookup)
    monkeypatch.setattr(worker, "_is_thread_watched", AsyncMock(return_value=True))
    monkeypatch.setattr(worker, "_has_pending_thread_dispatch", AsyncMock(return_value=False))

    request = await worker._request_from_payload(
        {
            "event_id": "Ev3",
            "team_id": "T1",
            "event": {
                "type": "message",
                "channel_type": "channel",
                "channel": "C1",
                "user": "U1",
                "text": "what changed now?",
                "ts": "3.0",
                "thread_ts": "1.0",
            },
        }
    )

    assert request is not None
    assert request.discussion_id == latest_fresh.source_thread_id
    exact_lookup.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_previous_messages_uses_history_for_dm_and_replies_for_threads() -> None:
    slack = AsyncMock(spec=SlackApiClient)
    slack.channel_messages.return_value = [
        {"ts": "3.0", "user": "U1", "text": "show revenue by month"},
        {"ts": "2.0", "user": "UBOT", "text": "working"},
        {"ts": "1.0", "user": "U1", "text": "<@UBOT> analyze revenue"},
    ]
    slack.thread_messages.return_value = [
        {"ts": "1.0", "user": "U1", "text": "<@UBOT> analyze revenue"},
        {"ts": "2.0", "user": "U1", "text": "show revenue by month"},
    ]
    worker = SlackPoCWorker(
        SlackPoCConfig(bot_token="xoxb-test", app_token="xapp-test", bot_user_id="UBOT"),
        slack,
        AsyncMock(),
    )

    dm_messages = await worker._previous_thread_messages(
        SlackRequest(
            event_id="Ev3",
            team_id="T1",
            channel_id="D1",
            user_id="U1",
            text="show revenue by month",
            event_ts="3.0",
            thread_ts="3.0",
            source_url="https://slack.test/archives/D1/p30",
            channel_type="im",
            discussion_id="slack:T1:D1:dm-1.0",
        )
    )
    thread_messages = await worker._previous_thread_messages(
        SlackRequest(
            event_id="Ev2",
            team_id="T1",
            channel_id="C1",
            user_id="U1",
            text="show revenue by month",
            event_ts="2.0",
            thread_ts="1.0",
            source_url="https://slack.test/archives/C1/p20",
            channel_type="channel",
            discussion_id="slack:T1:C1:1.0",
        )
    )

    assert dm_messages == ["analyze revenue"]
    assert thread_messages == ["analyze revenue"]
    slack.channel_messages.assert_awaited_once_with(channel="D1", latest="3.0")
    slack.thread_messages.assert_awaited_once_with(channel="C1", thread_ts="1.0")


@pytest.mark.asyncio
async def test_worker_missing_key_reply_omits_thread_ts_for_dm_and_includes_it_for_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SessionContext:
        async def __aenter__(self):
            return "db"

        async def __aexit__(self, exc_type, exc, tb):
            return False

    slack = AsyncMock(spec=SlackApiClient)
    slack.post_message.return_value = "nudge-ts"
    slack.add_reaction.return_value = None
    slack.remove_reaction.return_value = None
    worker = SlackPoCWorker(
        SlackPoCConfig(bot_token="xoxb-test", app_token="xapp-test", org_id="org-1"),
        slack,
        lambda: SessionContext(),
    )
    monkeypatch.setattr(worker, "_post_busy_reply_if_active", AsyncMock(return_value=False))
    monkeypatch.setattr(worker_module, "resolve_anthropic_key", AsyncMock(return_value=None))

    await worker._process_request(
        SlackRequest(
            event_id="Ev1",
            team_id="T1",
            channel_id="D1",
            user_id="U1",
            text="analyze revenue",
            event_ts="1.0",
            thread_ts="1.0",
            source_url="https://slack.test/archives/D1/p10",
            channel_type="im",
            discussion_id="slack:T1:D1:dm-1.0",
        )
    )
    await worker._process_request(
        SlackRequest(
            event_id="Ev2",
            team_id="T1",
            channel_id="C1",
            user_id="U1",
            text="analyze revenue",
            event_ts="2.0",
            thread_ts="1.0",
            source_url="https://slack.test/archives/C1/p20",
            channel_type="channel",
            discussion_id="slack:T1:C1:1.0",
        )
    )

    assert slack.post_message.await_args_list[0].kwargs["thread_ts"] is None
    assert slack.post_message.await_args_list[1].kwargs["thread_ts"] == "1.0"


def _slack_signature(signing_secret: str, timestamp: str, raw_body: bytes) -> str:
    base = b"v0:" + timestamp.encode("utf-8") + b":" + raw_body
    return "v0=" + hmac.new(signing_secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
