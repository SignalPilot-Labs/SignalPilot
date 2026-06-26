from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException

from gateway.api import slack as slack_api
from gateway.models.slack import SlackProvisionRequest


def test_authorize_url_includes_state_and_required_oauth_fields() -> None:
    url = slack_api.build_slack_authorize_url(
        "client-123",
        "https://app.test/slack/callback",
        "state-123",
        "app_mentions:read,chat:write",
    )
    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == "https://slack.com/oauth/v2/authorize"
    assert params["client_id"] == ["client-123"]
    assert params["redirect_uri"] == ["https://app.test/slack/callback"]
    assert params["scope"] == ["app_mentions:read,chat:write"]
    assert params["state"] == ["state-123"]


def test_oauth_redirect_rejects_external_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGNALPILOT_WEB_URL", "https://app.signalpilot.ai")

    redirect_url = slack_api._safe_redirect_url(
        "https://evil.test/integrations",
        installation_id="install-1",
    )
    parsed = urlparse(redirect_url)
    params = parse_qs(parsed.query)

    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == "https://app.signalpilot.ai/integrations"
    assert params["slack"] == ["connected"]
    assert params["slack_installation_id"] == ["install-1"]


@pytest.mark.asyncio
async def test_provisioning_requires_existing_default_project() -> None:
    class Store:
        async def get_workspace_project(self, project_id: str):
            assert project_id == "project-1"

    with pytest.raises(HTTPException) as exc:
        await slack_api.provision_slack_oauth_installation(
            "install-1",
            SlackProvisionRequest(default_project_id="project-1"),
            Store(),
            object(),
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Default project not found"


@pytest.mark.asyncio
async def test_provisioning_saves_default_project() -> None:
    calls: list[dict] = []

    class Store:
        async def get_workspace_project(self, project_id: str):
            assert project_id == "project-1"
            return object()

        async def save_slack_oauth_installation_config(self, installation_id: str, **kwargs):
            calls.append({"installation_id": installation_id, **kwargs})
            return {
                "id": installation_id,
                "team_id": "T1",
                "team_name": "Demo",
                "bot_user_id": "UBOT",
                "status": "active",
                "config": {
                    "enabled": True,
                    "default_project_id": kwargs["default_project_id"],
                    "default_branch": kwargs["default_branch"],
                    "analysis_branch_mode": kwargs["analysis_branch_mode"],
                    "allowed_channel_ids": kwargs["allowed_channel_ids"],
                },
            }

    response = await slack_api.provision_slack_oauth_installation(
        "install-1",
        SlackProvisionRequest(default_project_id="project-1", allowed_channel_ids=["C1"]),
        Store(),
        object(),
    )

    assert response.installation.id == "install-1"
    assert calls == [
        {
            "installation_id": "install-1",
            "enabled": True,
            "default_project_id": "project-1",
            "default_branch": "main",
            "analysis_branch_mode": "per_request",
            "allowed_channel_ids": ["C1"],
        }
    ]
