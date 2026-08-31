"""Query approval, run lifecycle, and event-stream routes."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from gateway.auth import OrgRole
from gateway.db.engine import get_session_factory
from gateway.db.models import (
    GatewayChatConversation,
    GatewayChatRun,
    GatewayGovernedQueryExecution,
)
from gateway.governance.query_executor import governed_query_executor
from gateway.models.standalone_chat import (
    ChatRunInfo,
    QueryApprovalDecision,
    StandaloneClarificationCreate,
    StandaloneMessageInfo,
    StandaloneRunCreate,
    StandaloneSteeringCreate,
)
from gateway.security.scope_guard import RequireScope
from gateway.standalone_chat.query_approvals import decide_query_proposal
from gateway.store import standalone_chat as chat_store

from ..deps import StoreD
from .common import is_admin as _is_admin
from .common import readiness_or_error as _readiness_or_error
from .common import require_enabled as _require_enabled
from .common import require_enterprise_feature as _require_enterprise_feature
from .common import unready_detail as _unready_detail

router = APIRouter()


@router.post(
    "/query-proposals/{proposal_id}/decision",
    response_model=ChatRunInfo,
    dependencies=[RequireScope("write")],
)
async def decide_query(
    proposal_id: str,
    body: QueryApprovalDecision,
    store: StoreD,
):
    _require_enabled()
    _require_enterprise_feature("query_approval")
    try:
        run = await decide_query_proposal(
            store.session,
            org_id=store._require_org_id(),
            user_id=store.user_id or "local",
            proposal_id=proposal_id,
            decision=body.decision,
            approval_scope=body.scope,
            per_query_budget_usd=body.per_query_budget_usd,
            chat_budget_usd=body.chat_budget_usd,
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if run is None:
        raise HTTPException(status_code=404, detail="Query proposal not found")
    return chat_store._run_info(run)


@router.post(
    "/conversations/{conversation_id}/runs",
    status_code=201,
    response_model=ChatRunInfo,
    dependencies=[RequireScope("write")],
)
async def create_run(
    conversation_id: str,
    body: StandaloneRunCreate,
    store: StoreD,
    role: OrgRole,
):
    _require_enabled()
    conversation = (
        await store.session.execute(
            select(GatewayChatConversation).where(
                GatewayChatConversation.id == conversation_id,
                GatewayChatConversation.org_id == store._require_org_id(),
                GatewayChatConversation.user_id == (store.user_id or "local"),
                GatewayChatConversation.surface == "standalone",
                GatewayChatConversation.status == "active",
            )
        )
    ).scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    _, readiness = await _readiness_or_error(
        store,
        conversation.project_id or "",
        branch_override=conversation.branch,
    )
    if not readiness.ready:
        raise HTTPException(
            status_code=409,
            detail=_unready_detail(readiness, admin=_is_admin(role)),
        )
    report_reference = None
    if body.report_reference is not None:
        from gateway.store.chat_reports import verified_report_reference

        report_reference = await verified_report_reference(
            store.session,
            org_id=store._require_org_id(),
            user_id=store.user_id or "local",
            conversation_id=conversation_id,
            report_id=body.report_reference.report_id,
            version_id=body.report_reference.version_id,
        )
        if report_reference is None:
            raise HTTPException(status_code=404, detail="Report reference not found")
    try:
        run = await chat_store.create_run(
            store.session,
            org_id=store._require_org_id(),
            user_id=store.user_id or "local",
            conversation_id=conversation_id,
            message=body.message,
            message_metadata={"report_reference": report_reference} if report_reference else None,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Conversation not found") from exc
    return chat_store._run_info(run)


@router.get("/runs/{run_id}/events", dependencies=[RequireScope("read")])
async def stream_run_events(
    run_id: str,
    store: StoreD,
    after: Annotated[int, Query(ge=0)] = 0,
):
    _require_enabled()
    initial = await chat_store.list_run_events(
        store.session,
        org_id=store._require_org_id(),
        user_id=store.user_id or "local",
        run_id=run_id,
        after=after,
    )
    if initial is None:
        raise HTTPException(status_code=404, detail="Run not found")
    org_id = store._require_org_id()
    user_id = store.user_id or "local"

    async def generate():
        cursor = after
        keepalive_ticks = 0
        while True:
            factory = get_session_factory()
            async with factory() as session:
                events = await chat_store.list_run_events(
                    session,
                    org_id=org_id,
                    user_id=user_id,
                    run_id=run_id,
                    after=cursor,
                )
                if events is None:
                    return
                for event in events:
                    cursor = event.sequence
                    payload = json.dumps(event.model_dump(mode="json"), separators=(",", ":"))
                    yield f"id: {event.sequence}\nevent: {event.type}\ndata: {payload}\n\n"
                run_status = (
                    await session.execute(
                        select(GatewayChatRun.status).where(
                            GatewayChatRun.id == run_id,
                            GatewayChatRun.org_id == org_id,
                            GatewayChatRun.user_id == user_id,
                        )
                    )
                ).scalar_one_or_none()
            if (
                run_status
                in {
                    "completed",
                    "failed",
                    "cancelled",
                    "waiting_for_user",
                    "waiting_for_query_approval",
                }
                and not events
            ):
                return
            keepalive_ticks += 1
            if keepalive_ticks >= 15:
                keepalive_ticks = 0
                yield ": keepalive\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/runs/{run_id}/cancel", response_model=ChatRunInfo, dependencies=[RequireScope("write")])
async def cancel_run(run_id: str, store: StoreD):
    _require_enabled()
    run = await chat_store.request_cancellation(
        store.session,
        org_id=store._require_org_id(),
        user_id=store.user_id or "local",
        run_id=run_id,
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.execution_session_id and run.status == "running":
        try:
            from gateway.standalone_chat.execution import cancel_execution_session

            await cancel_execution_session(store.session, run)
        except Exception:
            pass
    active_queries = list(
        (
            await store.session.execute(
                select(GatewayGovernedQueryExecution).where(
                    GatewayGovernedQueryExecution.org_id == store._require_org_id(),
                    GatewayGovernedQueryExecution.user_id == (store.user_id or "local"),
                    GatewayGovernedQueryExecution.run_id == run.id,
                    GatewayGovernedQueryExecution.status.in_(("estimating", "running")),
                )
            )
        ).scalars()
    )
    for execution in active_queries:
        execution.status = "cancelled"
        execution.public_error_code = "query_cancelled"
        execution.terminal_at = datetime.now(UTC)
    if active_queries:
        await store.session.commit()
    for execution in active_queries:
        await governed_query_executor.cancel(execution.id)
        try:
            from gateway.governance.runtime_datasets import runtime_dataset_executor

            await runtime_dataset_executor.cancel(execution.id)
        except Exception:
            pass
    return chat_store._run_info(run)


@router.post(
    "/runs/{run_id}/steer",
    status_code=202,
    response_model=StandaloneMessageInfo,
    dependencies=[RequireScope("write")],
)
async def steer_run(run_id: str, body: StandaloneSteeringCreate, store: StoreD):
    _require_enabled()
    try:
        message = await chat_store.queue_steering_message(
            store.session,
            org_id=store._require_org_id(),
            user_id=store.user_id or "local",
            run_id=run_id,
            message=body.message,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if message is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return chat_store._message_info(message)


@router.post(
    "/runs/{run_id}/clarification",
    response_model=ChatRunInfo,
    dependencies=[RequireScope("write")],
)
async def clarify_run(run_id: str, body: StandaloneClarificationCreate, store: StoreD):
    _require_enabled()
    try:
        run = await chat_store.submit_clarification(
            store.session,
            org_id=store._require_org_id(),
            user_id=store.user_id or "local",
            run_id=run_id,
            message=body.message,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return chat_store._run_info(run)


@router.post(
    "/runs/{run_id}/retry",
    status_code=201,
    response_model=ChatRunInfo,
    dependencies=[RequireScope("write")],
)
async def retry_run(run_id: str, store: StoreD, role: OrgRole):
    _require_enabled()
    failed = (
        await store.session.execute(
            select(GatewayChatRun)
            .join(
                GatewayChatConversation,
                GatewayChatConversation.id == GatewayChatRun.conversation_id,
            )
            .where(
                GatewayChatRun.id == run_id,
                GatewayChatRun.org_id == store._require_org_id(),
                GatewayChatRun.user_id == (store.user_id or "local"),
                GatewayChatConversation.surface == "standalone",
                GatewayChatConversation.status == "active",
            )
        )
    ).scalar_one_or_none()
    if failed is None:
        raise HTTPException(status_code=404, detail="Run not found")
    conversation_branch = await store.session.scalar(
        select(GatewayChatConversation.branch).where(
            GatewayChatConversation.id == failed.conversation_id,
            GatewayChatConversation.org_id == store._require_org_id(),
            GatewayChatConversation.user_id == (store.user_id or "local"),
            GatewayChatConversation.surface == "standalone",
            GatewayChatConversation.status == "active",
        )
    )
    _, readiness = await _readiness_or_error(
        store,
        failed.project_id,
        branch_override=conversation_branch,
    )
    if not readiness.ready:
        raise HTTPException(
            status_code=409,
            detail=_unready_detail(readiness, admin=_is_admin(role)),
        )
    try:
        run = await chat_store.retry_run(
            store.session,
            org_id=store._require_org_id(),
            user_id=store.user_id or "local",
            run_id=run_id,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return chat_store._run_info(run)
