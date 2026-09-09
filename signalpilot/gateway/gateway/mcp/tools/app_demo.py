"""Small, read-only MCP Apps smoke demo; no agent or database execution."""

from datetime import datetime, timezone
from pathlib import Path

from mcp.types import CallToolResult, TextContent, ToolAnnotations

from gateway.mcp.audit import audited_tool
from gateway.mcp.server import mcp

URI = "ui://signalpilot/demo-v1.html"
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True)


@mcp.resource(URI, mime_type="text/html;profile=mcp-app", meta={"ui": {"prefersBorder": True}})
def signalpilot_demo_ui() -> str:
    return Path(__file__).with_suffix(".html").read_text(encoding="utf-8")


@audited_tool(mcp, annotations=READ_ONLY, meta={"ui": {"resourceUri": URI}})
async def show_signalpilot_app_demo() -> CallToolResult:
    """Show the interactive SignalPilot MCP App demo card. No agents or SQL run.

    Call once and let the user click the card's Ping gateway button.
    Do not poll or simulate the interface in text.
    """
    return CallToolResult(
        content=[TextContent(type="text", text="SignalPilot demo ready. Click Ping gateway in the interactive card.")],
        structuredContent={"server_time": datetime.now(timezone.utc).isoformat(), "message": "MCP App loaded"},
    )


@audited_tool(mcp, annotations=READ_ONLY, meta={"ui": {"resourceUri": URI, "visibility": ["app"]}})
async def ping_signalpilot_app_demo() -> CallToolResult:
    """Read the gateway clock from the demo UI. No data access or agent execution."""
    return CallToolResult(
        content=[TextContent(type="text", text="Gateway ping successful")],
        structuredContent={"server_time": datetime.now(timezone.utc).isoformat(), "message": "Gateway ping successful"},
    )
