"""gateway.mcp — FastMCP package for SignalPilot.

Import order matters: server must be first (creates mcp instance),
then context, validation, helpers, audit, and finally tools (which
register tool functions via @audited_tool(mcp) at decorator time).
"""

from __future__ import annotations

from gateway.mcp import (
    audit,  # noqa: F401
    context,  # noqa: F401
    helpers,  # noqa: F401
    server,  # noqa: F401
    tools,  # noqa: F401 — triggers all @audited_tool(mcp) registrations
    validation,  # noqa: F401
)
