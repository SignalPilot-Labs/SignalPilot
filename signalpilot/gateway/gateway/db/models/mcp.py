"""Connectors: external MCP servers the chat agent can use (org or personal scope).

Secrets never live in JSON columns. Static headers, member-supplied values,
OAuth tokens and OAuth client secrets are Fernet-encrypted in ``*_enc``
LargeBinary columns (see ``gateway/store/crypto.py``).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
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


class GatewayMcpConnector(GatewayBase):
    """One configured external MCP server."""

    __tablename__ = "gateway_mcp_connectors"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    # "org" (published by an admin for every member) or "personal" (one user).
    scope: Mapped[str] = mapped_column(String(10), nullable=False)
    owner_user_id: Mapped[str | None] = mapped_column(String)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Agent-facing server name: tools appear as mcp__<slug>__<tool>.
    slug: Mapped[str] = mapped_column(String(40), nullable=False)
    # "http" (Streamable HTTP), "sse" (legacy HTTP+SSE) or "stdio" (sandbox).
    transport: Mapped[str] = mapped_column(String(10), nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    command: Mapped[str | None] = mapped_column(Text)
    args_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # [{name, value?, secret, member_supplied}] — secret values are never stored here.
    env_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    header_names_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # "none" | "oauth" | "key"
    auth: Mapped[str] = mapped_column(String(10), nullable=False, default="none", server_default="none")
    # {issuer, metadata_url, client_id, registration, scopes, resource, ...} — no secrets.
    oauth_json: Mapped[dict | None] = mapped_column(JSON)
    oauth_client_secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    # Org-level (or personal owner-level) static headers, e.g. an API key.
    headers_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    # ToolInfo[] including the org-level enabled/policy decision per tool.
    tools_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    tools_hash: Mapped[str | None] = mapped_column(String(64))
    # Tools added/removed by refresh-tools since the inventory was last reviewed
    # (saving PUT /tools resets both to 0). Counts accumulate across refreshes.
    tools_added: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    tools_removed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    protocol_version: Mapped[str | None] = mapped_column(String(20))
    server_name: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending")
    status_detail: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    # Set explicitly by the store on every write (no ORM onupdate: a server-side
    # value would expire the attribute and force lazy IO on the next read).
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(TZDateTime)

    __table_args__ = (Index("ix_gw_mcp_connectors_org", "org_id", "scope"),)


# Slug uniqueness per (org, scope owner): personal connectors are keyed by their
# owner, org connectors by the empty string. Functional so NULL owners collide.
Index(
    "uq_gw_mcp_connector_slug",
    GatewayMcpConnector.org_id,
    func.coalesce(GatewayMcpConnector.owner_user_id, ""),
    GatewayMcpConnector.slug,
    unique=True,
)


class GatewayMcpMemberState(GatewayBase):
    """Per-(connector, user) switch, tool overrides, member-supplied secrets and OAuth tokens."""

    __tablename__ = "gateway_mcp_member_state"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    connector_id: Mapped[str] = mapped_column(String, nullable=False)
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    disabled_tools_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    headers_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    env_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    # {access_token, refresh_token, expires_at, scopes, token_type}
    oauth_tokens_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    signed_in_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    # Best-effort display identity of the signed-in account (email or name from
    # the provider's id_token). Cleared on sign-out. Never used for authorization.
    account_label: Mapped[str | None] = mapped_column(String(200))
    # Set explicitly by the store on every write (no ORM onupdate: a server-side
    # value would expire the attribute and force lazy IO on the next read).
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("connector_id", "user_id", name="uq_gw_mcp_member_state"),
        Index("ix_gw_mcp_member_state_user", "org_id", "user_id"),
    )


class GatewayMcpOAuthState(GatewayBase):
    """Short-lived OAuth state + PKCE verifier; tenant context comes from this row."""

    __tablename__ = "gateway_mcp_oauth_states"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    connector_id: Mapped[str] = mapped_column(String, nullable=False)
    code_verifier: Mapped[str] = mapped_column(String(256), nullable=False)
    redirect_after: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    consumed_at: Mapped[datetime | None] = mapped_column(TZDateTime)


class GatewayMcpOrgPolicy(GatewayBase):
    """Org-wide rules for personal connectors."""

    __tablename__ = "gateway_mcp_org_policy"

    org_id: Mapped[str] = mapped_column(String, primary_key=True)
    allow_personal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    allowed_hosts_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # Set explicitly by the store on every write (no ORM onupdate: a server-side
    # value would expire the attribute and force lazy IO on the next read).
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())


class GatewayMcpToolCall(GatewayBase):
    """Audit row written by the proxy for every tools/call (ok, error or denied)."""

    __tablename__ = "gateway_mcp_tool_calls"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String, nullable=False)
    connector_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    run_id: Mapped[str | None] = mapped_column(String)
    conversation_id: Mapped[str | None] = mapped_column(String)
    tool: Mapped[str] = mapped_column(String(128), nullable=False)
    # "ok" | "error" | "denied"
    outcome: Mapped[str] = mapped_column(String(10), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
    called_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_gw_mcp_tool_calls_org", "org_id", "called_at"),
        Index("ix_gw_mcp_tool_calls_connector", "connector_id", "called_at"),
    )
