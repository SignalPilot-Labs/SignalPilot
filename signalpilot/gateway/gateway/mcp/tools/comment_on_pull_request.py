"""comment_on_pull_request: the chat agent posts a comment on its open PR."""

from __future__ import annotations

from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _store_session
from gateway.mcp.server import mcp
from gateway.mcp.tools.open_pull_request import conversation_for_run, denial, run_bindings, tool_error


@audited_tool(mcp)
async def comment_on_pull_request(body: str, pr_number: int = 0) -> dict:
    """
    Post a comment on the pull request you opened.

    Use this tool to report a new build result, to answer a review
    comment, or to explain a follow-up push. Push your branch and open
    the pull request first.

    The tool returns the pull request URL and the comment URL. Put the
    pull request URL in your final answer. A person merges the pull
    request on GitHub.

    Args:
        body: The comment text. Required.
        pr_number: The pull request number. Leave 0 to use the open pull
            request of this chat.

    Returns:
        A dict with pr_url, pr_number, and comment_url. On failure the dict
        has an error field with the reason.
    """
    if err := denial("comment_on_pull_request"):
        return {"error": err}
    run_id, org_id, project_id = run_bindings()
    if not project_id:
        return {"error": "this session has no project binding"}

    from gateway.git.agent_pr import comment_on_pull_request as _comment

    try:
        async with _store_session() as store:
            conversation_id = await conversation_for_run(store.session, run_id, org_id)
            result = await _comment(
                store.session,
                org_id=org_id,
                project_id=project_id,
                conversation_id=conversation_id,
                body=body,
                pr_number=pr_number or None,
                actor="agent",
            )
    except Exception as exc:
        return tool_error(exc)
    return result
