"""Pull request lifecycle for branches the chat agent pushed to the git server.

The publish model: the agent runs plain ``git push origin HEAD:signalpilot/<name>``
against the gateway git server. The server records each accepted push in
``gateway_agent_pull_requests`` (status ``pushed``, ``last_pushed_sha``,
``repo_full_name``, ``base_branch``, ``conversation_id``) and mirrors the
branch to GitHub. This module opens, updates and comments on GitHub pull
requests for those pushed branches. There is no approval gate: the agent
opens pull requests on its own and a person merges them on GitHub.

Every write is confined to records of the calling conversation when the
actor is the agent. Human REST callers (``actor != "agent"``) may target any
record of the project. Tokens are repo-scoped installation tokens and are
never logged.
"""

from __future__ import annotations

import logging
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import GatewayAgentPullRequest
from ..models.github import AgentPullRequestInfo

logger = logging.getLogger(__name__)

ATTRIBUTION_MARKER = "Opened by SignalPilot"
PUSH_FIRST = "Push your branch first with git push origin HEAD:signalpilot/<name>"


class AgentPrError(Exception):
    """The pull request operation failed; the message is safe to show."""


def attribution_line(conversation_id: str | None) -> str:
    from ..config.github import get_github_settings

    if conversation_id:
        web = get_github_settings().sp_web_url.rstrip("/")
        return f"{ATTRIBUTION_MARKER} from chat {web}/chats/{conversation_id}"
    return ATTRIBUTION_MARKER


def strip_attribution(body: str) -> str:
    """Remove a trailing attribution block so it can be re-appended once."""
    text = (body or "").rstrip()
    lines = text.splitlines()
    if lines and lines[-1].startswith(ATTRIBUTION_MARKER):
        lines = lines[:-1]
        while lines and lines[-1].strip() in ("", "---"):
            lines.pop()
    return "\n".join(lines).rstrip()


def build_body(body: str, conversation_id: str | None) -> str:
    """Body text followed by exactly one attribution line."""
    text = strip_attribution(body)
    line = attribution_line(conversation_id)
    return f"{text}\n\n---\n{line}\n" if text else f"{line}\n"


# Record access (ORM rows are mutated here; the store exposes read helpers only).


async def _row_by_id(session: AsyncSession, record_id: str) -> GatewayAgentPullRequest:
    row = (
        await session.execute(select(GatewayAgentPullRequest).where(GatewayAgentPullRequest.id == record_id))
    ).scalar_one_or_none()
    if row is None:
        raise AgentPrError("pull request record not found")
    return row


async def _row_by_pr_number(
    session: AsyncSession, *, org_id: str, project_id: str, pr_number: int
) -> GatewayAgentPullRequest | None:
    return (
        await session.execute(
            select(GatewayAgentPullRequest).where(
                GatewayAgentPullRequest.org_id == org_id,
                GatewayAgentPullRequest.project_id == project_id,
                GatewayAgentPullRequest.pr_number == pr_number,
            )
        )
    ).scalar_one_or_none()


def _check_conversation(row_conversation: str | None, conversation_id: str | None, actor: str) -> None:
    """Agents only touch records of their own conversation."""
    if actor != "agent":
        return
    if row_conversation and row_conversation != conversation_id:
        raise AgentPrError("this branch belongs to another chat; push your own branch first")


async def _resolve_target(
    session: AsyncSession,
    *,
    org_id: str,
    project_id: str,
    conversation_id: str | None,
    pr_number: int | None,
    actor: str,
) -> GatewayAgentPullRequest:
    """The record with ``pr_number``, or the single open PR of the conversation."""
    from ..store import github_prs

    if pr_number:
        row = await _row_by_pr_number(session, org_id=org_id, project_id=project_id, pr_number=pr_number)
        if row is None:
            raise AgentPrError(f"pull request #{pr_number} was not opened by SignalPilot for this project")
        _check_conversation(row.conversation_id, conversation_id, actor)
        return row
    if not conversation_id:
        raise AgentPrError("pr_number is required")
    open_prs = await github_prs.list_open_prs_for_conversation(
        session, org_id=org_id, project_id=project_id, conversation_id=conversation_id
    )
    if not open_prs:
        raise AgentPrError("this chat has no open pull request; open one first with open_pull_request")
    if len(open_prs) > 1:
        numbers = ", ".join(f"#{p.pr_number}" for p in open_prs)
        raise AgentPrError(f"this chat has several open pull requests ({numbers}); pass pr_number")
    return await _row_by_id(session, open_prs[0].id)


# GitHub access.


async def _github_client(session: AsyncSession, *, org_id: str, project_id: str):
    """(client, link) for the project's active installation. Token stays in the client."""
    from ..github_bot.client import GitHubBotClient
    from ..store import github as gh_store

    link = await gh_store.get_repo_link_for_project(session, org_id=org_id, project_id=project_id)
    if link is None:
        raise AgentPrError("this project is not linked to GitHub")
    installation = await gh_store.get_installation(session, org_id=org_id, installation_id=link.installation_id)
    if installation is None or installation.status != "active":
        raise AgentPrError("the GitHub App installation for this project is not active")
    try:
        token = await gh_store.get_valid_token(session, installation)
    except Exception as exc:
        raise AgentPrError(f"could not obtain a GitHub token: {type(exc).__name__}") from exc
    return GitHubBotClient(token), link


def _github_error_message(exc: Exception) -> str:
    """Short, credential-free description of a GitHub API failure."""
    import httpx

    if isinstance(exc, httpx.HTTPStatusError):
        detail = ""
        try:
            payload = exc.response.json()
            detail = str(payload.get("message") or "")
            errors = payload.get("errors") or []
            if errors and isinstance(errors, list):
                first = errors[0]
                if isinstance(first, dict) and first.get("message"):
                    detail = f"{detail}: {first['message']}" if detail else str(first["message"])
        except Exception:
            pass
        return f"GitHub returned {exc.response.status_code}" + (f": {detail}" if detail else "")
    return f"{type(exc).__name__}: {exc}"[:500]


def _info(row: GatewayAgentPullRequest) -> AgentPullRequestInfo:
    from ..store.github_prs import _to_info

    return _to_info(row)


# Public operations.


async def get_record(session: AsyncSession, *, org_id: str, record_id: str) -> AgentPullRequestInfo | None:
    """One record by id, scoped to the org (REST id-addressed routes)."""
    row = (
        await session.execute(
            select(GatewayAgentPullRequest).where(
                GatewayAgentPullRequest.id == record_id, GatewayAgentPullRequest.org_id == org_id
            )
        )
    ).scalar_one_or_none()
    return _info(row) if row else None


async def open_pull_request(
    session: AsyncSession,
    *,
    org_id: str,
    project_id: str,
    conversation_id: str | None,
    title: str,
    body: str = "",
    draft: bool = False,
    github_branch: str | None = None,
    base_branch: str | None = None,
    actor: str = "agent",
) -> AgentPullRequestInfo:
    """Open a GitHub pull request for a pushed branch.

    Resolves ``github_branch`` explicitly or as the conversation's latest
    push. Idempotent: an existing open PR on the branch is returned as is.
    """
    from ..store import github_prs

    title = (title or "").strip()
    if not title:
        raise AgentPrError("title is required")

    branch = (github_branch or "").strip()
    if branch:
        record = await github_prs.get_branch_record(
            session, org_id=org_id, project_id=project_id, github_branch=branch
        )
        if record is None:
            raise AgentPrError(f"branch {branch!r} has no push record for this project. {PUSH_FIRST}")
        _check_conversation(record.conversation_id, conversation_id, actor)
    else:
        if not conversation_id:
            raise AgentPrError("github_branch is required")
        record = await github_prs.latest_branch_for_conversation(
            session, org_id=org_id, project_id=project_id, conversation_id=conversation_id
        )
        if record is None:
            raise AgentPrError(f"this chat has not pushed a branch yet. {PUSH_FIRST}")

    if not record.last_pushed_sha:
        raise AgentPrError(f"branch {record.github_branch!r} has no pushed commit. {PUSH_FIRST}")
    if not (record.repo_full_name or "").strip():
        raise AgentPrError("this project is not linked to GitHub")
    if record.status == "open" and record.pr_number:
        return record
    if record.status in ("merged", "closed"):
        raise AgentPrError(
            f"pull request #{record.pr_number} for {record.github_branch!r} is already {record.status}. "
            "Push a new branch to open another pull request"
        )

    client, link = await _github_client(session, org_id=org_id, project_id=project_id)
    base = (base_branch or "").strip() or record.base_branch or link.default_branch or "main"
    link_conversation = record.conversation_id or conversation_id
    row = await _row_by_id(session, record.id)
    try:
        pr = await client.create_pull_request(
            record.repo_full_name,
            title=title,
            head=record.github_branch,
            base=base,
            body=build_body(body, link_conversation),
            draft=bool(draft),
        )
    except Exception as exc:
        message = _github_error_message(exc)
        logger.warning("agent PR: open failed for %s/%s: %s", project_id, record.github_branch, message)
        row.status = "pushed"
        row.error_message = message[:2000]
        row.updated_at = time.time()
        await session.commit()
        raise AgentPrError(message) from exc
    finally:
        await client.aclose()

    row.status = "open"
    row.pr_number = pr.get("number")
    row.pr_url = pr.get("html_url")
    row.title = title
    row.draft = bool(draft)
    row.base_branch = base
    row.error_message = None
    row.created_by = row.created_by or actor
    if row.conversation_id is None and conversation_id:
        row.conversation_id = conversation_id
    row.updated_at = time.time()
    await session.commit()
    logger.info(
        "agent PR opened: %s#%s from %s (project %s)", record.repo_full_name, row.pr_number,
        row.github_branch, project_id,
    )
    return _info(row)


async def update_pull_request(
    session: AsyncSession,
    *,
    org_id: str,
    project_id: str,
    conversation_id: str | None,
    pr_number: int | None = None,
    title: str | None = None,
    body: str | None = None,
    draft: bool | None = None,
    actor: str = "agent",
) -> AgentPullRequestInfo:
    """Edit the title and body of an open pull request.

    ``draft`` is accepted for API symmetry but ignored: the REST API cannot
    toggle draft state, so the stored flag is left unchanged.
    """
    row = await _resolve_target(
        session, org_id=org_id, project_id=project_id, conversation_id=conversation_id,
        pr_number=pr_number, actor=actor,
    )
    if row.status != "open" or not row.pr_number:
        raise AgentPrError(f"pull request for {row.github_branch!r} is {row.status}, not open")
    new_title = (title or "").strip() or None
    new_body = build_body(body, row.conversation_id) if body is not None else None
    if new_title is None and new_body is None:
        raise AgentPrError("nothing to update; pass a title or a body")

    client, _link = await _github_client(session, org_id=org_id, project_id=project_id)
    try:
        await client.update_pull_request(row.repo_full_name, row.pr_number, title=new_title, body=new_body)
    except Exception as exc:
        message = _github_error_message(exc)
        logger.warning("agent PR: update failed for %s#%s: %s", row.repo_full_name, row.pr_number, message)
        raise AgentPrError(message) from exc
    finally:
        await client.aclose()

    if new_title:
        row.title = new_title
    row.error_message = None
    row.updated_at = time.time()
    await session.commit()
    return _info(row)


async def comment_on_pull_request(
    session: AsyncSession,
    *,
    org_id: str,
    project_id: str,
    conversation_id: str | None,
    body: str,
    pr_number: int | None = None,
    actor: str = "agent",
) -> dict:
    """Post an issue comment on the targeted pull request."""
    text = (body or "").strip()
    if not text:
        raise AgentPrError("comment body is required")
    row = await _resolve_target(
        session, org_id=org_id, project_id=project_id, conversation_id=conversation_id,
        pr_number=pr_number, actor=actor,
    )
    if not row.pr_number:
        raise AgentPrError(f"branch {row.github_branch!r} has no pull request yet; open one first")

    client, _link = await _github_client(session, org_id=org_id, project_id=project_id)
    try:
        comment = await client.create_issue_comment(row.repo_full_name, row.pr_number, text)
    except Exception as exc:
        message = _github_error_message(exc)
        logger.warning("agent PR: comment failed for %s#%s: %s", row.repo_full_name, row.pr_number, message)
        raise AgentPrError(message) from exc
    finally:
        await client.aclose()

    row.updated_at = time.time()
    await session.commit()
    return {"pr_url": row.pr_url, "pr_number": row.pr_number, "comment_url": comment.get("html_url")}
