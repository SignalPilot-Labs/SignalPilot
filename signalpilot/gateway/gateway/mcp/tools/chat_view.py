"""MCP App resource (SignalPilot Pulse) and its app-only run reader."""

from pathlib import Path

from mcp.types import CallToolResult, TextContent, ToolAnnotations

from gateway.mcp.audit import audited_tool
from gateway.mcp.context import mcp_org_id_var, mcp_user_id_var
from gateway.mcp.server import mcp
from gateway.mcp.tools.chat_errors import chat_failure

PULSE_APP_URI = "ui://signalpilot/pulse-v1.html"
PULSE_APP_PATH = Path(__file__).parent.parent / "apps" / "pulse.html"


@mcp.resource(PULSE_APP_URI, mime_type="text/html;profile=mcp-app", meta={"ui": {"prefersBorder": False}})
def signalpilot_pulse_ui() -> str:
    if not PULSE_APP_PATH.is_file():
        raise ValueError(
            "SignalPilot Pulse app bundle is missing. Run `npm run build` in signalpilot-mcp-app/ "
            "or rebuild the gateway image."
        )
    return PULSE_APP_PATH.read_text(encoding="utf-8")


@audited_tool(
    mcp,
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True),
    meta={"ui": {"resourceUri": PULSE_APP_URI, "visibility": ["app"]}},
)
async def read_signalpilot_chat_view(
    thread_id: str, run_id: str | None = None,
    after_sequence: int = 0, after_message_sequence: int = 0,
) -> CallToolResult:
    """Read the display-safe run activity without tool inputs or results.

    Retain run_id and both cursors between reads. No model narration is needed.
    """
    org_id, user_id = mcp_org_id_var.get(None), mcp_user_id_var.get(None)
    if not org_id or not user_id:
        return CallToolResult(isError=True, content=[TextContent(type="text", text="Authenticated organization and user required")])
    from gateway.agent_execution.chat_view_service import read_chat_view

    try:
        data = await read_chat_view(org_id, user_id, thread_id, run_id, after_sequence, after_message_sequence)
    except Exception as exc:
        return chat_failure(exc, read_chat_view)
    return CallToolResult(
        structuredContent=data,
        content=[TextContent(type="text", text="SignalPilot activity updated")],
    )
