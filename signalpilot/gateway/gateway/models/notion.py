"""Pydantic models for Notion integration."""

from __future__ import annotations

import time
from datetime import datetime

from pydantic import BaseModel, Field


class NotionIntegrationCreate(BaseModel):
    """Create a new Notion integration."""

    name: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    api_key: str = Field(..., min_length=1, max_length=256)
    search_page_ids: list[str] = Field(default_factory=list, max_length=20)
    report_parent_page_id: str = Field(..., min_length=1, max_length=64)


class NotionIntegrationUpdate(BaseModel):
    """Partial update for an existing Notion integration."""

    api_key: str | None = Field(default=None, min_length=1, max_length=256)
    search_page_ids: list[str] | None = Field(default=None, max_length=20)
    report_parent_page_id: str | None = Field(default=None, min_length=1, max_length=64)


class NotionIntegrationInfo(BaseModel):
    """Read-only info returned from API (never includes api_key)."""

    id: str
    name: str
    search_page_ids: list[str] = Field(default_factory=list)
    report_parent_page_id: str | None = None
    status: str = "unknown"
    created_at: float = Field(default_factory=time.time)
    org_id: str | None = None


class NotionOAuthStartResponse(BaseModel):
    """Authorization URL for the Notion public integration OAuth flow."""

    authorize_url: str
    state: str


class NotionInstallationConfigInfo(BaseModel):
    """Provisioned Notion resources for an OAuth installation."""

    parent_page_id: str | None = None
    trigger_page_id: str | None = None
    requests_data_source_id: str | None = None
    requests_database_page_id: str | None = None
    enabled: bool = False
    default_project_id: str | None = None
    default_branch: str = "main"
    analysis_branch_mode: str = "per_request"


class NotionOAuthInstallationInfo(BaseModel):
    """Read-only OAuth install info returned from API."""

    id: str
    workspace_id: str
    workspace_name: str | None = None
    bot_id: str
    owner_user_id: str | None = None
    status: str = "connected"
    created_at: datetime | None = None
    updated_at: datetime | None = None
    org_id: str | None = None
    config: NotionInstallationConfigInfo | None = None


class NotionPageOption(BaseModel):
    """A Notion page that can be selected as a setup parent."""

    id: str
    title: str
    url: str | None = None


class NotionProvisionRequest(BaseModel):
    """Provision SignalPilot Notion resources.

    When parent_page_id is omitted, resources are created privately at the
    workspace level for the authorizing Notion user.
    """

    parent_page_id: str | None = Field(default=None, min_length=1, max_length=100)
    default_project_id: str | None = Field(default=None, min_length=1, max_length=200)
    default_branch: str = Field(default="main", min_length=1, max_length=100)
    analysis_branch_mode: str = Field(default="per_request", pattern=r"^(per_request|default_branch)$")


class NotionProvisionResponse(BaseModel):
    """Provisioning result for a Notion OAuth installation."""

    installation: NotionOAuthInstallationInfo
    trigger_page_id: str
    requests_data_source_id: str
    requests_database_page_id: str


class NotionWebhookResponse(BaseModel):
    """Public webhook endpoint response."""

    status: str
    event_id: str | None = None
