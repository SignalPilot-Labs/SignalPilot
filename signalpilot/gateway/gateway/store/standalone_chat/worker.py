"""Worker claim, lease, context, and usage accounting operations."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import (
    GatewayChatConversation,
    GatewayChatMessage,
    GatewayChatRun,
    GatewayDashboardAuthoringSession,
    GatewayGovernedQueryExecution,
    GatewayQueryApproval,
    GatewayQueryProposal,
    GatewayStructuredQueryResult,
    GatewayWorkspaceProject,
)
from gateway.standalone_chat import config as chat_config
from gateway.standalone_chat.domain import RunStatus, assert_run_transition
from gateway.store.standalone_chat.helpers import (
    _append_status_message,
    _now,
    _retain_runtime_datasets_after_terminal_run,
    _stage_run_event,
)


async def claim_runs(
    db: AsyncSession,
    *,
    worker_id: str,
    limit: int,
    lease_seconds: int,
) -> list[str]:
    now = _now()
    query = select(GatewayChatRun).where(
        or_(
            GatewayChatRun.status == RunStatus.queued.value,
            and_(
                GatewayChatRun.status == RunStatus.running.value,
                GatewayChatRun.lease_expires_at < now,
            ),
        )
    )
    # Environment affinity: a labeled worker claims only its own runs plus
    # unlabeled (NULL) rows; an unlabeled worker claims everything.
    own_env = chat_config.runtime_env()
    if own_env is not None:
        query = query.where(
            or_(GatewayChatRun.runtime_env == own_env, GatewayChatRun.runtime_env.is_(None))
        )
    candidates = (
        (
            await db.execute(
                query.order_by(GatewayChatRun.created_at)
                .with_for_update(skip_locked=True)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    claimed: list[str] = []
    for run in candidates:
        if run.cancellation_requested_at:
            assert_run_transition(run.status, RunStatus.cancelled.value)
            run.status = RunStatus.cancelled.value
            run.terminal_at = now
            run.lease_owner = None
            run.lease_expires_at = None
            await _append_status_message(
                db,
                run=run,
                status=RunStatus.cancelled.value,
                content="This run was stopped.",
            )
            _stage_run_event(
                db,
                run=run,
                event_type="status",
                payload={"status": RunStatus.cancelled.value},
            )
            await _retain_runtime_datasets_after_terminal_run(db, run=run)
            continue
        if run.status == RunStatus.queued.value:
            assert_run_transition(run.status, RunStatus.running.value)
        run.status = RunStatus.running.value
        run.started_at = run.started_at or now
        run.execution_attempt += 1
        run.lease_owner = worker_id
        run.lease_expires_at = now + timedelta(seconds=lease_seconds)
        claimed.append(run.id)
    await db.commit()
    return claimed


async def renew_lease(
    db: AsyncSession,
    *,
    run_id: str,
    worker_id: str,
    lease_seconds: int,
) -> bool:
    run = (
        await db.execute(
            select(GatewayChatRun).where(
                GatewayChatRun.id == run_id,
                GatewayChatRun.status == RunStatus.running.value,
                GatewayChatRun.lease_owner == worker_id,
            )
        )
    ).scalar_one_or_none()
    if run is None:
        return False
    run.lease_expires_at = _now() + timedelta(seconds=lease_seconds)
    await db.commit()
    return True


async def get_worker_run(db: AsyncSession, *, run_id: str, worker_id: str) -> GatewayChatRun | None:
    return (
        await db.execute(
            select(GatewayChatRun).where(
                GatewayChatRun.id == run_id,
                GatewayChatRun.status == RunStatus.running.value,
                GatewayChatRun.lease_owner == worker_id,
            )
        )
    ).scalar_one_or_none()


async def worker_context(db: AsyncSession, *, run: GatewayChatRun) -> dict[str, Any]:
    conversation = (
        await db.execute(
            select(GatewayChatConversation).where(
                GatewayChatConversation.id == run.conversation_id,
                GatewayChatConversation.org_id == run.org_id,
                GatewayChatConversation.user_id == run.user_id,
                GatewayChatConversation.surface == "standalone",
            )
        )
    ).scalar_one()
    project = (
        await db.execute(
            select(GatewayWorkspaceProject).where(
                GatewayWorkspaceProject.id == run.project_id,
                GatewayWorkspaceProject.org_id == run.org_id,
            )
        )
    ).scalar_one()
    messages = (
        (
            await db.execute(
                select(GatewayChatMessage)
                .where(GatewayChatMessage.conversation_id == run.conversation_id)
                .order_by(GatewayChatMessage.sequence)
            )
        )
        .scalars()
        .all()
    )
    proposals = list(
        (
            await db.execute(
                select(GatewayQueryProposal)
                .where(GatewayQueryProposal.conversation_id == run.conversation_id)
                .order_by(GatewayQueryProposal.created_at)
            )
        ).scalars()
    )
    proposal_ids = [proposal.id for proposal in proposals]
    approvals = (
        list(
            (
                await db.execute(
                    select(GatewayQueryApproval)
                    .where(GatewayQueryApproval.proposal_id.in_(proposal_ids))
                    .order_by(GatewayQueryApproval.created_at)
                )
            ).scalars()
        )
        if proposal_ids
        else []
    )
    executions = list(
        (
            await db.execute(
                select(GatewayGovernedQueryExecution)
                .where(GatewayGovernedQueryExecution.conversation_id == run.conversation_id)
                .order_by(GatewayGovernedQueryExecution.created_at)
            )
        ).scalars()
    )
    results = list(
        (
            await db.execute(
                select(GatewayStructuredQueryResult)
                .where(
                    GatewayStructuredQueryResult.org_id == run.org_id,
                    GatewayStructuredQueryResult.owner_user_id == run.user_id,
                    GatewayStructuredQueryResult.conversation_id == run.conversation_id,
                )
                .order_by(GatewayStructuredQueryResult.created_at)
            )
        ).scalars()
    )
    dashboard_authoring_session = (
        await db.execute(
            select(GatewayDashboardAuthoringSession)
            .where(
                GatewayDashboardAuthoringSession.org_id == run.org_id,
                GatewayDashboardAuthoringSession.owner_user_id == run.user_id,
                GatewayDashboardAuthoringSession.conversation_id == run.conversation_id,
            )
            .order_by(GatewayDashboardAuthoringSession.updated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return {
        "conversation": conversation,
        "project": project,
        "messages": messages,
        "query_proposals": proposals,
        "query_approvals": approvals,
        "query_executions": executions,
        "query_results": results,
        "dashboard_authoring_session": dashboard_authoring_session,
    }


async def set_execution_session(
    db: AsyncSession,
    *,
    run_id: str,
    worker_id: str,
    execution_session_id: str,
) -> bool:
    run = (
        await db.execute(
            select(GatewayChatRun).where(
                GatewayChatRun.id == run_id,
                GatewayChatRun.lease_owner == worker_id,
            )
        )
    ).scalar_one_or_none()
    if run is None:
        return False
    run.execution_session_id = execution_session_id
    await db.commit()
    return True


async def record_run_usage(
    db: AsyncSession,
    *,
    run_id: str,
    worker_id: str,
    cost_usd: float | None,
    usage: dict[str, Any] | None,
) -> bool:
    """Persist the agent's reported cost and token usage on the run row.

    Operator accounting only (never surfaced in the chat UX). Written as soon
    as the runtime reports it, so the numbers survive even when the run later
    fails validation or cancels."""
    if cost_usd is None and not usage:
        return False
    run = (
        await db.execute(
            select(GatewayChatRun).where(
                GatewayChatRun.id == run_id,
                GatewayChatRun.lease_owner == worker_id,
            )
        )
    ).scalar_one_or_none()
    if run is None:
        return False
    if cost_usd is not None:
        run.cost_usd = float(cost_usd)
    if usage:
        run.usage_json = usage
    await db.commit()
    return True
