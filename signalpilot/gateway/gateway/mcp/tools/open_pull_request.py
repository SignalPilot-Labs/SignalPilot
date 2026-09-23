"""open_pull_request: the chat agent opens a GitHub PR for the branch it pushed.

Bound to the run's project (contextvars set by the session token); the
agent cannot choose another project. The conversation is resolved from the
run id so only branches this chat pushed are eligible and the PR body links
back to the chat. The shared helpers here are reused by
update_pull_request and comment_on_pull_request.
"""

from __future__ import annotations

from sqlalchemy import select

from gateway.errors.mcp import sanitize_mcp_error
from gateway.mcp.audit import audited_tool
from gateway.mcp.context import (
    _store_session,
    mcp_execution_identity_var,
    mcp_org_id_var,
    mcp_project_id_var,
)
from gateway.mcp.server import mcp


def denial(tool_name: str) -> str | None:
    identity = mcp_execution_identity_var.get(None) or ""
    if not identity.startswith("chat:"):
        return f"Error: {tool_name} requires a chat execution identity"
    return None


def run_bindings() -> tuple[str, str, str | None]:
    """(run_id, org_id, project_id) for the calling chat run."""
    identity = mcp_execution_identity_var.get(None) or ""
    org_id = mcp_org_id_var.get(None) or "local"
    return identity.removeprefix("chat:"), org_id, mcp_project_id_var.get(None)


async def _conversation_id(session, run_id: str, org_id: str) -> str | None:
    from gateway.db.models import GatewayChatRun

    return (
        await session.execute(
            select(GatewayChatRun.conversation_id).where(
                GatewayChatRun.id == run_id, GatewayChatRun.org_id == org_id
            )
        )
    ).scalar_one_or_none()


async def conversation_for_run(session, run_id: str, org_id: str) -> str | None:
    """Module-level indirection so tests can patch ``_conversation_id``."""
    return await _conversation_id(session, run_id, org_id)


def tool_error(exc: Exception) -> dict:
    """AgentPrError messages are safe to show; anything else is reduced to its type."""
    from gateway.git.agent_pr import AgentPrError

    if isinstance(exc, AgentPrError):
        return {"error": sanitize_mcp_error(str(exc))}
    return {"error": f"pull request operation failed: {type(exc).__name__}"}


@audited_tool(mcp)
async def open_pull_request(title: str, body: str = "", draft: bool = False, branch: str = "") -> dict:
    """
    Open a GitHub pull request for the branch you pushed.

    Do these steps before you call this tool:
    1. Commit your changes.
    2. Push your branch with: git push origin HEAD:signalpilot/<name>
    3. Run dbt_execute with command "build" for the models you changed.
    4. Write the list of changed models and the build result in the body.

    The tool opens the pull request on GitHub. The project must be linked
    to a GitHub repository. If the branch already has an open pull request,
    the tool returns that pull request. A person merges the pull request
    on GitHub. The tool does not merge.

    The tool returns the pull request URL. Put the URL in your final
    answer so the user can open the pull request.

    Args:
        title: Short title for the pull request. Required.
        body: Description of the change. List the models you changed, what
            changed in each model, and the dbt build result.
        draft: Set true to open the pull request as a draft.
        branch: The pushed branch name, for example signalpilot/add-mart.
            Leave empty to use the branch you pushed most recently.

    Returns:
        A dict with pr_url, pr_number, github_branch, and draft. On failure
        the dict has an error field with the reason.
    """
    if err := denial("open_pull_request"):
        return {"error": err}
    run_id, org_id, project_id = run_bindings()
    if not project_id:
        return {"error": "this session has no project binding"}

    from gateway.git.agent_pr import open_pull_request as _open

    try:
        async with _store_session() as store:
            conversation_id = await conversation_for_run(store.session, run_id, org_id)
            record = await _open(
                store.session,
                org_id=org_id,
                project_id=project_id,
                conversation_id=conversation_id,
                title=title,
                body=body,
                draft=bool(draft),
                github_branch=branch or None,
                actor="agent",
            )
    except Exception as exc:  # never leak provider/credential internals
        return tool_error(exc)

    return {
        "pr_url": record.pr_url,
        "pr_number": record.pr_number,
        "github_branch": record.github_branch,
        "draft": bool(record.draft),
    }
