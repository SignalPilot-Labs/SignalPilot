"""Pydantic models for Slack integration."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SlackOAuthStartResponse(BaseModel):
    """Authorization URL for the Slack app OAuth flow."""

    authorize_url: str
    state: str


class SlackInstallationConfigInfo(BaseModel):
    """Configured defaults for a Slack OAuth installation."""

    enabled: bool = False
    default_project_id: str | None = None
    default_branch: str = "main"
    analysis_branch_mode: str = "per_request"
    allowed_channel_ids: list[str] = Field(default_factory=list)


class SlackOAuthInstallationInfo(BaseModel):
    """Read-only Slack OAuth install info returned from API."""

    id: str
    team_id: str
    team_name: str | None = None
    enterprise_id: str | None = None
    enterprise_name: str | None = None
    app_id: str | None = None
    bot_user_id: str
    authed_user_id: str | None = None
    scopes: list[str] = Field(default_factory=list)
    status: str = "connected"
    created_at: datetime | None = None
    updated_at: datetime | None = None
    org_id: str | None = None
    config: SlackInstallationConfigInfo | None = None


class SlackProvisionRequest(BaseModel):
    """Configure a Slack installation for notebook-backed analysis."""

    default_project_id: str = Field(..., min_length=1, max_length=200)
    default_branch: str = Field(default="main", min_length=1, max_length=100)
    analysis_branch_mode: str = Field(default="per_request", pattern=r"^(per_request|default_branch)$")
    allowed_channel_ids: list[str] = Field(default_factory=list, max_length=200)


class SlackProvisionResponse(BaseModel):
    """Provisioning result for a Slack OAuth installation."""

    installation: SlackOAuthInstallationInfo
