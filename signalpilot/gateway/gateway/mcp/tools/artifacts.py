"""Discover saved chat files and issue explicit batch downloads."""

import json

from mcp.types import CallToolResult, TextContent, ToolAnnotations

from gateway.agent_execution.artifacts import read_artifacts
from gateway.mcp.audit import audited_tool
from gateway.mcp.context import mcp_org_id_var, mcp_user_id_var
from gateway.mcp.server import mcp
from .chat_errors import chat_failure


async def _read(thread_id, artifact_ids=None):
    org_id, user_id = mcp_org_id_var.get(None), mcp_user_id_var.get(None)
    if not org_id or not user_id:
        return CallToolResult(isError=True, content=[TextContent(type="text", text="Authenticated organization and user required")])
    try:
        data = await read_artifacts(org_id, user_id, thread_id, artifact_ids)
        return CallToolResult(structuredContent=data, content=[TextContent(
            type="text", text=json.dumps(data, ensure_ascii=False, separators=(",", ":")),
        )])
    except ValueError as exc:
        return CallToolResult(isError=True, content=[TextContent(type="text", text=str(exc))])
    except Exception as exc:
        return chat_failure(exc, read_artifacts)


@audited_tool(mcp, annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True))
async def list_artifacts(thread_id: str) -> CallToolResult:
    """List saved artifacts in a chat's current manifest, including IDs, filenames, sizes and SHA-256 hashes. No file contents or download links are fetched. Files may still change while the agent runs."""
    return await _read(thread_id)


@audited_tool(mcp, annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True))
async def download_artifacts(thread_id: str, artifact_ids: list[str]) -> CallToolResult:
    """Get two-minute, single-use gateway links for 1 to 20 artifact IDs. Maximum total size is 100 MiB. Follow the returned POST instructions to download with agent HTTP tools; browsers show a download button. No S3 URL is returned. Treat URL fragments as temporary credentials. Failed downloads require a new link."""
    return await _read(thread_id, artifact_ids)
