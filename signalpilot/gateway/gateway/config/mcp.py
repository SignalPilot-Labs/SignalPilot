"""MCP settings for the gateway.

Cached because no test monkeypatches these vars after import.
If you add an env var here, audit tests/ for monkeypatch.setenv("YOUR_VAR")
before adding — if any test touches it, keep it as os.getenv (Class B).

Class A vars managed here: SP_MCP_ALLOWED_HOSTS, SP_MCP_OAUTH_DISABLED,
SP_MCP_OAUTH_RESOURCE_URL, SP_MCP_OAUTH_REQUIRE_AUDIENCE

Note: sp_mcp_allowed_hosts is a raw CSV string. The downstream parse in mcp/server.py
does the split/strip/extend — this module does not duplicate that logic, so the
existing server.py behavior is preserved bit-for-bit.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field

from ._base import _GatewaySettingsBase


class McpSettings(_GatewaySettingsBase):
    """Typed MCP configuration read from process environment at instantiation."""

    sp_mcp_allowed_hosts: str = Field("", alias="SP_MCP_ALLOWED_HOSTS")
    # OAuth resource-server behaviour for /mcp (cloud mode, Clerk as the AS).
    # Set SP_MCP_OAUTH_DISABLED=true to fall back to API-key-only auth.
    sp_mcp_oauth_disabled: bool = Field(False, alias="SP_MCP_OAUTH_DISABLED")
    # Canonical RFC 8707 resource identifier. Defaults to
    # ``{SP_PUBLIC_GATEWAY_URL}/mcp``; override when the MCP host differs.
    sp_mcp_oauth_resource_url: str = Field("", alias="SP_MCP_OAUTH_RESOURCE_URL")
    # Reject access tokens that carry no ``aud`` claim at all. Tokens with an
    # ``aud`` are always checked against the resource URL.
    sp_mcp_oauth_require_audience: bool = Field(True, alias="SP_MCP_OAUTH_REQUIRE_AUDIENCE")


@lru_cache(maxsize=1)
def get_mcp_settings() -> McpSettings:
    """Return cached McpSettings instance.

    Safe to cache: SP_MCP_ALLOWED_HOSTS is not monkeypatched by any test in tests/
    (confirmed by grep before migration).
    """
    return McpSettings()
