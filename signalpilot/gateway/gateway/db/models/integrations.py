"""Define Notion and Slack integration models."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import GatewayBase, TZDateTime


class GatewayNotionIntegration(GatewayBase):
    """Notion integration configuration scoped by org."""

    __tablename__ = "gateway_notion_integrations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    api_key_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    search_page_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    report_parent_page_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="unknown")
    created_at: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("org_id", "name", name="uq_gw_notion_org_name"),
        Index("ix_gw_notion_org_id", "org_id"),
    )

    def to_info_dict(self) -> dict:
        """Convert to a dict matching NotionIntegrationInfo fields."""
        return {
            "id": self.id,
            "name": self.name,
            "search_page_ids": self.search_page_ids or [],
            "report_parent_page_id": self.report_parent_page_id,
            "status": self.status or "unknown",
            "created_at": self.created_at,
            "org_id": self.org_id,
        }


class NotionInstallation(GatewayBase):
    """OAuth-installed Notion public connection scoped by org."""

    __tablename__ = "notion_installations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    workspace_id: Mapped[str] = mapped_column(String(100), nullable=False)
    workspace_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    bot_id: Mapped[str] = mapped_column(String(100), nullable=False)
    owner_user_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    access_token_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    refresh_token_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    owner: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="connected", server_default="connected")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("org_id", "workspace_id", "bot_id", name="uq_notion_install_org_workspace_bot"),
        Index("ix_notion_install_org_status", "org_id", "status"),
        Index("ix_notion_install_workspace", "workspace_id"),
    )


class NotionInstallationConfig(GatewayBase):
    """Provisioning metadata for a Notion OAuth installation."""

    __tablename__ = "notion_installation_config"

    installation_id: Mapped[str] = mapped_column(String, primary_key=True)
    parent_page_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    trigger_page_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    requests_data_source_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    requests_database_page_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    default_project_id: Mapped[str | None] = mapped_column(String, nullable=True)
    default_branch: Mapped[str] = mapped_column(String(100), nullable=False, default="main", server_default="main")
    analysis_branch_mode: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="per_request",
        server_default="per_request",
    )


class NotionWebhookDelivery(GatewayBase):
    """Idempotency and audit record for Notion webhook deliveries."""

    __tablename__ = "notion_webhook_deliveries"

    event_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    installation_id: Mapped[str | None] = mapped_column(String, nullable=True)
    org_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    attempt_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_notion_delivery_install", "installation_id"),
        Index("ix_notion_delivery_org_status", "org_id", "status"),
    )


class NotionDeliverable(GatewayBase):
    """Link a Notion HTML deliverable block to the report and analysis request."""

    __tablename__ = "notion_deliverables"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    installation_id: Mapped[str] = mapped_column(String, nullable=False)
    page_id: Mapped[str] = mapped_column(String(100), nullable=False)
    request_page_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    discussion_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    request_id: Mapped[str] = mapped_column(String(120), nullable=False)
    report_id: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="report", server_default="report")
    embed_block_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    file_upload_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    context_snapshot_id: Mapped[str | None] = mapped_column(String, nullable=True)
    latest_update_id: Mapped[str | None] = mapped_column(String, nullable=True)
    latest_file_upload_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    latest_html_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_notion_deliverables_org_request", "org_id", "request_id"),
        Index("ix_notion_deliverables_report", "org_id", "report_id"),
        Index("ix_notion_deliverables_embed", "installation_id", "embed_block_id"),
        Index("ix_notion_deliverables_install", "installation_id", "created_at"),
    )


class NotionDeliverableContextSnapshot(GatewayBase):
    """Immutable source context captured when a Notion HTML deliverable is created."""

    __tablename__ = "notion_deliverable_context_snapshots"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    deliverable_id: Mapped[str] = mapped_column(String, nullable=False)
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    request_id: Mapped[str] = mapped_column(String(120), nullable=False)
    session_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    base_notebook_code: Mapped[str] = mapped_column(Text, nullable=False)
    base_chat_events: Mapped[list | None] = mapped_column(JSON)
    base_final_packet: Mapped[dict | None] = mapped_column(JSON)
    base_notebook_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    base_notebook_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    project_id: Mapped[str | None] = mapped_column(String, nullable=True)
    branch: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_notion_deliverable_context_deliverable", "deliverable_id", "created_at"),
        Index("ix_notion_deliverable_context_org_request", "org_id", "request_id"),
    )


class NotionDeliverableUpdate(GatewayBase):
    """Lifecycle record for a follow-up refresh/edit of an existing Notion deliverable."""

    __tablename__ = "notion_deliverable_updates"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    deliverable_id: Mapped[str] = mapped_column(String, nullable=False)
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    mode: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running", server_default="running")
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    render_instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    ephemeral_run_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    old_file_upload_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    new_file_upload_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    html_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_notion_deliverable_updates_deliverable", "deliverable_id", "created_at"),
        Index("ix_notion_deliverable_updates_org_status", "org_id", "status"),
    )


class NotionOAuthState(GatewayBase):
    """Short-lived OAuth state for CSRF protection and post-install redirect."""

    __tablename__ = "notion_oauth_states"

    state: Mapped[str] = mapped_column(String(128), primary_key=True)
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    redirect_after: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)

    __table_args__ = (Index("ix_notion_oauth_states_expires", "expires_at"),)


class SlackInstallation(GatewayBase):
    """OAuth-installed Slack app scoped by org."""

    __tablename__ = "slack_installations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    team_id: Mapped[str] = mapped_column(String(100), nullable=False)
    team_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    enterprise_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    enterprise_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    app_id: Mapped[str] = mapped_column(String(100), nullable=False, default="", server_default="")
    bot_user_id: Mapped[str] = mapped_column(String(100), nullable=False)
    authed_user_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bot_access_token_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    scopes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="connected", server_default="connected")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("org_id", "team_id", "app_id", name="uq_slack_install_org_team_app"),
        Index("ix_slack_install_team", "team_id"),
        Index("ix_slack_install_org_status", "org_id", "status"),
    )


class SlackInstallationConfig(GatewayBase):
    """Setup metadata for a Slack OAuth installation."""

    __tablename__ = "slack_installation_config"

    installation_id: Mapped[str] = mapped_column(String, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    default_project_id: Mapped[str | None] = mapped_column(String, nullable=True)
    default_branch: Mapped[str] = mapped_column(String(100), nullable=False, default="main", server_default="main")
    analysis_branch_mode: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="per_request",
        server_default="per_request",
    )
    allowed_channel_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)


class GatewaySlackThreadWatch(GatewayBase):
    """Durable Slack thread invitation state.

    A row means SignalPilot was explicitly mentioned in the Slack thread and may
    route later plain replies through intake without another @mention.
    """

    __tablename__ = "gateway_slack_thread_watches"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    team_id: Mapped[str] = mapped_column(String(100), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(100), nullable=False)
    thread_ts: Mapped[str] = mapped_column(String(50), nullable=False)
    source_thread_id: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active")
    invited_by_user_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    latest_user_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    first_event_ts: Mapped[str | None] = mapped_column(String(50), nullable=True)
    latest_event_ts: Mapped[str | None] = mapped_column(String(50), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("org_id", "team_id", "channel_id", "thread_ts", name="uq_slack_thread_watch_identity"),
        Index("ix_slack_thread_watch_source_thread", "org_id", "source_thread_id"),
        Index("ix_slack_thread_watch_active", "org_id", "team_id", "channel_id", "status"),
    )


class SlackOAuthState(GatewayBase):
    """Short-lived Slack OAuth state for CSRF protection and post-install redirect."""

    __tablename__ = "slack_oauth_states"

    state: Mapped[str] = mapped_column(String(128), primary_key=True)
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    redirect_after: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)

    __table_args__ = (Index("ix_slack_oauth_states_expires", "expires_at"),)
