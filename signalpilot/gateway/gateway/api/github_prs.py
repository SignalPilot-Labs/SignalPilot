"""Agent pull request endpoints (split from api/github.py).

Mounted by ``api/github.py`` via ``router.include_router``.

- POST  /api/github/pull-requests: open a PR for a branch the agent pushed.
- GET   /api/github/pull-requests?project_id=: list the org's agent PRs.
- PATCH /api/github/pull-requests/{id}: edit the PR title or body.
- POST  /api/github/pull-requests/{id}/comments: comment on the PR.
"""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import APIRouter, HTTPException, Query

from ..models.audit import AuditEntry
from ..models.github import (
    AgentPullRequestCommentCreate,
    AgentPullRequestCommentInfo,
    AgentPullRequestCreate,
    AgentPullRequestInfo,
    AgentPullRequestUpdate,
)
from ..security.scope_guard import RequireScope
from .deps import StoreD

logger = logging.getLogger(__name__)

router = APIRouter()


async def _audit(store, event_type: str, metadata: dict) -> None:
    try:
        await store.append_audit(
            AuditEntry(id=str(uuid.uuid4()), timestamp=time.time(), event_type=event_type, metadata=metadata)
        )
    except Exception:
        logger.warning("Failed to append audit log for %s project=%s", event_type, metadata.get("project_id"))


async def _record_or_404(store, record_id: str) -> AgentPullRequestInfo:
    from ..git.agent_pr import get_record

    record = await get_record(store.session, org_id=store.org_id or "local", record_id=record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Pull request record not found")
    return record


@router.post(
    "/api/github/pull-requests",
    status_code=201,
    response_model=AgentPullRequestInfo,
    dependencies=[RequireScope("write")],
)
async def create_pull_request(body: AgentPullRequestCreate, store: StoreD):
    from ..git.agent_pr import AgentPrError, open_pull_request

    org_id = store.org_id or "local"
    project = await store.get_workspace_project(body.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        record = await open_pull_request(
            store.session,
            org_id=org_id,
            project_id=body.project_id,
            conversation_id=body.conversation_id,
            title=body.title,
            body=body.body,
            draft=body.draft,
            github_branch=body.github_branch,
            base_branch=body.base_branch,
            actor=store.user_id or "local",
        )
    except AgentPrError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await _audit(
        store,
        "github_pr_create",
        {
            "project_id": body.project_id,
            "repo": record.repo_full_name,
            "source_branch": record.source_branch,
            "github_branch": record.github_branch,
            "base_branch": record.base_branch,
            "pr_number": record.pr_number,
            "status": record.status,
            "draft": record.draft,
            "conversation_id": record.conversation_id,
        },
    )
    return record


@router.get(
    "/api/github/pull-requests",
    response_model=list[AgentPullRequestInfo],
    dependencies=[RequireScope("read")],
)
async def list_pull_requests(store: StoreD, project_id: str | None = Query(None)):
    from ..store import github_prs

    return await github_prs.list_pull_requests(
        store.session, org_id=store.org_id or "local", project_id=project_id
    )


@router.patch(
    "/api/github/pull-requests/{record_id}",
    response_model=AgentPullRequestInfo,
    dependencies=[RequireScope("write")],
)
async def update_pull_request(record_id: str, body: AgentPullRequestUpdate, store: StoreD):
    from ..git.agent_pr import AgentPrError
    from ..git.agent_pr import update_pull_request as _update

    target = await _record_or_404(store, record_id)
    if not target.pr_number:
        raise HTTPException(status_code=400, detail="This branch has no pull request yet")
    try:
        record = await _update(
            store.session,
            org_id=store.org_id or "local",
            project_id=target.project_id,
            conversation_id=target.conversation_id,
            pr_number=target.pr_number,
            title=body.title,
            body=body.body,
            actor=store.user_id or "local",
        )
    except AgentPrError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await _audit(
        store,
        "github_pr_update",
        {
            "project_id": record.project_id,
            "repo": record.repo_full_name,
            "github_branch": record.github_branch,
            "pr_number": record.pr_number,
            "title_changed": body.title is not None,
            "body_changed": body.body is not None,
        },
    )
    return record


@router.post(
    "/api/github/pull-requests/{record_id}/comments",
    status_code=201,
    response_model=AgentPullRequestCommentInfo,
    dependencies=[RequireScope("write")],
)
async def comment_on_pull_request(record_id: str, body: AgentPullRequestCommentCreate, store: StoreD):
    from ..git.agent_pr import AgentPrError
    from ..git.agent_pr import comment_on_pull_request as _comment

    target = await _record_or_404(store, record_id)
    if not target.pr_number:
        raise HTTPException(status_code=400, detail="This branch has no pull request yet")
    try:
        result = await _comment(
            store.session,
            org_id=store.org_id or "local",
            project_id=target.project_id,
            conversation_id=target.conversation_id,
            body=body.body,
            pr_number=target.pr_number,
            actor=store.user_id or "local",
        )
    except AgentPrError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await _audit(
        store,
        "github_pr_comment",
        {
            "project_id": target.project_id,
            "repo": target.repo_full_name,
            "github_branch": target.github_branch,
            "pr_number": target.pr_number,
            "comment_url": result.get("comment_url"),
        },
    )
    return AgentPullRequestCommentInfo(**result)
