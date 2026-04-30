"""MCP settings for the gateway.

Cached because no test monkeypatches these vars after import.
If you add an env var here, audit tests/ for monkeypatch.setenv("YOUR_VAR")
before adding — if any test touches it, keep it as os.getenv (Class B).

Class A vars managed here: SP_MCP_ALLOWED_HOSTS

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


@lru_cache(maxsize=1)
def get_mcp_settings() -> McpSettings:
    """Return cached McpSettings instance.

    Safe to cache: SP_MCP_ALLOWED_HOSTS is not monkeypatched by any test in tests/
    (confirmed by grep before migration).
    """
    return McpSettings()
