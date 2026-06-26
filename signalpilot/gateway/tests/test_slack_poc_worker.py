from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import time
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient

from gateway.db.models import SlackInstallation, SlackInstallationConfig
from gateway.slack_poc import worker as worker_module
from gateway.slack_poc.progress import COMPLETING_PROGRESS_TEXT, INITIAL_PROGRESS_TEXT
from gateway.slack_poc.worker import (
    SlackApiClient,
    SlackPoCConfig,
    SlackPoCWorker,
    SlackRequest,
    _apply_local_runtime_defaults,
    _final_slack_text,
    _remove_bot_mention,
    create_http_app,
)


def test_remove_bot_mention_removes_configured_mention_and_fallback_mentions() -> None:
    assert _remove_bot_mention("<@U123> analyze revenue <@U999>", "U123") == "analyze revenue"


def test_final_slack_text_includes_answer_trail_confidence_without_chart_links() -> None:
    text = _final_slack_text(
        {
            "status": "Done",
            "notionComment": "**Revenue grew** in Q2.\nCosts stayed flat.",
            "confidenceScore": 0.83,
            "notionCharts": [{"title": "Revenue trend", "url": "https://app.test/chart.png"}],
        },
        "https://app.test/projects?file=analysis.py",
    )

    assert "*SignalPilot analysis complete*" in text
    assert "*Revenue grew* in Q2" in text
    assert "**Revenue grew**" not in text
    assert "*Confidence:* 0.83" in text
    assert "<https://app.test/projects?file=analysis.py|Open authenticated notebook>" in text
    assert "*Notebook trail:* https://" not in text
    assert "https://app.test/chart.png" not in text
    assert "*Charts:*" not in text


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
        raise AssertionError(f"unexpected request: {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    slack = SlackApiClient("xoxb-test", "xapp-test", http_client=client)
    try:
        assert await slack.permalink(channel="C1", message_ts="1.0") == "https://slack.test/p1"
        assert await slack.thread_messages(channel="C1", thread_ts="1.0") == [{"text": "hello"}]
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


@pytest.mark.asyncio
async def test_worker_uses_explicit_config_user_id_before_notion_installation() -> None:
    worker = SlackPoCWorker(
        SlackPoCConfig(bot_token="xoxb-test", app_token="xapp-test", user_id="user-explicit"),
        AsyncMock(spec=SlackApiClient),
        AsyncMock(),
    )

    assert await worker._analysis_user_id(AsyncMock()) == "user-explicit"


@pytest.mark.asyncio
async def test_worker_uses_notion_installation_user_when_user_id_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    async def latest_notion_user_id(db, org_id: str) -> str:
        assert db == "db"
        assert org_id == "org-1"
        return "user-from-notion"

    monkeypatch.setattr(worker_module, "_latest_notion_installation_user_id", latest_notion_user_id)
    worker = SlackPoCWorker(
        SlackPoCConfig(bot_token="xoxb-test", app_token="xapp-test", org_id="org-1"),
        AsyncMock(spec=SlackApiClient),
        AsyncMock(),
    )

    assert await worker._analysis_user_id("db") == "user-from-notion"


@pytest.mark.asyncio
async def test_worker_releases_db_session_before_long_notebook_analysis(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    progress_seen = asyncio.Event()
    slack_events: list[tuple[str, str]] = []

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
        credential_user_id: str,
    ):
        assert db == "db"
        assert org_id == "org-1"
        assert source == "slack"
        assert request_id == "slack-req-1"
        assert project_id == "project-1"
        assert branch == "analysis/slack/slack-req-1-analyze-revenue"
        assert credential_user_id == "user-1"
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
        return {"status": "Done", "notionComment": "Done", "confidenceScore": 1.0}

    monkeypatch.setattr(worker_module.notebook_analysis, "resolve_analysis_route_for_defaults", resolve_route)
    monkeypatch.setattr(worker_module, "ensure_analysis_notebook_session", ensure_session)
    monkeypatch.setattr(worker_module.notebook_analysis, "upsert_analysis_trail_seed", seed_trail)
    monkeypatch.setattr(worker_module.notebook_analysis, "upsert_analysis_trail_from_status", upsert_trail)
    monkeypatch.setattr(worker_module.notebook_analysis, "update_analysis_trail_from_status", update_trail)
    monkeypatch.setattr(worker_module.notebook_analysis, "_poll_analysis", poll_analysis)
    monkeypatch.setattr(worker_module.notebook_analysis, "_public_signalpilot_url", lambda url, runtime: url)
    monkeypatch.setattr(worker_module.notebook_analysis, "_with_public_chart_urls", lambda status, runtime: status)

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
            user_id="user-1",
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

    async def run_progress_reporter(*, stop_event, thread_id, source_prompt, channel_id, message_ts, user_id):
        assert thread_id == "session-slack-req-1"
        assert source_prompt == "analyze revenue"
        assert channel_id == "C1"
        assert message_ts == "progress-ts"
        assert user_id == "user-1"
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
    slack.add_reaction.assert_any_await(channel="C1", timestamp="1.0", name="eyes")
    slack.add_reaction.assert_any_await(channel="C1", timestamp="1.0", name="white_check_mark")
    slack.remove_reaction.assert_any_await(channel="C1", timestamp="1.0", name="eyes")
    slack.remove_reaction.assert_any_await(channel="C1", timestamp="1.0", name="x")


@pytest.mark.asyncio
async def test_worker_adds_error_reaction_when_analysis_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    slack = AsyncMock(spec=SlackApiClient)
    slack.post_message.return_value = "progress-ts"
    slack.add_reaction.return_value = None
    slack.remove_reaction.return_value = None

    worker = SlackPoCWorker(
        SlackPoCConfig(bot_token="xoxb-test", app_token="xapp-test", org_id="org-1", user_id="user-1"),
        slack,
        AsyncMock(),
    )

    async def fail_previous_messages(_request):
        raise RuntimeError("notebook auth missing")

    monkeypatch.setattr(worker, "_previous_thread_messages", fail_previous_messages)

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
async def test_worker_uploads_chart_images_as_slack_thread_files(monkeypatch: pytest.MonkeyPatch) -> None:
    slack = AsyncMock(spec=SlackApiClient)
    slack.fetch_bytes.return_value = (b"png-bytes", "image/png")
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

    slack.fetch_bytes.assert_awaited_once_with(
        "http://notebook.test/api/notion-analysis/chart/notion-1/chart.png"
    )
    slack.upload_file.assert_awaited_once_with(
        channel="C1",
        thread_ts="1.0",
        filename="revenue-trend.png",
        title="Revenue trend",
        content=b"png-bytes",
        content_type="image/png",
    )
    slack.post_message.assert_not_called()


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
async def test_worker_preflight_direct_greeting_does_not_spawn_analysis(monkeypatch: pytest.MonkeyPatch) -> None:
    slack = AsyncMock(spec=SlackApiClient)
    slack.permalink.return_value = "https://slack.test/archives/C1/p1000"
    worker = SlackPoCWorker(
        SlackPoCConfig(bot_token="xoxb-test", app_token="xapp-test", bot_user_id="UBOT"),
        slack,
        AsyncMock(),
    )

    async def fail_process_request(_request):
        raise AssertionError("greeting should not spawn analysis")

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
    assert "specific data question" in slack.post_message.call_args.kwargs["text"]


@pytest.mark.asyncio
async def test_worker_preflight_ambiguous_data_prompt_does_not_spawn_analysis(monkeypatch: pytest.MonkeyPatch) -> None:
    slack = AsyncMock(spec=SlackApiClient)
    slack.permalink.return_value = "https://slack.test/archives/C1/p1000"
    worker = SlackPoCWorker(
        SlackPoCConfig(bot_token="xoxb-test", app_token="xapp-test", bot_user_id="UBOT"),
        slack,
        AsyncMock(),
    )

    async def fail_process_request(_request):
        raise AssertionError("ambiguous prompt should not spawn analysis")

    monkeypatch.setattr(worker, "_process_request", fail_process_request)

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

    slack.post_message.assert_awaited_once()
    assert "fresh, specific analysis request" in slack.post_message.call_args.kwargs["text"]


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


def _slack_signature(signing_secret: str, timestamp: str, raw_body: bytes) -> str:
    base = b"v0:" + timestamp.encode("utf-8") + b":" + raw_body
    return "v0=" + hmac.new(signing_secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
