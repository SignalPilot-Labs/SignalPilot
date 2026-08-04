"""Transactional chat-budget reservation and exact-query approval decisions."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import (
    GatewayChatConversation,
    GatewayChatRun,
    GatewayChatRunEvent,
    GatewayChatUserPreference,
    GatewayQueryApproval,
    GatewayQueryProposal,
)


@dataclass(frozen=True)
class ReservationDecision:
    proposal_id: str
    approved: bool
    remaining_chat_budget_usd: float


def _event(run: GatewayChatRun, event_type: str, payload: dict) -> GatewayChatRunEvent:
    run.last_event_sequence += 1
    return GatewayChatRunEvent(
        id=str(uuid.uuid4()),
        org_id=run.org_id,
        user_id=run.user_id,
        conversation_id=run.conversation_id,
        run_id=run.id,
        sequence=run.last_event_sequence,
        event_type=event_type,
        payload_json=payload,
    )


async def reserve_or_request_approval(
    db: AsyncSession,
    *,
    run_id: str,
    sql_hash: str,
    normalized_sql: str,
    connection_name: str,
    query_path: str,
    purpose: str,
    timeout_seconds: int,
    estimated_cost_usd: float,
    estimate_quality: str,
    estimate_json: dict,
    plan_id: str | None = None,
) -> ReservationDecision:
    """Atomically reserve estimated spend or pause the logical run."""
    run = (
        await db.execute(select(GatewayChatRun).where(GatewayChatRun.id == run_id).with_for_update())
    ).scalar_one_or_none()
    if run is None:
        raise LookupError("Standalone run not found")
    conversation = (
        await db.execute(
            select(GatewayChatConversation)
            .where(
                GatewayChatConversation.id == run.conversation_id,
                GatewayChatConversation.org_id == run.org_id,
                GatewayChatConversation.user_id == run.user_id,
            )
            .with_for_update()
        )
    ).scalar_one()
    existing = (
        await db.execute(
            select(GatewayQueryProposal).where(
                GatewayQueryProposal.run_id == run.id,
                GatewayQueryProposal.sql_hash == sql_hash,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        approved = existing.status in {"approved", "executing", "completed"}
        remaining = max(
            0.0,
            conversation.chat_budget_usd - conversation.actual_spend_usd - conversation.reserved_spend_usd,
        )
        return ReservationDecision(existing.id, approved, remaining)

    cost = max(0.0, estimated_cost_usd)
    remaining_before = max(
        0.0,
        conversation.chat_budget_usd - conversation.actual_spend_usd - conversation.reserved_spend_usd,
    )
    auto_approved = cost <= conversation.per_query_budget_usd and cost <= remaining_before
    proposal = GatewayQueryProposal(
        id=str(uuid.uuid4()),
        org_id=run.org_id,
        user_id=run.user_id,
        conversation_id=run.conversation_id,
        run_id=run.id,
        project_id=run.project_id,
        commit_sha=conversation.commit_sha or "0" * 40,
        connection_name=connection_name,
        plan_id=plan_id,
        query_path=query_path,
        purpose=purpose[:2_000],
        normalized_sql=normalized_sql,
        sql_hash=sql_hash,
        timeout_seconds=timeout_seconds,
        status="approved" if auto_approved else "waiting_for_approval",
        estimated_cost_usd=cost,
        estimate_quality=estimate_quality,
        estimate_json=estimate_json,
        reserved_cost_usd=cost if auto_approved else 0.0,
    )
    db.add(proposal)
    db.add(
        _event(
            run,
            "query_proposed",
            {
                "proposal_id": proposal.id,
                "purpose": proposal.purpose,
                "sql_hash": sql_hash,
                "query_path": query_path,
            },
        )
    )
    db.add(
        _event(
            run,
            "query_estimated",
            {
                "proposal_id": proposal.id,
                "purpose": proposal.purpose,
                "sql_hash": sql_hash,
                "estimated_cost_usd": cost,
                "estimate_quality": estimate_quality,
            },
        )
    )
    if auto_approved:
        conversation.reserved_spend_usd += cost
        conversation.estimated_spend_usd += cost
    else:
        run.status = "waiting_for_query_approval"
        run.lease_owner = None
        run.lease_expires_at = None
        db.add(
            _event(
                run,
                "query_approval_requested",
                {
                    "proposal_id": proposal.id,
                    "purpose": proposal.purpose,
                    "sql_hash": sql_hash,
                    "estimated_cost_usd": cost,
                    "remaining_chat_budget_usd": remaining_before,
                    "estimate_quality": estimate_quality,
                },
            )
        )
    conversation.updated_at = time.time()
    await db.commit()
    return ReservationDecision(
        proposal.id,
        auto_approved,
        max(0.0, remaining_before - cost if auto_approved else remaining_before),
    )


async def reconcile_reservation(
    db: AsyncSession,
    *,
    proposal_id: str,
    actual_cost_usd: float | None,
    completed: bool,
) -> None:
    proposal = (
        await db.execute(select(GatewayQueryProposal).where(GatewayQueryProposal.id == proposal_id).with_for_update())
    ).scalar_one()
    conversation = (
        await db.execute(
            select(GatewayChatConversation)
            .where(GatewayChatConversation.id == proposal.conversation_id)
            .with_for_update()
        )
    ).scalar_one()
    conversation.reserved_spend_usd = max(0.0, conversation.reserved_spend_usd - proposal.reserved_cost_usd)
    if completed:
        charged = max(0.0, actual_cost_usd if actual_cost_usd is not None else proposal.estimated_cost_usd)
        conversation.actual_spend_usd += charged
        proposal.status = "completed"
    else:
        proposal.status = "failed"
    proposal.reserved_cost_usd = 0.0
    proposal.terminal_at = datetime.now(UTC)
    await db.commit()


async def decide_query_proposal(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    proposal_id: str,
    decision: str,
    approval_scope: str,
    per_query_budget_usd: float | None,
    chat_budget_usd: float | None,
) -> GatewayChatRun | None:
    proposal = (
        await db.execute(
            select(GatewayQueryProposal)
            .where(
                GatewayQueryProposal.id == proposal_id,
                GatewayQueryProposal.org_id == org_id,
                GatewayQueryProposal.user_id == user_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if proposal is None:
        return None
    existing = (
        await db.execute(
            select(GatewayQueryApproval).where(
                GatewayQueryApproval.proposal_id == proposal.id,
                GatewayQueryApproval.approver_user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    run = (
        await db.execute(select(GatewayChatRun).where(GatewayChatRun.id == proposal.run_id).with_for_update())
    ).scalar_one()
    if existing is not None:
        return run
    if proposal.status != "waiting_for_approval" or run.status != "waiting_for_query_approval":
        raise RuntimeError("This query is no longer waiting for approval")
    conversation = (
        await db.execute(
            select(GatewayChatConversation)
            .where(GatewayChatConversation.id == proposal.conversation_id)
            .with_for_update()
        )
    ).scalar_one()
    approved = decision == "approve"
    if approved and approval_scope in {"current_chat", "user_defaults"}:
        if per_query_budget_usd is None or chat_budget_usd is None:
            raise ValueError("Updated budgets are required for this approval scope")
        if per_query_budget_usd < 0 or chat_budget_usd < per_query_budget_usd:
            raise ValueError("Chat budget must be at least the non-negative per-query budget")
        conversation.per_query_budget_usd = per_query_budget_usd
        conversation.chat_budget_usd = chat_budget_usd
        if approval_scope == "user_defaults":
            preference = (
                await db.execute(
                    select(GatewayChatUserPreference)
                    .where(
                        GatewayChatUserPreference.org_id == org_id,
                        GatewayChatUserPreference.user_id == user_id,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if preference is None:
                preference = GatewayChatUserPreference(
                    org_id=org_id,
                    user_id=user_id,
                    default_per_query_budget_usd=per_query_budget_usd,
                    default_chat_budget_usd=chat_budget_usd,
                )
                db.add(preference)
            else:
                preference.default_per_query_budget_usd = per_query_budget_usd
                preference.default_chat_budget_usd = chat_budget_usd

    approval = GatewayQueryApproval(
        id=str(uuid.uuid4()),
        proposal_id=proposal.id,
        org_id=org_id,
        approver_user_id=user_id,
        approval_scope=approval_scope,
        decision="approved" if approved else "declined",
        sql_hash=proposal.sql_hash,
        approved_estimated_cost_usd=proposal.estimated_cost_usd,
        per_query_budget_usd=per_query_budget_usd,
        chat_budget_usd=chat_budget_usd,
        policy_version=proposal.policy_version,
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )
    db.add(approval)
    if approved:
        conversation.reserved_spend_usd += proposal.estimated_cost_usd
        conversation.estimated_spend_usd += proposal.estimated_cost_usd
        proposal.reserved_cost_usd = proposal.estimated_cost_usd
        proposal.status = "approved"
    else:
        proposal.status = "declined"
        proposal.terminal_at = datetime.now(UTC)
    run.status = "queued"
    run.lease_owner = None
    run.lease_expires_at = None
    db.add(
        _event(
            run,
            "query_approved" if approved else "query_declined",
            {"proposal_id": proposal.id, "sql_hash": proposal.sql_hash, "scope": approval_scope},
        )
    )
    await db.commit()
    return run
