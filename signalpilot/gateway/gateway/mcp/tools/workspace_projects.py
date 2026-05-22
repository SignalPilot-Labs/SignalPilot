"""MCP tool: list_workspace_projects — list notebook projects with git/GitHub status."""

from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _store_session, mcp_org_id_var, mcp_user_id_var
from gateway.mcp.server import mcp


@audited_tool(mcp)
async def list_workspace_projects() -> str:
    """List all notebook workspace projects with their status, source, and branch info.

    Returns project ID (needed for run_notebook), name, source (managed/github),
    default branch, and file count.
    """
    org_id = mcp_org_id_var.get(None) or "local"
    user_id = mcp_user_id_var.get(None) or "local"

    async with _store_session(user_id=user_id, org_id=org_id) as store:
        projects, total = await store.list_workspace_projects(status="active", limit=50)

    if not projects:
        return "No workspace projects found. Create one in the SignalPilot IDE."

    lines = [f"Found {total} workspace project(s):\n"]
    for p in projects:
        source_tag = f"[{p.source}]" if p.source != "managed" else ""
        git_remote = f"  remote: {p.git_remote}" if p.git_remote else ""
        lines.append(
            f"  - {p.display_name}  (id={p.id})  branch={p.default_branch or 'main'}  "
            f"files={p.file_count}  {source_tag}"
        )
        if git_remote:
            lines.append(git_remote)
    return "\n".join(lines)
