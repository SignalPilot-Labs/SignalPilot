from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from gateway.api import notion as notion_api
from gateway.db.models import NotionInstallation, NotionInstallationConfig
from gateway.models.notion import NotionInstallationConfigInfo, NotionOAuthInstallationInfo, NotionProvisionRequest
from gateway.notion import client as notion_client
from gateway.notion import webhooks as notion_webhooks
from gateway.store import notion as notion_store


def _json_request(payload: dict, *, notion_secret: str | None = None) -> Request:
    body = json.dumps(payload).encode()
    headers: list[tuple[bytes, bytes]] = []
    if notion_secret:
        signature = "sha256=" + hmac.new(notion_secret.encode(), body, hashlib.sha256).hexdigest()
        headers.append((b"x-notion-signature", signature.encode()))

    async def receive() -> dict:
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/notion/webhooks/events",
            "headers": headers,
        },
        receive,
    )


def _notion_http_error(status_code: int, method: str = "GET", path: str = "/v1/comments") -> httpx.HTTPStatusError:
    request = httpx.Request(method, f"https://api.notion.com{path}")
    response = httpx.Response(
        status_code,
        json={"message": "missing comment capability"},
        request=request,
    )
    return httpx.HTTPStatusError("Notion API error", request=request, response=response)


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
async def test_webhook_verification_token_is_not_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING", logger="gateway.api.notion"):
        response = await notion_api.receive_notion_webhook(
            _json_request({"verification_token": "verify-secret"}),
            db=object(),
        )

    assert response.status == "verification_received"
    assert "verification challenge received" in caplog.text
    assert "verify-secret" not in caplog.text


@pytest.mark.asyncio
async def test_webhook_delivery_fails_closed_without_verification_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NOTION_WEBHOOK_VERIFICATION_TOKEN", raising=False)
    monkeypatch.delenv("WEBHOOK_VERIFICATION_TOKEN", raising=False)

    with pytest.raises(HTTPException) as exc:
        await notion_api.receive_notion_webhook(
            _json_request({"id": "evt-1", "type": "comment.created"}),
            db=object(),
        )

    assert exc.value.status_code == 503
    assert "NOTION_WEBHOOK_VERIFICATION_TOKEN" in exc.value.detail


@pytest.mark.asyncio
async def test_webhook_delivery_rejects_missing_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOTION_WEBHOOK_VERIFICATION_TOKEN", "secret-test")

    with pytest.raises(HTTPException) as exc:
        await notion_api.receive_notion_webhook(
            _json_request({"id": "evt-1", "type": "comment.created"}),
            db=object(),
        )

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_webhook_logs_when_comment_event_has_no_route(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("NOTION_WEBHOOK_VERIFICATION_TOKEN", "secret-test")

    async def no_existing_delivery(*_args, **_kwargs):
        return None

    async def no_route(*_args, **_kwargs):
        return None

    async def record_delivery(*_args, **_kwargs):
        return None

    monkeypatch.setattr(notion_store, "get_webhook_delivery", no_existing_delivery)
    monkeypatch.setattr(notion_store, "record_webhook_delivery", record_delivery)
    monkeypatch.setattr(notion_webhooks, "route_comment_event", no_route)

    payload = {
        "id": "evt-unrouted",
        "type": "comment.created",
        "attempt_number": 1,
        "workspace_id": "workspace-1",
        "data": {"page_id": "page-1"},
        "authors": [{"id": "person-1", "type": "person"}],
    }

    with caplog.at_level(logging.INFO, logger="gateway.api.notion"):
        response = await notion_api.receive_notion_webhook(
            _json_request(payload, notion_secret="secret-test"),
            db=object(),
        )

    assert response.status == "ignored"
    assert response.event_id == "evt-unrouted"
    assert "no_matching_active_provisioned_installation" in caplog.text
    assert "workspace-1" in caplog.text
    assert "page-1" in caplog.text


@pytest.mark.asyncio
async def test_route_comment_event_logs_unprovisioned_candidate(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    install = NotionInstallation(
        id="install-1",
        org_id="org-1",
        user_id="user-1",
        workspace_id="workspace-1",
        workspace_name="Workspace",
        bot_id="bot-1",
        access_token_enc=b"encrypted",
        status="connected",
    )

    async def records(*_args, **_kwargs):
        return [(install, None, "token-1")]

    monkeypatch.setattr(notion_store, "list_active_installation_records_for_workspace", records)

    payload = {
        "id": "evt-unprovisioned",
        "type": "comment.created",
        "workspace_id": "workspace-1",
        "integration_id": "bot-1",
        "data": {"page_id": "page-1"},
    }

    with caplog.at_level(logging.INFO, logger="gateway.notion.webhooks"):
        routed = await notion_webhooks.route_comment_event(object(), payload)

    assert routed is None
    assert "installation_not_provisioned" in caplog.text
    assert "install-1" in caplog.text


@pytest.mark.asyncio
async def test_provisioning_reports_missing_comment_read_capability(monkeypatch: pytest.MonkeyPatch) -> None:
    class Store:
        async def get_notion_oauth_installation(self, installation_id: str):
            assert installation_id == "install-1"
            return SimpleNamespace(
                config=SimpleNamespace(
                    parent_page_id="parent-1",
                    trigger_page_id="trigger-1",
                    requests_data_source_id="ds-1",
                    requests_database_page_id="db-1",
                )
            )

        async def get_notion_oauth_installation_token(self, installation_id: str):
            assert installation_id == "install-1"
            return "token-1"

    async def list_comments(*_args, **_kwargs):
        raise _notion_http_error(403)

    monkeypatch.setattr(notion_client, "list_comments", list_comments)

    with pytest.raises(HTTPException) as exc:
        await notion_api.provision_notion_oauth_installation(
            "install-1",
            NotionProvisionRequest(parent_page_id="parent-1"),
            Store(),
            object(),
        )

    assert exc.value.status_code == 424
    assert "Read comments capability" in exc.value.detail


@pytest.mark.asyncio
async def test_provisioning_ignores_comment_probe_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    saved: list[dict] = []

    class Store:
        async def get_notion_oauth_installation(self, installation_id: str):
            assert installation_id == "install-1"
            return SimpleNamespace(
                config=SimpleNamespace(
                    parent_page_id="parent-1",
                    trigger_page_id="trigger-1",
                    requests_data_source_id="ds-1",
                    requests_database_page_id="db-1",
                )
            )

        async def get_notion_oauth_installation_token(self, installation_id: str):
            assert installation_id == "install-1"
            return "token-1"

        async def save_notion_oauth_installation_config(self, installation_id: str, **kwargs):
            assert installation_id == "install-1"
            saved.append(kwargs)
            return NotionOAuthInstallationInfo(
                id=installation_id,
                workspace_id="workspace-1",
                workspace_name="Workspace",
                bot_id="bot-1",
                owner_user_id=None,
                status="active",
                created_at=None,
                updated_at=None,
                org_id="org-1",
                config=NotionInstallationConfigInfo(**kwargs),
            )

    async def list_comments(*_args, **_kwargs):
        raise _notion_http_error(404)

    monkeypatch.setattr(notion_client, "list_comments", list_comments)

    response = await notion_api.provision_notion_oauth_installation(
        "install-1",
        NotionProvisionRequest(parent_page_id="parent-1"),
        Store(),
        object(),
    )

    assert response.trigger_page_id == "trigger-1"
    assert saved == [
        {
            "parent_page_id": "parent-1",
            "trigger_page_id": "trigger-1",
            "requests_data_source_id": "ds-1",
            "requests_database_page_id": "db-1",
            "enabled": True,
            "default_project_id": None,
            "default_branch": "main",
            "analysis_branch_mode": "per_request",
        }
    ]


@pytest.mark.asyncio
async def test_oauth_provisioning_auto_provisions_without_selected_page(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class Store:
        async def get_notion_oauth_installation(self, installation_id: str):
            assert installation_id == "install-1"
            return SimpleNamespace(config=None)

        async def get_workspace_project(self, project_id: str):
            assert project_id == "project-1"
            return SimpleNamespace(id=project_id)

        async def get_notion_oauth_installation_token(self, installation_id: str):
            assert installation_id == "install-1"
            return "token-1"

        async def save_notion_oauth_installation_config(self, installation_id: str, **kwargs):
            assert installation_id == "install-1"
            return NotionOAuthInstallationInfo(
                id=installation_id,
                workspace_id="workspace-1",
                workspace_name="Workspace",
                bot_id="bot-1",
                owner_user_id=None,
                status="active",
                created_at=None,
                updated_at=None,
                org_id="org-1",
                config=NotionInstallationConfigInfo(**kwargs),
            )

    async def provision_auto(api_key: str):
        calls.append(api_key)
        return {
            "parent_page_id": "signalpilot-integration",
            "trigger_page_id": "new-trigger",
            "requests_data_source_id": "new-ds",
            "requests_database_page_id": "new-db",
        }

    async def list_comments(*_args, **_kwargs):
        return []

    monkeypatch.setattr(notion_client, "provision_signalpilot_resources_auto", provision_auto)
    monkeypatch.setattr(notion_client, "list_comments", list_comments)

    response = await notion_api.provision_notion_oauth_installation(
        "install-1",
        NotionProvisionRequest(default_project_id="project-1"),
        Store(),
        object(),
    )

    assert calls == ["token-1"]
    assert response.trigger_page_id == "new-trigger"
    assert response.installation.config is not None
    assert response.installation.config.parent_page_id == "signalpilot-integration"
    assert response.installation.config.default_project_id == "project-1"


@pytest.mark.asyncio
async def test_oauth_provisioning_uses_selected_sibling_page(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    class Store:
        async def get_notion_oauth_installation(self, installation_id: str):
            assert installation_id == "install-1"
            return SimpleNamespace(
                config=SimpleNamespace(
                    parent_page_id=None,
                    trigger_page_id="old-trigger",
                    requests_data_source_id="old-ds",
                    requests_database_page_id="old-db",
                )
            )

        async def get_notion_oauth_installation_token(self, installation_id: str):
            assert installation_id == "install-1"
            return "token-1"

        async def save_notion_oauth_installation_config(self, installation_id: str, **kwargs):
            assert installation_id == "install-1"
            return NotionOAuthInstallationInfo(
                id=installation_id,
                workspace_id="workspace-1",
                workspace_name="Workspace",
                bot_id="bot-1",
                owner_user_id=None,
                status="active",
                created_at=None,
                updated_at=None,
                org_id="org-1",
                config=NotionInstallationConfigInfo(**kwargs),
            )

    async def provision(api_key: str, sibling_page_id: str):
        calls.append((api_key, sibling_page_id))
        return {
            "parent_page_id": "signalpilot-integration",
            "trigger_page_id": "new-trigger",
            "requests_data_source_id": "new-ds",
            "requests_database_page_id": "new-db",
        }

    async def list_comments(*_args, **_kwargs):
        return []

    monkeypatch.setattr(notion_client, "provision_signalpilot_resources_for_sibling", provision)
    monkeypatch.setattr(notion_client, "list_comments", list_comments)

    response = await notion_api.provision_notion_oauth_installation(
        "install-1",
        NotionProvisionRequest(sibling_page_id="teamspace-child"),
        Store(),
        object(),
    )

    assert calls == [("token-1", "teamspace-child")]
    assert response.trigger_page_id == "new-trigger"
    assert response.installation.config is not None
    assert response.installation.config.parent_page_id == "signalpilot-integration"


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

    async def fake_create_page(
        api_key: str,
        parent_page_id: str | None,
        title: str,
        content: str,
        icon: dict[str, str] | None = None,
    ):
        calls.append(
            {
                "api_key": api_key,
                "path": "/pages",
                "parent_page_id": parent_page_id,
                "title": title,
                "content": content,
                "icon": icon,
            }
        )
        return {"id": "trigger-page-123", "url": "https://notion.test/trigger-page-123"}

    async def fake_notion_json(api_key: str, method: str, path: str, *, json_body=None, params=None):
        calls.append({"api_key": api_key, "method": method, "path": path, "json_body": json_body, "params": params})
        return {"id": "database-123", "data_sources": [{"id": "data-source-123"}]}

    async def fake_list_block_children(*_args, **_kwargs):
        return []

    monkeypatch.setattr(notion_client, "create_page", fake_create_page)
    monkeypatch.setattr(notion_client, "notion_json", fake_notion_json)
    monkeypatch.setattr(notion_client, "list_block_children", fake_list_block_children)

    provisioned = await notion_client.provision_signalpilot_resources("token", "parent-page")

    assert provisioned == {
        "parent_page_id": "parent-page",
        "trigger_page_id": "trigger-page-123",
        "requests_database_page_id": "database-123",
        "requests_data_source_id": "data-source-123",
    }
    assert [call["path"] for call in calls] == ["/pages", "/databases"]
    assert calls[0]["icon"] == notion_client.SIGNALPILOT_TRIGGER_PAGE_ICON


@pytest.mark.asyncio
async def test_create_page_sends_icon_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"id": "trigger-page-123", "url": "https://notion.test/trigger-page-123"}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            del args, kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            del args

        async def post(self, url: str, *, headers: dict, json: dict):
            calls.append({"url": url, "headers": headers, "json": json})
            return FakeResponse()

    monkeypatch.setattr(notion_client.httpx, "AsyncClient", FakeAsyncClient)

    page = await notion_client.create_page(
        "token",
        "parent-page",
        notion_client.SIGNALPILOT_TRIGGER_PAGE_TITLE,
        "Mention this page in a Notion comment to start SignalPilot analysis.",
        icon=notion_client.SIGNALPILOT_TRIGGER_PAGE_ICON,
    )

    assert page == {"id": "trigger-page-123", "title": "SignalPilot", "url": "https://notion.test/trigger-page-123"}
    assert calls[0]["json"]["parent"] == {"type": "page_id", "page_id": "parent-page"}
    assert calls[0]["json"]["icon"] == notion_client.SIGNALPILOT_TRIGGER_PAGE_ICON


@pytest.mark.asyncio
async def test_existing_trigger_page_receives_bot_icon(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    async def fake_list_block_children(api_key: str, block_id: str):
        calls.append({"api_key": api_key, "path": f"/blocks/{block_id}/children"})
        return [
            {
                "id": "trigger-page-123",
                "type": "child_page",
                "child_page": {"title": notion_client.SIGNALPILOT_TRIGGER_PAGE_TITLE},
            }
        ]

    async def fake_update_page_icon(api_key: str, page_id: str, icon: dict[str, str]):
        calls.append({"api_key": api_key, "path": f"/pages/{page_id}", "icon": icon})

    async def fail_create_page(*_args, **_kwargs):
        raise AssertionError("existing trigger page should be reused")

    monkeypatch.setattr(notion_client, "list_block_children", fake_list_block_children)
    monkeypatch.setattr(notion_client, "update_page_icon", fake_update_page_icon)
    monkeypatch.setattr(notion_client, "create_page", fail_create_page)

    page = await notion_client.ensure_child_page(
        "token",
        "parent-page",
        icon=notion_client.SIGNALPILOT_TRIGGER_PAGE_ICON,
    )

    assert page["id"] == "trigger-page-123"
    assert calls == [
        {"api_key": "token", "path": "/blocks/parent-page/children"},
        {
            "api_key": "token",
            "path": "/pages/trigger-page-123",
            "icon": notion_client.SIGNALPILOT_TRIGGER_PAGE_ICON,
        },
    ]


@pytest.mark.asyncio
async def test_provisioning_creates_container_page_as_sibling(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    async def fake_create_page(
        api_key: str,
        parent_page_id: str | None,
        title: str,
        content: str,
        icon: dict[str, str] | None = None,
    ):
        calls.append(
            {
                "api_key": api_key,
                "path": "/pages",
                "parent_page_id": parent_page_id,
                "title": title,
                "content": content,
                "icon": icon,
            }
        )
        if title == notion_client.SIGNALPILOT_INTEGRATION_PAGE_TITLE:
            return {"id": "integration-page-123", "url": "https://notion.test/integration-page-123"}
        return {"id": "trigger-page-123", "url": "https://notion.test/trigger-page-123"}

    async def fake_notion_json(api_key: str, method: str, path: str, *, json_body=None, params=None):
        calls.append({"api_key": api_key, "method": method, "path": path, "json_body": json_body, "params": params})
        if method == "GET" and path == "/pages/teamspace-child":
            return {"id": "teamspace-child", "parent": {"type": "page_id", "page_id": "teamspace-parent"}}
        return {"id": "database-123", "data_sources": [{"id": "data-source-123"}]}

    async def fake_list_block_children(_api_key: str, block_id: str):
        calls.append({"api_key": _api_key, "method": "GET", "path": f"/blocks/{block_id}/children"})
        return []

    monkeypatch.setattr(notion_client, "create_page", fake_create_page)
    monkeypatch.setattr(notion_client, "notion_json", fake_notion_json)
    monkeypatch.setattr(notion_client, "list_block_children", fake_list_block_children)

    provisioned = await notion_client.provision_signalpilot_resources_for_sibling("token", "teamspace-child")

    assert provisioned == {
        "parent_page_id": "integration-page-123",
        "trigger_page_id": "trigger-page-123",
        "requests_database_page_id": "database-123",
        "requests_data_source_id": "data-source-123",
    }
    created_pages = [call for call in calls if call.get("path") == "/pages"]
    assert created_pages == [
        {
            "api_key": "token",
            "path": "/pages",
            "parent_page_id": "teamspace-parent",
            "title": notion_client.SIGNALPILOT_INTEGRATION_PAGE_TITLE,
            "content": (
                "SignalPilot-created pages for Notion analysis requests. "
                "Keep this page shared with the SignalPilot connection."
            ),
            "icon": None,
        },
        {
            "api_key": "token",
            "path": "/pages",
            "parent_page_id": "integration-page-123",
            "title": notion_client.SIGNALPILOT_TRIGGER_PAGE_TITLE,
            "content": "Mention this page in a Notion comment to start SignalPilot analysis.",
            "icon": notion_client.SIGNALPILOT_TRIGGER_PAGE_ICON,
        },
    ]
    databases = [call for call in calls if call.get("path") == "/databases"]
    assert databases[0]["json_body"]["parent"] == {"type": "page_id", "page_id": "integration-page-123"}


@pytest.mark.asyncio
async def test_provisioning_uses_selected_workspace_level_integration_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict] = []

    async def fake_create_page(
        api_key: str,
        parent_page_id: str | None,
        title: str,
        content: str,
        icon: dict[str, str] | None = None,
    ):
        calls.append(
            {
                "api_key": api_key,
                "path": "/pages",
                "parent_page_id": parent_page_id,
                "title": title,
                "content": content,
                "icon": icon,
            }
        )
        return {"id": "trigger-page-123", "url": "https://notion.test/trigger-page-123"}

    async def fake_notion_json(api_key: str, method: str, path: str, *, json_body=None, params=None):
        calls.append({"api_key": api_key, "method": method, "path": path, "json_body": json_body, "params": params})
        if method == "GET" and path == "/pages/integration-page-123":
            return {
                "id": "integration-page-123",
                "parent": {"type": "workspace", "workspace": True},
                "properties": {
                    "title": {
                        "type": "title",
                        "title": [{"plain_text": "SignalPilot Integration"}],
                    }
                },
            }
        return {"id": "database-123", "data_sources": [{"id": "data-source-123"}]}

    async def fake_list_block_children(_api_key: str, block_id: str):
        calls.append({"api_key": _api_key, "method": "GET", "path": f"/blocks/{block_id}/children"})
        return []

    monkeypatch.setattr(notion_client, "create_page", fake_create_page)
    monkeypatch.setattr(notion_client, "notion_json", fake_notion_json)
    monkeypatch.setattr(notion_client, "list_block_children", fake_list_block_children)

    provisioned = await notion_client.provision_signalpilot_resources_for_sibling("token", "integration-page-123")

    assert provisioned == {
        "parent_page_id": "integration-page-123",
        "trigger_page_id": "trigger-page-123",
        "requests_database_page_id": "database-123",
        "requests_data_source_id": "data-source-123",
    }
    created_pages = [call for call in calls if call.get("path") == "/pages"]
    assert created_pages == [
        {
            "api_key": "token",
            "path": "/pages",
            "parent_page_id": "integration-page-123",
            "title": notion_client.SIGNALPILOT_TRIGGER_PAGE_TITLE,
            "content": "Mention this page in a Notion comment to start SignalPilot analysis.",
            "icon": notion_client.SIGNALPILOT_TRIGGER_PAGE_ICON,
        },
    ]
    databases = [call for call in calls if call.get("path") == "/databases"]
    assert databases[0]["json_body"]["parent"] == {"type": "page_id", "page_id": "integration-page-123"}


@pytest.mark.asyncio
async def test_auto_provisioning_reuses_visible_integration_page(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    async def fake_create_page(
        api_key: str,
        parent_page_id: str | None,
        title: str,
        content: str,
        icon: dict[str, str] | None = None,
    ):
        calls.append(
            {
                "api_key": api_key,
                "path": "/pages",
                "parent_page_id": parent_page_id,
                "title": title,
                "content": content,
                "icon": icon,
            }
        )
        return {"id": "trigger-page-123", "url": "https://notion.test/trigger-page-123"}

    async def fake_notion_json(api_key: str, method: str, path: str, *, json_body=None, params=None):
        calls.append({"api_key": api_key, "method": method, "path": path, "json_body": json_body, "params": params})
        if method == "POST" and path == "/search":
            assert json_body["query"] == notion_client.SIGNALPILOT_INTEGRATION_PAGE_TITLE
            return {
                "results": [
                    {
                        "id": "integration-page-123",
                        "parent": {"type": "workspace", "workspace": True},
                        "properties": {
                            "title": {
                                "type": "title",
                                "title": [{"plain_text": "SignalPilot Integration"}],
                            }
                        },
                    }
                ]
            }
        return {"id": "database-123", "data_sources": [{"id": "data-source-123"}]}

    async def fake_list_block_children(_api_key: str, block_id: str):
        calls.append({"api_key": _api_key, "method": "GET", "path": f"/blocks/{block_id}/children"})
        return []

    monkeypatch.setattr(notion_client, "create_page", fake_create_page)
    monkeypatch.setattr(notion_client, "notion_json", fake_notion_json)
    monkeypatch.setattr(notion_client, "list_block_children", fake_list_block_children)

    provisioned = await notion_client.provision_signalpilot_resources_auto("token")

    assert provisioned == {
        "parent_page_id": "integration-page-123",
        "trigger_page_id": "trigger-page-123",
        "requests_database_page_id": "database-123",
        "requests_data_source_id": "data-source-123",
    }
    created_pages = [call for call in calls if call.get("path") == "/pages"]
    assert created_pages == [
        {
            "api_key": "token",
            "path": "/pages",
            "parent_page_id": "integration-page-123",
            "title": notion_client.SIGNALPILOT_TRIGGER_PAGE_TITLE,
            "content": "Mention this page in a Notion comment to start SignalPilot analysis.",
            "icon": notion_client.SIGNALPILOT_TRIGGER_PAGE_ICON,
        },
    ]


@pytest.mark.asyncio
async def test_auto_provisioning_creates_container_beside_visible_page(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    async def fake_create_page(
        api_key: str,
        parent_page_id: str | None,
        title: str,
        content: str,
        icon: dict[str, str] | None = None,
    ):
        calls.append(
            {
                "api_key": api_key,
                "path": "/pages",
                "parent_page_id": parent_page_id,
                "title": title,
                "content": content,
                "icon": icon,
            }
        )
        if title == notion_client.SIGNALPILOT_INTEGRATION_PAGE_TITLE:
            return {"id": "integration-page-123", "url": "https://notion.test/integration-page-123"}
        return {"id": "trigger-page-123", "url": "https://notion.test/trigger-page-123"}

    async def fake_notion_json(api_key: str, method: str, path: str, *, json_body=None, params=None):
        calls.append({"api_key": api_key, "method": method, "path": path, "json_body": json_body, "params": params})
        if method == "POST" and path == "/search" and json_body.get("query"):
            return {"results": []}
        if method == "POST" and path == "/search":
            return {
                "results": [
                    {
                        "id": "teamspace-child",
                        "parent": {"type": "page_id", "page_id": "teamspace-parent"},
                        "properties": {
                            "title": {
                                "type": "title",
                                "title": [{"plain_text": "Teamspace child"}],
                            }
                        },
                    }
                ]
            }
        return {"id": "database-123", "data_sources": [{"id": "data-source-123"}]}

    async def fake_list_block_children(_api_key: str, block_id: str):
        calls.append({"api_key": _api_key, "method": "GET", "path": f"/blocks/{block_id}/children"})
        return []

    monkeypatch.setattr(notion_client, "create_page", fake_create_page)
    monkeypatch.setattr(notion_client, "notion_json", fake_notion_json)
    monkeypatch.setattr(notion_client, "list_block_children", fake_list_block_children)

    provisioned = await notion_client.provision_signalpilot_resources_auto("token")

    assert provisioned["parent_page_id"] == "integration-page-123"
    created_pages = [call for call in calls if call.get("path") == "/pages"]
    assert created_pages == [
        {
            "api_key": "token",
            "path": "/pages",
            "parent_page_id": "teamspace-parent",
            "title": notion_client.SIGNALPILOT_INTEGRATION_PAGE_TITLE,
            "content": notion_client.SIGNALPILOT_INTEGRATION_PAGE_CONTENT,
            "icon": None,
        },
        {
            "api_key": "token",
            "path": "/pages",
            "parent_page_id": "integration-page-123",
            "title": notion_client.SIGNALPILOT_TRIGGER_PAGE_TITLE,
            "content": "Mention this page in a Notion comment to start SignalPilot analysis.",
            "icon": notion_client.SIGNALPILOT_TRIGGER_PAGE_ICON,
        },
    ]


@pytest.mark.asyncio
async def test_auto_provisioning_errors_when_only_workspace_level_pages_are_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict] = []

    async def fake_create_page(*_args, **_kwargs):
        raise AssertionError("auto provisioning must not create inside an arbitrary visible page")

    async def fake_notion_json(api_key: str, method: str, path: str, *, json_body=None, params=None):
        calls.append({"api_key": api_key, "method": method, "path": path, "json_body": json_body, "params": params})
        if method == "POST" and path == "/search" and json_body.get("query"):
            return {"results": []}
        if method == "POST" and path == "/search":
            return {
                "results": [
                    {
                        "id": "workspace-level-page",
                        "parent": {"type": "workspace", "workspace": True},
                        "properties": {
                            "title": {
                                "type": "title",
                                "title": [{"plain_text": "SP my Integration"}],
                            }
                        },
                    }
                ]
            }
        raise AssertionError(f"unexpected Notion call {method} {path}")

    monkeypatch.setattr(notion_client, "create_page", fake_create_page)
    monkeypatch.setattr(notion_client, "notion_json", fake_notion_json)

    with pytest.raises(ValueError, match="Create a Notion page named 'SignalPilot Integration'"):
        await notion_client.provision_signalpilot_resources_auto("token")

    assert [call["path"] for call in calls] == ["/search", "/search"]


@pytest.mark.asyncio
async def test_list_parent_pages_returns_visible_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    async def fake_notion_json(api_key: str, method: str, path: str, *, json_body=None, params=None):
        del api_key, json_body, params
        calls.append((method, path))
        if method == "POST" and path == "/search":
            return {
                "results": [
                    {
                        "id": "nested-page",
                        "parent": {"type": "page_id", "page_id": "teamspace-root"},
                        "properties": {"title": {"type": "title", "title": [{"plain_text": "Nested"}]}},
                    },
                    {
                        "id": "other-page",
                        "parent": {"type": "page_id", "page_id": "teamspace-root"},
                        "properties": {"title": {"type": "title", "title": [{"plain_text": "Other"}]}},
                        "url": "https://notion.test/other-page",
                    },
                ]
            }
        raise AssertionError(f"unexpected Notion call {method} {path}")

    monkeypatch.setattr(notion_client, "notion_json", fake_notion_json)

    pages = await notion_client.list_parent_pages("token")

    assert pages == [
        {"id": "nested-page", "title": "Nested", "url": ""},
        {"id": "other-page", "title": "Other", "url": "https://notion.test/other-page"},
    ]
    assert calls == [("POST", "/search")]


@pytest.mark.asyncio
async def test_provisioning_requires_parent_page_to_avoid_private_workspace_resources() -> None:
    with pytest.raises(ValueError, match="parent_page_id is required"):
        await notion_client.provision_signalpilot_resources("token", None)


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
    assert body["properties"]["Created at"] == {"date": {"start": "2026-06-01T12:00:00+00:00"}}

    assert "children" not in body


@pytest.mark.asyncio
async def test_create_request_page_falls_back_to_readable_created_at_for_legacy_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict] = []

    async def fake_notion_json(api_key: str, method: str, path: str, *, json_body=None, params=None):
        del api_key, method, path, params
        calls.append(json.loads(json.dumps(json_body)))
        if len(calls) == 1:
            request = httpx.Request("POST", "https://api.notion.com/v1/pages")
            response = httpx.Response(400, json={"message": "Created at should be rich_text"}, request=request)
            raise httpx.HTTPStatusError("bad request", request=request, response=response)
        return {"id": "request-page-123", "url": "https://notion.test/request-page-123"}

    monkeypatch.setattr(notion_client, "notion_json", fake_notion_json)

    page = await notion_client.create_request_page(
        "token",
        "data-source-123",
        headline="Revenue question",
        source_url="https://notion.test/source-page",
        requester_id="user-123",
        prompt="Analyze revenue",
        created_at="2026-06-26T14:38:44.790255+00:00",
    )

    assert page == {"id": "request-page-123", "url": "https://notion.test/request-page-123"}
    assert calls[0]["properties"]["Created at"] == {"date": {"start": "2026-06-26T14:38:44.790255+00:00"}}
    assert calls[1]["properties"]["Created at"]["rich_text"][0]["text"]["content"] == "Jun 26, 2026 14:38 UTC"


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
async def test_webhook_routing_requires_positive_ownership(monkeypatch: pytest.MonkeyPatch) -> None:
    install = NotionInstallation(
        id="install-1",
        org_id="org-1",
        user_id="user-1",
        workspace_id="workspace-1",
        workspace_name="Workspace",
        bot_id="bot-1",
        access_token_enc=b"encrypted",
        status="active",
    )
    config = NotionInstallationConfig(
        installation_id="install-1",
        parent_page_id="parent-1",
        trigger_page_id="trigger-1",
        requests_data_source_id="ds-1",
        requests_database_page_id="db-1",
        enabled=True,
    )

    async def fake_records(session, workspace_id: str):
        assert workspace_id == "workspace-1"
        return [(install, config, "token-1")]

    async def fail_belongs(*args, **kwargs):
        raise AssertionError("page_belongs_to_scope should not run without positive ownership")

    monkeypatch.setattr(notion_store, "list_active_installation_records_for_workspace", fake_records)
    monkeypatch.setattr(notion_client, "page_belongs_to_scope", fail_belongs)

    routed = await notion_webhooks.route_comment_event(
        object(),
        {
            "workspace_id": "workspace-1",
            "type": "comment.created",
            "data": {"page_id": "page-1", "parent": {"id": "page-1", "type": "page"}},
        },
    )

    assert routed is None


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

    async def fake_list_comments(*args, **kwargs):
        return [
            {
                "id": "comment-1",
                "rich_text": [
                    {"type": "mention", "mention": {"type": "page", "page": {"id": "trigger-1"}}},
                    {"type": "mention", "mention": {"type": "page", "page": {"id": "trigger-2"}}},
                ],
            }
        ]

    monkeypatch.setattr(notion_store, "list_active_installation_records_for_workspace", fake_records)
    monkeypatch.setattr(notion_client, "page_belongs_to_scope", fake_belongs)
    monkeypatch.setattr(notion_client, "list_comments", fake_list_comments)

    payload = {
        "workspace_id": "workspace-1",
        "integration_id": "bot-1",
        "type": "comment.created",
        "entity": {"id": "comment-1", "type": "comment"},
        "data": {"page_id": "page-1", "parent": {"id": "page-1", "type": "page"}},
    }
    with pytest.raises(notion_webhooks.AmbiguousNotionInstallation):
        await notion_webhooks.route_comment_event(object(), payload)


@pytest.mark.asyncio
async def test_webhook_routing_uses_trigger_page_mention_to_disambiguate(monkeypatch: pytest.MonkeyPatch) -> None:
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
        parent_page_id=None,
        trigger_page_id="trigger-1",
        requests_data_source_id="ds-1",
        requests_database_page_id="db-1",
        enabled=True,
    )
    config_2 = NotionInstallationConfig(
        installation_id="install-2",
        parent_page_id=None,
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

    async def fake_list_comments(*args, **kwargs):
        return [
            {
                "id": "comment-1",
                "rich_text": [{"type": "mention", "mention": {"type": "page", "page": {"id": "trigger-2"}}}],
            }
        ]

    monkeypatch.setattr(notion_store, "list_active_installation_records_for_workspace", fake_records)
    monkeypatch.setattr(notion_client, "page_belongs_to_scope", fake_belongs)
    monkeypatch.setattr(notion_client, "list_comments", fake_list_comments)

    payload = {
        "workspace_id": "workspace-1",
        "integration_id": "bot-1",
        "type": "comment.created",
        "entity": {"id": "comment-1", "type": "comment"},
        "data": {"page_id": "page-1", "parent": {"id": "page-1", "type": "page"}},
    }

    routed = await notion_webhooks.route_comment_event(object(), payload)

    assert routed is not None
    assert routed.installation.id == "install-2"


def test_bot_authored_comment_events_are_ignored() -> None:
    assert notion_webhooks.is_bot_authored({"authors": [{"id": "bot", "type": "bot"}]}) is True
    assert notion_webhooks.is_bot_authored({"authors": [{"id": "user", "type": "person"}]}) is False
