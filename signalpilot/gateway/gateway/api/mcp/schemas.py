"""Request bodies and response shapes for the Connectors API (§2 contract; snake_case JSON).

Routes build response dicts directly (``api/mcp/common.py``); the ``*Out``
models below are the typed contract those dicts must satisfy and are what the
contract tests validate against. ``extra="forbid"`` on them makes any drift
between the two fail loudly.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Scope = Literal["org", "personal"]
Transport = Literal["http", "sse", "stdio"]
AuthMode = Literal["none", "oauth", "key"]
ToolPolicy = Literal["auto", "off"]
StoredToolPolicy = Literal["auto", "ask", "off"]
ConnectorStatus = Literal["connected", "needs_sign_in", "needs_key", "unreachable", "tools_changed", "disabled", "pending"]
CallOutcome = Literal["ok", "error", "denied"]


class ProbeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str | None = Field(default=None, max_length=2048)
    command: str | None = Field(default=None, max_length=2048)
    args: list[str] | None = Field(default=None, max_length=64)


class EnvEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    value: str | None = Field(default=None, max_length=8192)
    secret: bool = True
    member_supplied: bool = False


class OAuthClient(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: str = Field(..., min_length=1, max_length=512)
    client_secret: str | None = Field(default=None, max_length=2048)


class ConnectorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Scope
    name: str = Field(..., min_length=1, max_length=100)
    transport: Transport | None = None
    url: str | None = Field(default=None, max_length=2048)
    command: str | None = Field(default=None, max_length=2048)
    args: list[str] | None = Field(default=None, max_length=64)
    env: list[EnvEntry] | None = Field(default=None, max_length=64)
    headers: dict[str, str] | None = None
    auth: AuthMode | None = None
    oauth_client: OAuthClient | None = None


class ConnectorPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    enabled: bool | None = None
    url: str | None = Field(default=None, max_length=2048)
    command: str | None = Field(default=None, max_length=2048)
    args: list[str] | None = Field(default=None, max_length=64)
    auth: AuthMode | None = None


class ToolSetting(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    policy: ToolPolicy = "auto"


class ToolsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tools: dict[str, ToolSetting]


class MemberStateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    disabled_tools: list[str] | None = Field(default=None, max_length=512)


class SecretsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headers: dict[str, str] | None = None
    env: dict[str, str] | None = None


class OrgPolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allow_personal: bool = True
    allowed_hosts: list[str] = Field(default_factory=list, max_length=200)


# ── Response shapes ──────────────────────────────────────────────────────────


class MemberStateOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    disabled_tools: list[str]
    signed_in: bool
    has_key: bool
    signed_in_at: str | None
    # Best-effort identity of the signed-in account (from the provider's id_token); null when unknown.
    account_label: str | None = None


class EnvKeyOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    secret: bool
    has_value: bool
    member_supplied: bool


class HeaderKeyOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    has_value: bool


class ToolInfoOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    title: str | None
    description: str
    annotations: dict[str, bool]
    enabled: bool
    policy: StoredToolPolicy
    discovered_at: str | None
    is_new: bool


class ConnectorOut(BaseModel):
    """Connector (+ ``tools`` for ConnectorDetail)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    org_id: str
    scope: Scope
    owner_user_id: str | None
    name: str
    slug: str
    transport: Transport
    url: str | None
    command: str | None
    args: list[str]
    env_keys: list[EnvKeyOut]
    header_keys: list[HeaderKeyOut]
    auth: AuthMode
    status: ConnectorStatus
    status_detail: str | None
    protocol_version: str | None
    server_name: str | None
    enabled: bool
    tool_count: int
    enabled_tool_count: int
    # Tools added/removed by refresh-tools since the inventory was last saved (PUT /tools resets both).
    tools_added: int = 0
    tools_removed: int = 0
    # Members signed in to (or holding a key for) an org connector. Admin view only; otherwise 0.
    signed_in_count: int = 0
    # Gateway-relative icon route for remote connectors; null for sandbox (stdio) connectors.
    icon_url: str | None = None
    created_by: str
    created_at: str | None
    updated_at: str | None
    last_used_at: str | None
    my_state: MemberStateOut | None
    tools: list[ToolInfoOut] | None = None


class OrgPolicyOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allow_personal: bool
    allowed_hosts: list[str]
    updated_at: str | None


class ConnectorListOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connectors: list[ConnectorOut]
    policy: OrgPolicyOut
    is_admin: bool
    # Organization display name from the request's Clerk claims; null when the token carries none.
    org_name: str | None = None


class ToolCallOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    connector_id: str
    connector_name: str
    user_id: str
    # Display name/email for user_id when the gateway can resolve one; null otherwise.
    user_label: str | None = None
    run_id: str | None
    conversation_id: str | None
    tool: str
    outcome: CallOutcome
    duration_ms: int
    error: str | None
    called_at: str | None
