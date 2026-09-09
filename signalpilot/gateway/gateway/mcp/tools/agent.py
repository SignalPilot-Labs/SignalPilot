"""Cloud agent delegation on the existing MCP endpoint."""

from mcp.server.mcpserver import Context
from mcp.types import CallToolResult, TextContent, ToolAnnotations

from gateway.agent_execution.contracts import AgentRequest
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
        data = result.model_dump(exclude_none=True)
        lines = [
            f"SignalPilot {result.status} · {result.elapsed_seconds}s",
            f"thread_id: {result.thread_id}\nrun_id: {result.run_id}\nnext_sequence: {result.next_sequence}",
        ]
        for event in result.events:
            lines.append(str(event.get("label") or event.get("stage") or event.get("type", "Activity")))
            if event.get("sql_preview"):
                lines.append("```sql\n" + event["sql_preview"] + "\n```")
            for key in ("tool", "connection_name", "path", "activity", "rows", "row_count", "duration_ms", "status"):
                if key in event:
                    lines.append(f"{key}: {event[key]}")
        if result.heartbeat:
            lines.append(f"Still {result.status}; no new activity during this wait.")
        if result.summary:
            lines.append(result.summary)
        if result.question:
            lines.append(result.question)
        if result.error:
            lines.append(result.error)
        if result.verification:
            lines.extend(result.verification)
        if result.output:
            lines.extend(f"{key}: {value}" for key, value in result.output.items())
        lines.append(result.next_action)
        return CallToolResult(
            isError=result.status == "failed",
            structuredContent=data,
            content=[TextContent(type="text", text="\n\n".join(lines))],
        )
    except ValueError as exc:
        return CallToolResult(isError=True, content=[TextContent(type="text", text=str(exc))])


@audited_tool(mcp)
async def run_signalpilot_agent(
    task: str,
    project_id: str,
    revision: int,
    connection_name: str,
    ctx: Context,
    branch: str = "main",
    max_turns: int = 24,
    timeout_seconds: int = 1200,
    client_request_id: str | None = None,
) -> CallToolResult:
    """Delegate work on an immutable cloud workspace revision to SignalPilot.

    Returns a queued thread immediately. Call wait_signalpilot_agent repeatedly,
    narrating new evidence to the user, until terminal status and has_more=false.
    Runs in cloud Docker.
    Reuse client_request_id when retrying a launch to avoid duplicate execution.
    """
    try:
        request = AgentRequest(
            task=task,
            project_id=project_id,
            revision=revision,
            connection_name=connection_name,
            branch=branch,
            max_turns=max_turns,
            timeout_seconds=timeout_seconds,
            client_request_id=client_request_id,
        )
    except ValueError:
        return CallToolResult(
            isError=True, content=[TextContent(type="text", text="Invalid or out-of-bounds agent request")]
        )
    return await _call(AgentService().start, request)


@audited_tool(mcp)
async def continue_signalpilot_agent(thread_id: str, task: str, ctx: Context) -> CallToolResult:
    """Continue your completed or input-required thread using its output snapshot."""
    return await _call(AgentService().resume, thread_id, task)


@audited_tool(mcp, annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True))
async def wait_signalpilot_agent(
    thread_id: str, after_sequence: int = 0, run_id: str | None = None, wait_seconds: float = 20
) -> CallToolResult:
    """Wait up to 25 seconds for new agent activity; narrate returned evidence.

    Pass returned next_sequence as after_sequence on the next wait and retain run_id.
    Keep waiting until completed, input_required, cancelled, or failed, then drain
    remaining pages while has_more=true. Disconnecting
    this call does not cancel the background job. Use cancel_signalpilot_agent to stop it.
    """
    return await _call(AgentService().wait, thread_id, after_sequence, run_id, wait_seconds)


@audited_tool(mcp, annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True))
async def get_signalpilot_agent(thread_id: str) -> CallToolResult:
    """Read your thread status and renew its short-lived artifact download links."""
    return await _call(AgentService().get, thread_id)


@audited_tool(mcp)
async def cancel_signalpilot_agent(thread_id: str) -> CallToolResult:
    """Cancel your active agent turn and revoke its database access immediately."""
    return await _call(AgentService().cancel, thread_id)
