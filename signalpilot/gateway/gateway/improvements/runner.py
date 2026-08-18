"""Improvement-run seeding.

Creates the origin="improvement" standalone-chat conversation and its first
queued run. The existing chat worker picks the run up like any other; the
improvement origin then flows through `prepare_execution` (sandbox:execute
capability, run_origin payload flag, dedicated billing key) and the
notebook-server (sandbox tools + improvement instructions).
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import GatewayUserSession, GatewayWorkspaceProject
from gateway.git.repos import branch_head_sha
from gateway.standalone_chat.projects import evaluate_project_readiness
from gateway.store.standalone_chat import create_conversation_with_run

IMPROVEMENT_CHAT_BUDGET_USD = 2.0
IMPROVEMENT_PER_QUERY_BUDGET_USD = 0.25

_IMPROVEMENT_MESSAGE = (
    "Run the scheduled cost-optimization analysis for this project. Analyze "
    "the dbt models for warehouse cost-saving opportunities using the query "
    "cost estimator, rank the findings by estimated savings, and publish the "
    "\"Cost optimization report\" HTML artifact with your recommendations."
)


async def _owner_user_id(db: AsyncSession, org_id: str) -> str:
    """Attribute the automated conversation to the org's most recent user.

    There is no membership table in the gateway (identity lives in Clerk in
    cloud mode), so the best available owner is the most recently active
    session user; local single-user deployments fall back to "local".
    """
    row = (
        await db.execute(
            select(GatewayUserSession.user_id)
            .where(GatewayUserSession.org_id == org_id)
            .order_by(GatewayUserSession.updated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return str(row) if row else "local"


async def seed_improvement_run(
    db: AsyncSession,
    *,
    org_id: str,
    project: GatewayWorkspaceProject,
    trigger: str = "scheduled",
) -> tuple[str, str]:
    """Create the improvement conversation and queued run for one org.

    Raises on failure; the scheduler records the failure on the
    GatewayImprovementRun row and moves on to the next org.
    """
    user_id = await _owner_user_id(db, org_id)
    readiness = await evaluate_project_readiness(
        db,
        org_id=org_id,
        user_id=user_id,
        project=project,
    )
    if not readiness.ready or not readiness.branch:
        raise RuntimeError(
            f"Project {project.id} is not chat-ready ({readiness.code}): {readiness.message}"
        )
    commit_sha = branch_head_sha(project.id, readiness.branch)
    if not commit_sha or len(commit_sha) != 40:
        raise RuntimeError(f"Project {project.id} has no resolvable head commit on {readiness.branch}")
    conversation, run = await create_conversation_with_run(
        db,
        org_id=org_id,
        user_id=user_id,
        project=project,
        branch=readiness.branch,
        message=_IMPROVEMENT_MESSAGE,
        commit_sha=commit_sha,
        per_query_budget_usd=IMPROVEMENT_PER_QUERY_BUDGET_USD,
        chat_budget_usd=IMPROVEMENT_CHAT_BUDGET_USD,
        origin="improvement",
    )
    # Title the conversation for the chats list; created with a placeholder
    # by create_conversation_with_run.
    et_day = datetime.now(UTC).date().isoformat()
    conversation.title = f"Cost optimization — {et_day} ({trigger})"
    conversation.updated_at = time.time()
    await db.commit()
    return conversation.id, run.id
