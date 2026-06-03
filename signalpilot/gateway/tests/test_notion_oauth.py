from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from urllib.parse import parse_qs, urlparse

import pytest
from starlette.requests import Request

from gateway.api import notion as notion_api
from gateway.db.models import NotionInstallation, NotionInstallationConfig
from gateway.notion import client as notion_client
from gateway.notion import webhooks as notion_webhooks
from gateway.store import notion as notion_store


def _json_request(payload: dict) -> Request:
    body = json.dumps(payload).encode()

    async def receive() -> dict:
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/notion/webhooks/events",
            "headers": [],
        },
        receive,
    )


def test_authorize_url_includes_state_and_required_oauth_fields() -> None:
    url = notion_client.build_authorize_url("client-123", "https://app.test/notion/callback", "state-123")
    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == "https://api.notion.com/v1/oauth/authorize"
    assert params["client_id"] == ["client-123"]
    assert params["redirect_uri"] == ["https://app.test/notion/callback"]
    assert params["response_type"] == ["code"]
    assert params["owner"] == ["user"]
    assert params["state"] == ["state-123"]


def test_webhook_signature_validation_accepts_valid_signature() -> None:
    body = json.dumps({"id": "evt-1", "type": "comment.created"}).encode()
    secret = "secret_test"
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    notion_webhooks.verify_notion_signature(body, signature, secret)


def test_webhook_signature_validation_rejects_invalid_signature() -> None:
    body = b'{"id":"evt-1"}'

    with pytest.raises(notion_webhooks.InvalidNotionSignature):
        notion_webhooks.verify_notion_signature(body, "sha256=bad", "secret_test")


def test_oauth_redirect_rejects_external_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGNALPILOT_WEB_URL", "https://app.signalpilot.ai")

    redirect_url = notion_api._safe_redirect_url(
        "https://evil.test/integrations",
        installation_id="install-1",
    )
    parsed = urlparse(redirect_url)
    params = parse_qs(parsed.query)

    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == "https://app.signalpilot.ai/integrations"
    assert params["notion"] == ["connected"]
    assert params["installation_id"] == ["install-1"]


def test_oauth_redirect_allows_configured_frontend_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SP_ALLOWED_ORIGINS", "https://preview.signalpilot.ai")

    redirect_url = notion_api._safe_redirect_url("https://preview.signalpilot.ai/integrations?tab=notion")
    parsed = urlparse(redirect_url)
    params = parse_qs(parsed.query)

    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == "https://preview.signalpilot.ai/integrations"
    assert params["tab"] == ["notion"]
    assert params["notion"] == ["connected"]


@pytest.mark.asyncio
async def test_webhook_background_task_logs_unhandled_exception(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def fail_unhandled(*_args, **_kwargs) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(notion_api, "_process_notion_event_task", fail_unhandled)

    with caplog.at_level("ERROR", logger="gateway.api.notion"):
        notion_api._schedule_notion_event_processing("evt-1", "install-1", {})
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    assert "Unhandled Notion webhook processing task failure" in caplog.text
    assert "evt-1" in caplog.text


@pytest.mark.asyncio
async def test_webhook_verification_token_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING", logger="gateway.api.notion"):
        response = await notion_api.receive_notion_webhook(
            _json_request({"verification_token": "verify-secret"}),
            db=object(),
        )

    assert response.status == "verification_received"
    assert "NOTION WEBHOOK VERIFICATION TOKEN RECEIVED: verify-secret" in caplog.text


def test_comment_page_mention_matches_trigger_page_id() -> None:
    comment = {
        "rich_text": [
            {"type": "text", "plain_text": "Hello "},
            {
                "type": "mention",
                "mention": {
                    "type": "page",
                    "page": {"id": "36f79dc4-cc44-817d-b146-c32668bb22ca"},
                },
                "plain_text": "SignalPilot",
            },
        ]
    }

    assert notion_client.comment_has_page_mention(comment, "36f79dc4-cc44-817d-b146-c32668bb22ca")


def test_trigger_page_mention_does_not_match_user_mentions() -> None:
    comment = {
        "rich_text": [
            {
                "type": "mention",
                "mention": {
                    "type": "user",
                    "user": {"object": "user", "id": "2ffd872b-594c-8146-bfcf-00028711f4e5", "type": "person"},
                },
                "plain_text": "@SignalPilot",
            },
        ]
    }

    assert not notion_client.comment_has_page_mention(comment, "36f79dc4-cc44-817d-b146-c32668bb22ca")


@pytest.mark.asyncio
async def test_provisioning_creates_trigger_page_and_requests_database(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    async def fake_create_page(api_key: str, parent_page_id: str | None, title: str, content: str):
        calls.append({"api_key": api_key, "path": "/pages", "parent_page_id": parent_page_id, "title": title, "content": content})
        return {"id": "trigger-page-123", "url": "https://notion.test/trigger-page-123"}

    async def fake_notion_json(api_key: str, method: str, path: str, *, json_body=None, params=None):
        calls.append({"api_key": api_key, "method": method, "path": path, "json_body": json_body, "params": params})
        return {"id": "database-123", "data_sources": [{"id": "data-source-123"}]}

    monkeypatch.setattr(notion_client, "create_page", fake_create_page)
    monkeypatch.setattr(notion_client, "notion_json", fake_notion_json)

    provisioned = await notion_client.provision_signalpilot_resources("token", None)

    assert provisioned == {
        "parent_page_id": None,
        "trigger_page_id": "trigger-page-123",
        "requests_database_page_id": "database-123",
        "requests_data_source_id": "data-source-123",
    }
    assert [call["path"] for call in calls] == ["/pages", "/databases"]


@pytest.mark.asyncio
async def test_provisioning_creates_requests_database_with_expected_properties(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    async def fake_notion_json(api_key: str, method: str, path: str, *, json_body=None, params=None):
        calls.append({"api_key": api_key, "method": method, "path": path, "json_body": json_body, "params": params})
        return {"id": "database-123", "data_sources": [{"id": "data-source-123"}]}

    monkeypatch.setattr(notion_client, "notion_json", fake_notion_json)

    database_id, data_source_id = await notion_client.create_requests_database("token", "parent-page")

    assert database_id == "database-123"
    assert data_source_id == "data-source-123"
    assert calls[0]["path"] == "/databases"
    body = calls[0]["json_body"]
    assert body["parent"] == {"type": "page_id", "page_id": "parent-page"}
    assert body["is_inline"] is True
    assert body["title"][0]["text"]["content"] == "SignalPilot Requests"
    assert body["initial_data_source"]["properties"] == notion_client.REQUEST_DATABASE_PROPERTIES


@pytest.mark.asyncio
async def test_provisioning_can_create_requests_database_at_workspace_level(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    async def fake_notion_json(api_key: str, method: str, path: str, *, json_body=None, params=None):
        calls.append({"api_key": api_key, "method": method, "path": path, "json_body": json_body, "params": params})
        return {"id": "database-123", "data_sources": [{"id": "data-source-123"}]}

    monkeypatch.setattr(notion_client, "notion_json", fake_notion_json)

    database_id, data_source_id = await notion_client.create_requests_database("token", None)

    assert database_id == "database-123"
    assert data_source_id == "data-source-123"
    body = calls[0]["json_body"]
    assert body["parent"] == {"type": "workspace", "workspace": True}
    assert "is_inline" not in body
    assert body["initial_data_source"]["properties"] == notion_client.REQUEST_DATABASE_PROPERTIES


@pytest.mark.asyncio
async def test_create_request_page_does_not_write_prompt_or_source_body(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    async def fake_notion_json(api_key: str, method: str, path: str, *, json_body=None, params=None):
        calls.append({"api_key": api_key, "method": method, "path": path, "json_body": json_body, "params": params})
        return {"id": "request-page-123", "url": "https://notion.test/request-page-123"}

    monkeypatch.setattr(notion_client, "notion_json", fake_notion_json)

    page = await notion_client.create_request_page(
        "token",
        "data-source-123",
        headline="Revenue question",
        source_url="https://notion.test/source-page",
        requester_id="user-123",
        prompt="## Question\n\n- Check `orders`\n- See [dashboard](https://charts.test/dashboard)",
        created_at="2026-06-01T12:00:00+00:00",
    )

    assert page == {"id": "request-page-123", "url": "https://notion.test/request-page-123"}
    body = calls[0]["json_body"]
    assert body["parent"] == {"type": "data_source_id", "data_source_id": "data-source-123"}
    assert body["properties"]["Summary"]["rich_text"][0]["text"]["content"].startswith("## Question")

    assert "children" not in body


@pytest.mark.asyncio
async def test_workspace_level_scope_routes_any_page_to_mention_gate() -> None:
    assert await notion_client.page_belongs_to_scope(
        "token",
        "comment-page",
        parent_page_id=None,
        trigger_page_id="trigger-1",
        requests_data_source_id="ds-1",
        requests_database_page_id="db-1",
    )


@pytest.mark.asyncio
async def test_trigger_page_is_part_of_routing_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_retrieve_page(*args, **kwargs):
        return {"parent": {"type": "workspace", "workspace": True}}

    monkeypatch.setattr(notion_client, "retrieve_page", fake_retrieve_page)

    assert await notion_client.page_belongs_to_scope(
        "token",
        "trigger-1",
        parent_page_id="parent-1",
        trigger_page_id="trigger-1",
        requests_data_source_id="ds-1",
        requests_database_page_id="db-1",
    )


@pytest.mark.asyncio
async def test_webhook_routing_rejects_ambiguous_installations(monkeypatch: pytest.MonkeyPatch) -> None:
    install_1 = NotionInstallation(
        id="install-1",
        org_id="org-1",
        user_id="user-1",
        workspace_id="workspace-1",
        workspace_name="Workspace",
        bot_id="bot-1",
        access_token_enc=b"encrypted",
        status="active",
    )
    install_2 = NotionInstallation(
        id="install-2",
        org_id="org-2",
        user_id="user-2",
        workspace_id="workspace-1",
        workspace_name="Workspace",
        bot_id="bot-1",
        access_token_enc=b"encrypted",
        status="active",
    )
    config_1 = NotionInstallationConfig(
        installation_id="install-1",
        parent_page_id="parent-1",
        trigger_page_id="trigger-1",
        requests_data_source_id="ds-1",
        requests_database_page_id="db-1",
        enabled=True,
    )
    config_2 = NotionInstallationConfig(
        installation_id="install-2",
        parent_page_id="parent-2",
        trigger_page_id="trigger-2",
        requests_data_source_id="ds-2",
        requests_database_page_id="db-2",
        enabled=True,
    )

    async def fake_records(session, workspace_id: str):
        assert workspace_id == "workspace-1"
        return [(install_1, config_1, "token-1"), (install_2, config_2, "token-2")]

    async def fake_belongs(*args, **kwargs):
        return True

    monkeypatch.setattr(notion_store, "list_active_installation_records_for_workspace", fake_records)
    monkeypatch.setattr(notion_client, "page_belongs_to_scope", fake_belongs)

    payload = {
        "workspace_id": "workspace-1",
        "integration_id": "bot-1",
        "type": "comment.created",
        "data": {"page_id": "page-1"},
    }
    with pytest.raises(notion_webhooks.AmbiguousNotionInstallation):
        await notion_webhooks.route_comment_event(object(), payload)


def test_bot_authored_comment_events_are_ignored() -> None:
    assert notion_webhooks.is_bot_authored({"authors": [{"id": "bot", "type": "bot"}]}) is True
    assert notion_webhooks.is_bot_authored({"authors": [{"id": "user", "type": "person"}]}) is False
