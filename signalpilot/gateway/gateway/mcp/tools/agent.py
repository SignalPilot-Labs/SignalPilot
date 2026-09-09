"""Launch and observe the existing Chats agent over MCP."""

from typing import Literal

from mcp.server.mcpserver import Context
from mcp.types import CallToolResult, TextContent, ToolAnnotations

from gateway.agent_execution.contracts import AgentLaunchRequest
from gateway.agent_execution.service import AgentService
from gateway.mcp.audit import audited_tool
from gateway.mcp.context import mcp_org_id_var, mcp_user_id_var
from gateway.mcp.server import mcp


async def _call(operation, *args):
    org_id, user_id = mcp_org_id_var.get(None), mcp_user_id_var.get(None)
    if not org_id or not user_id:
        return CallToolResult(
            isError=True, content=[TextContent(type="text", text="Authenticated organization and user required")]
        )
    try:
        result = await operation(org_id, user_id, *args)
        data = result.model_dump(mode="json", exclude_none=True)
        lines = [f"SignalPilot {data.get('status', 'chat context')}"]
        if data.get("chat_url"):
            lines.append(data["chat_url"])
        if data.get("next_action"):
            lines.append(data["next_action"])
        return CallToolResult(
            isError=data.get("status") == "failed",
            structuredContent=data,
            content=[TextContent(type="text", text="\n\n".join(lines))],
        )
    except ValueError as exc:
        return CallToolResult(isError=True, content=[TextContent(type="text", text=str(exc))])


@audited_tool(mcp)
async def run_signalpilot_agent(
    task: str,
    ctx: Context,
    project_id: str | None = None,
    connection_name: str | None = None,
    branch: str | None = None,
    client_request_id: str | None = None,
) -> CallToolResult:
    """Delegate a task to SignalPilot using saved Settings → MCP Connect defaults.

    Only task is required. Project, connection and branch override saved defaults.
    Uses the same agent, configured authentication, sandbox, and Git commit as Chats.
    If setup is missing, direct the user to Settings → MCP Connect.
    Do not search source code or local files to guess workspace IDs or connections.

    Returns a queued thread and chat_url immediately. Let the user watch Chats.
    Wait only when the calling task needs a result or the user asks for progress.
    Do not continuously poll or narrate routine activity after launching.
    Reuse client_request_id when retrying a launch to avoid duplicate execution.
    """
    try:
        request = AgentLaunchRequest(
            task=task,
            project_id=project_id,
            connection_name=connection_name,
            branch=branch,
            client_request_id=client_request_id,
        )
    except ValueError:
        return CallToolResult(
            isError=True, content=[TextContent(type="text", text="Invalid or out-of-bounds agent request")]
        )
    return await _call(AgentService().start, request)


@audited_tool(mcp)
async def continue_signalpilot_agent(thread_id: str, task: str, ctx: Context) -> CallToolResult:
    """Continue the same chat through its normal follow-up or clarification flow."""
    return await _call(AgentService().resume, thread_id, task)


@audited_tool(mcp, annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True))
async def wait_signalpilot_agent(
    thread_id: str, after_sequence: int = 0, run_id: str | None = None, wait_seconds: float = 20,
    detail: Literal["summary", "full"] = "summary",
) -> CallToolResult:
    """Wait up to 25 seconds only when a result or requested progress is needed.

    Pass returned next_sequence as after_sequence on the next wait and retain run_id.
    Summary mode omits repetitive deltas and large tool inputs/results.
    Request full detail only for debugging, or read one event by its sequence.
    Disconnecting
    this call does not cancel the background job. Use cancel_signalpilot_agent to stop it.
    """
    return await _call(AgentService().wait, thread_id, after_sequence, run_id, wait_seconds, detail)


@audited_tool(mcp, annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True))
async def get_signalpilot_agent(
    thread_id: str, after_sequence: int = 0, run_id: str | None = None,
    detail: Literal["summary", "full"] = "summary",
) -> CallToolResult:
    """Read compact status and new activity; full event details are opt-in.

    Reuse next_sequence as after_sequence to avoid rereading previous activity.
    Substantive results and diagnostics are returned once in structuredContent.
    """
    return await _call(AgentService().get, thread_id, after_sequence, run_id, detail)


@audited_tool(mcp, annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True))
async def get_signalpilot_agent_event(thread_id: str, sequence: int, run_id: str | None = None) -> CallToolResult:
    """Read one original stored event on demand by exact sequence; retain its run_id."""
    return await _call(AgentService().get, thread_id, 0, run_id, "full", sequence)


@audited_tool(mcp, annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True))
async def get_signalpilot_agent_context(
    thread_id: str, after_message_sequence: int = 0, limit: int = 20,
) -> CallToolResult:
    """Read paginated user/assistant chat messages only when context is needed.

    Pass next_message_sequence as after_message_sequence for the next page.
    Tool payloads are not duplicated here; read a specific event for tool details.
    """
    return await _call(AgentService().context, thread_id, after_message_sequence, limit)


@audited_tool(mcp)
async def cancel_signalpilot_agent(thread_id: str) -> CallToolResult:
    """Request cancellation through the same lifecycle as stopping a run in Chats."""
    return await _call(AgentService().cancel, thread_id)
