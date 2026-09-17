"""update_pull_request: the chat agent edits the title or body of its open PR."""

from __future__ import annotations

from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _store_session
from gateway.mcp.server import mcp
from gateway.mcp.tools.open_pull_request import conversation_for_run, denial, run_bindings, tool_error


@audited_tool(mcp)
async def update_pull_request(title: str = "", body: str = "", pr_number: int = 0) -> dict:
    """
    Change the title or the body of the pull request you opened.

    Use this tool after you push more commits to the same branch. Write
    the updated list of changed models and the new build result in the
    body. Leave title empty to keep the current title. Leave body empty to
    keep the current body.

    The tool returns the pull request URL. Put the URL in your final
    answer. A person merges the pull request on GitHub.

    Args:
        title: New title. Leave empty to keep the current title.
        body: New description. Leave empty to keep the current body.
        pr_number: The pull request number. Leave 0 to use the open pull
            request of this chat.

    Returns:
        A dict with pr_url and pr_number. On failure the dict has an error
        field with the reason.
    """
    if err := denial("update_pull_request"):
        return {"error": err}
    run_id, org_id, project_id = run_bindings()
    if not project_id:
        return {"error": "this session has no project binding"}

    from gateway.git.agent_pr import update_pull_request as _update

    try:
        async with _store_session() as store:
            conversation_id = await conversation_for_run(store.session, run_id, org_id)
            record = await _update(
                store.session,
                org_id=org_id,
                project_id=project_id,
                conversation_id=conversation_id,
                pr_number=pr_number or None,
                title=title or None,
                body=body or None,
                actor="agent",
            )
    except Exception as exc:
        return tool_error(exc)
    return {"pr_url": record.pr_url, "pr_number": record.pr_number}
