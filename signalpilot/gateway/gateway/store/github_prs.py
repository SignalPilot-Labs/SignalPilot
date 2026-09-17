"""Store operations for agent-opened pull requests (gateway_agent_pull_requests)."""

from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import GatewayAgentPullRequest, GatewayGitHubRepoLink
from ..models.github import AgentPullRequestInfo

# "pushed": the branch is on GitHub (or recorded locally) with no pull request yet.
PR_STATUSES = ("pushed", "open", "merged", "closed", "error")


def _to_info(row: GatewayAgentPullRequest) -> AgentPullRequestInfo:
    return AgentPullRequestInfo(
        id=row.id,
        org_id=row.org_id,
        project_id=row.project_id,
        conversation_id=row.conversation_id,
        repo_full_name=row.repo_full_name,
        source_branch=row.source_branch,
        github_branch=row.github_branch,
        base_branch=row.base_branch,
        pr_number=row.pr_number,
        pr_url=row.pr_url,
        title=row.title,
        status=row.status,
        error_message=row.error_message,
        export_commit_sha=row.export_commit_sha,
        last_pushed_sha=row.last_pushed_sha,
        last_pushed_at=row.last_pushed_at,
        draft=bool(row.draft),
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def create_pull_request_record(
    session: AsyncSession,
    *,
    org_id: str,
    project_id: str,
    repo_full_name: str,
    source_branch: str,
    github_branch: str,
    base_branch: str,
    title: str,
    created_by: str,
    conversation_id: str | None = None,
    export_commit_sha: str | None = None,
    pr_number: int | None = None,
    pr_url: str | None = None,
    status: str = "open",
    error_message: str | None = None,
) -> AgentPullRequestInfo:
    if status not in PR_STATUSES:
        raise ValueError(f"invalid pull request status {status!r}")
    now = time.time()
    row = GatewayAgentPullRequest(
        org_id=org_id,
        project_id=project_id,
        conversation_id=conversation_id,
        repo_full_name=repo_full_name,
        source_branch=source_branch,
        github_branch=github_branch,
        base_branch=base_branch,
        pr_number=pr_number,
        pr_url=pr_url,
        title=title,
        status=status,
        error_message=error_message[:2000] if error_message else None,
        export_commit_sha=export_commit_sha,
        created_by=created_by,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.commit()
    return _to_info(row)


async def list_pull_requests(
    session: AsyncSession, *, org_id: str, project_id: str | None = None, limit: int = 100
) -> list[AgentPullRequestInfo]:
    q = select(GatewayAgentPullRequest).where(GatewayAgentPullRequest.org_id == org_id)
    if project_id:
        q = q.where(GatewayAgentPullRequest.project_id == project_id)
    result = await session.execute(q.order_by(GatewayAgentPullRequest.created_at.desc()).limit(limit))
    return [_to_info(r) for r in result.scalars().all()]


async def mark_pull_request_closed(
    session: AsyncSession, *, repo_full_name: str, pr_number: int, merged: bool
) -> int:
    """Webhook fast path: flip open records for (repo, number) to merged/closed.

    Attribution is by the repo's active links, so a record is only touched
    when its project is still linked to that repository. Returns rows changed.
    """
    linked_projects = (
        await session.execute(
            select(GatewayGitHubRepoLink.org_id, GatewayGitHubRepoLink.project_id).where(
                GatewayGitHubRepoLink.repo_full_name == repo_full_name,
                GatewayGitHubRepoLink.status == "active",
            )
        )
    ).all()
    if not linked_projects:
        return 0
    result = await session.execute(
        select(GatewayAgentPullRequest).where(
            GatewayAgentPullRequest.repo_full_name == repo_full_name,
            GatewayAgentPullRequest.pr_number == pr_number,
            GatewayAgentPullRequest.status == "open",
        )
    )
    changed = 0
    allowed = {(o, p) for o, p in linked_projects}
    for row in result.scalars().all():
        if (row.org_id, row.project_id) not in allowed:
            continue
        row.status = "merged" if merged else "closed"
        row.updated_at = time.time()
        changed += 1
    if changed:
        await session.commit()
    return changed


# Chat agent branch pushes (git server -> GitHub mirror).


async def _branch_row(
    session: AsyncSession, *, org_id: str, project_id: str, github_branch: str
) -> GatewayAgentPullRequest | None:
    result = await session.execute(
        select(GatewayAgentPullRequest).where(
            GatewayAgentPullRequest.org_id == org_id,
            GatewayAgentPullRequest.project_id == project_id,
            GatewayAgentPullRequest.github_branch == github_branch,
        )
    )
    return result.scalar_one_or_none()


async def record_branch_push(
    session: AsyncSession,
    *,
    org_id: str,
    project_id: str,
    conversation_id: str | None,
    repo_full_name: str,
    github_branch: str,
    base_branch: str,
    sha: str,
    actor: str,
    error_message: str | None = None,
) -> AgentPullRequestInfo:
    """Upsert the push record for ``github_branch`` on (org, project).

    A new row starts in status ``pushed`` with the branch name as its title.
    An existing row keeps its status and pull request fields; only the push
    fields move (``last_pushed_sha``, ``last_pushed_at``, ``updated_at``),
    plus ``conversation_id`` when it was never set. ``error_message`` is the
    outcome of the GitHub mirror for this push: None clears an older error.
    """
    now = time.time()
    row = await _branch_row(session, org_id=org_id, project_id=project_id, github_branch=github_branch)
    if row is None:
        row = GatewayAgentPullRequest(
            org_id=org_id,
            project_id=project_id,
            conversation_id=conversation_id,
            repo_full_name=repo_full_name,
            source_branch=github_branch,
            github_branch=github_branch,
            base_branch=base_branch,
            title=github_branch,
            status="pushed",
            created_by=actor,
            created_at=now,
            updated_at=now,
            draft=False,
        )
        session.add(row)
    elif row.conversation_id is None and conversation_id:
        row.conversation_id = conversation_id
    if not row.repo_full_name and repo_full_name:
        row.repo_full_name = repo_full_name
    row.last_pushed_sha = sha
    row.last_pushed_at = now
    row.updated_at = now
    row.error_message = error_message[:2000] if error_message else None
    await session.commit()
    return _to_info(row)


async def get_branch_record(
    session: AsyncSession, *, org_id: str, project_id: str, github_branch: str
) -> AgentPullRequestInfo | None:
    row = await _branch_row(session, org_id=org_id, project_id=project_id, github_branch=github_branch)
    return _to_info(row) if row else None


async def latest_branch_for_conversation(
    session: AsyncSession, *, org_id: str, project_id: str, conversation_id: str
) -> AgentPullRequestInfo | None:
    """The branch this conversation pushed most recently (by ``last_pushed_at``)."""
    result = await session.execute(
        select(GatewayAgentPullRequest)
        .where(
            GatewayAgentPullRequest.org_id == org_id,
            GatewayAgentPullRequest.project_id == project_id,
            GatewayAgentPullRequest.conversation_id == conversation_id,
            GatewayAgentPullRequest.last_pushed_at.isnot(None),
        )
        .order_by(GatewayAgentPullRequest.last_pushed_at.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    return _to_info(row) if row else None


async def list_open_prs_for_conversation(
    session: AsyncSession, *, org_id: str, project_id: str, conversation_id: str
) -> list[AgentPullRequestInfo]:
    result = await session.execute(
        select(GatewayAgentPullRequest)
        .where(
            GatewayAgentPullRequest.org_id == org_id,
            GatewayAgentPullRequest.project_id == project_id,
            GatewayAgentPullRequest.conversation_id == conversation_id,
            GatewayAgentPullRequest.status == "open",
        )
        .order_by(GatewayAgentPullRequest.updated_at.desc())
    )
    return [_to_info(r) for r in result.scalars().all()]
