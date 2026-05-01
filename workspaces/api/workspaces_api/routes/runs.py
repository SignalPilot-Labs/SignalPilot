"""Run and approval routes for the Workspaces API.

Route summary:
  POST   /v1/runs                      Submit a new run
  GET    /v1/runs                      List runs (keyset paginated)
  GET    /v1/runs/{run_id}             Fetch run state
  GET    /v1/runs/{run_id}/events      SSE stream of run events
  POST   /v1/runs/{run_id}/approve     Approve a pending approval gate
  POST   /v1/runs/{run_id}/reject      Reject a pending approval gate

SSE ordering (load-bearing — do not reorder):
  1. Existence check fires BEFORE EventSourceResponse is constructed.
     sse-starlette swallows exceptions raised inside the generator after
     headers have flushed, so the 404 MUST be raised in the route function
     body before returning EventSourceResponse.
  2. Ownership check (cloud mode) fires at the same point as the existence check.
  3. Persisted events are snapshotted while the DB session is still open.
  4. Live bus events are drained until stream_end or a run-terminal event.

If this file grows past ~250 lines, split SSE into routes/runs_events.py.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import secrets
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sse_starlette.sse import EventSourceResponse

from workspaces_api.agent.inference import resolve_inference_source
from workspaces_api.agent.resume_marker import write_approval_marker
from workspaces_api.agent.spawner import SpawnRequest, Spawner
from workspaces_api.auth.dependency import CurrentUserId
from workspaces_api.config import Settings, get_settings
from workspaces_api.errors import ProxyTokenMintFailed, SpawnFailed
from workspaces_api.events.bus import EventBus
from workspaces_api.models import Approval, Run, RunEvent
from workspaces_api.schemas import (
    ApprovalDecisionRequest,
    ApprovalResponse,
    RunCreateRequest,
    RunEventOut,
    RunListResponse,
    RunResponse,
)
from workspaces_api.states import RunState, transition

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/runs")

_TERMINAL_STATES = {RunState.succeeded, RunState.failed, RunState.cancelled}

# Map wire verbs (route names) to past-tense decision vocabulary.
# DB column Approval.decision and on-disk resume markers use past tense.
_DECISION_MAP: dict[str, Literal["approved", "rejected"]] = {
    "approve": "approved",
    "reject": "rejected",
}


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _run_to_response(run: Run) -> RunResponse:
    return RunResponse.model_validate(run)


def _event_to_out(ev: RunEvent) -> RunEventOut:
    return RunEventOut.model_validate(ev)


def _sse_frame(event: RunEventOut) -> dict:
    return {"event": event.kind, "data": event.model_dump_json()}


async def _load_run_events(session: AsyncSession, run_id: uuid.UUID) -> list[RunEvent]:
    result = await session.execute(
        select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.id)
    )
    return list(result.scalars().all())


async def _insert_run_event(
    session: AsyncSession,
    run_id: uuid.UUID,
    kind: str,
    payload: dict | None = None,
) -> RunEvent:
    ev = RunEvent(run_id=run_id, kind=kind, payload=payload or {})
    session.add(ev)
    await session.flush()
    await session.refresh(ev)
    return ev


def _get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.session_factory


def _get_spawner(request: Request) -> Spawner:
    return request.app.state.spawner


def _get_bus(request: Request) -> EventBus:
    return request.app.state.bus


# ─── Cursor helpers ───────────────────────────────────────────────────────────


def _encode_run_cursor(created_at_iso: str, run_id: str) -> str:
    raw = json.dumps([created_at_iso, run_id], separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_run_cursor(cursor: str) -> tuple[str, str]:
    padded = cursor + "=" * (-len(cursor) % 4)
    raw = base64.urlsafe_b64decode(padded).decode()
    created_at_iso, run_id = json.loads(raw)
    return created_at_iso, run_id


# ─── Routes ───────────────────────────────────────────────────────────────────


@router.post("", status_code=201, response_model=RunResponse)
async def submit_run(
    body: RunCreateRequest,
    user_id: CurrentUserId,
    settings: Settings = Depends(get_settings),
    session_factory: async_sessionmaker[AsyncSession] = Depends(_get_session_factory),
    spawner: Spawner = Depends(_get_spawner),
    bus: EventBus = Depends(_get_bus),
) -> RunResponse:
    """Submit a new workspace run.

    Raises 422 (inference_not_configured) if no inference source is available.
    Raises 501 (metered_not_implemented) if metered inference is requested.
    No DB row is inserted if inference resolution fails.
    """
    bundle = resolve_inference_source(settings, requested=body.requested_inference)

    async with session_factory() as session:
        run = Run(
            id=uuid.uuid4(),
            workspace_id=body.workspace_id,
            prompt=body.prompt,
            state=RunState.queued.value,
            inference_mode=bundle.mode,
            dbt_proxy_host_port=body.dbt_proxy_host_port,
            user_id=user_id,
            created_at=_now_utc(),
            updated_at=_now_utc(),
        )
        session.add(run)
        await session.flush()

        spawn_req = SpawnRequest(
            run_id=run.id,
            workspace_id=body.workspace_id,
            prompt=body.prompt,
            inference=bundle,
            gateway_run_token=None,
            dbt_proxy_host_port=body.dbt_proxy_host_port,
            connector_name=body.connector_name,
            sandbox_internal_secret=secrets.token_hex(32),
        )

        try:
            await spawner.spawn(spawn_req)
        except (SpawnFailed, ProxyTokenMintFailed) as exc:
            # Mark run failed, emit run.failed event, then re-raise
            run.state = RunState.failed.value
            run.updated_at = _now_utc()
            run.finished_at = _now_utc()
            try:
                ev = await _insert_run_event(
                    session,
                    run.id,
                    "run.failed",
                    payload={
                        "error_code": exc.error_code,
                        "correlation_id": exc.correlation_id,
                    },
                )
                await session.commit()
                await bus.publish(run.id, _event_to_out(ev))
            except Exception as emit_exc:
                logger.error(
                    "run.failed event emit error run_id=%s: %r", run.id, emit_exc
                )
            raise

        transition(RunState(run.state), RunState.running)
        run.state = RunState.running.value
        run.updated_at = _now_utc()

        ev = await _insert_run_event(session, run.id, "run.started")
        await session.commit()
        await session.refresh(run)

    await bus.publish(run.id, _event_to_out(ev))
    logger.info("run_started run_id=%s mode=%s", run.id, bundle.mode)
    return _run_to_response(run)


@router.get("", response_model=RunListResponse)
async def list_runs(
    user_id: CurrentUserId,
    settings: Settings = Depends(get_settings),
    session_factory: async_sessionmaker[AsyncSession] = Depends(_get_session_factory),
    workspace_id: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None),
) -> RunListResponse:
    """List runs for a workspace, paginated by created_at DESC.

    In cloud mode, only runs owned by the authenticated user are returned.
    NULL user_id rows (legacy local-mode rows) are invisible to cloud callers.
    In local mode, all runs for the workspace are returned.
    """
    async with session_factory() as session:
        q = (
            select(Run)
            .where(Run.workspace_id == workspace_id)
            .order_by(Run.created_at.desc(), Run.id.desc())
            .limit(limit + 1)
        )

        if settings.sp_deployment_mode == "cloud":
            q = q.where(Run.user_id == user_id)

        if cursor is not None:
            try:
                cursor_created_at, cursor_id = _decode_run_cursor(cursor)
            except Exception:
                raise HTTPException(status_code=422, detail="invalid_cursor")
            cursor_dt = datetime.fromisoformat(cursor_created_at)
            q = q.where(
                or_(
                    Run.created_at < cursor_dt,
                    and_(
                        Run.created_at == cursor_dt,
                        Run.id < uuid.UUID(cursor_id),
                    ),
                )
            )

        result = await session.execute(q)
        runs = list(result.scalars().all())

    has_next = len(runs) > limit
    page = runs[:limit]

    next_cursor: str | None = None
    if has_next and page:
        last = page[-1]
        ts = last.created_at
        created_at_iso = (
            ts.replace(tzinfo=timezone.utc).isoformat()
            if ts.tzinfo is None
            else ts.isoformat()
        )
        next_cursor = _encode_run_cursor(created_at_iso, str(last.id))

    return RunListResponse(
        items=[_run_to_response(r) for r in page],
        next_cursor=next_cursor,
    )


@router.get("/{run_id}", response_model=RunResponse)
async def get_run(
    run_id: uuid.UUID,
    user_id: CurrentUserId,
    settings: Settings = Depends(get_settings),
    session_factory: async_sessionmaker[AsyncSession] = Depends(_get_session_factory),
) -> RunResponse:
    """Fetch run state by ID."""
    async with session_factory() as session:
        run = await session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run_not_found")
    if settings.sp_deployment_mode == "cloud" and run.user_id != user_id:
        raise HTTPException(status_code=404, detail="run_not_found")
    return _run_to_response(run)


@router.get("/{run_id}/events")
async def stream_events(
    run_id: uuid.UUID,
    user_id: CurrentUserId,
    settings: Settings = Depends(get_settings),
    session_factory: async_sessionmaker[AsyncSession] = Depends(_get_session_factory),
    bus: EventBus = Depends(_get_bus),
) -> EventSourceResponse:
    """SSE stream of run events.

    The 404 existence check fires BEFORE EventSourceResponse is constructed.
    sse-starlette swallows generator-time exceptions after headers flush;
    putting the check inside the generator would silently produce a 200
    with zero frames for non-existent runs.

    The ownership check (cloud mode) fires at the same point as the existence
    check — inside async with session_factory(), BEFORE _gen is defined,
    BEFORE EventSourceResponse is returned.
    """
    async with session_factory() as session:
        run = await session.get(Run, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run_not_found")
        if settings.sp_deployment_mode == "cloud" and run.user_id != user_id:
            raise HTTPException(status_code=404, detail="run_not_found")
        persisted = await _load_run_events(session, run_id)

    persisted_out = [_event_to_out(ev) for ev in persisted]

    async def _gen() -> AsyncIterator[dict]:
        for ev in persisted_out:
            yield _sse_frame(ev)
            if ev.kind == "stream_end":
                return
        async with bus.subscribe(run_id) as queue:
            while True:
                event = await queue.get()
                yield _sse_frame(event)
                if event.kind == "stream_end":
                    break

    return EventSourceResponse(_gen())


@router.post("/{run_id}/approve", response_model=ApprovalResponse)
async def approve_run(
    run_id: uuid.UUID,
    body: ApprovalDecisionRequest,
    user_id: CurrentUserId,
    settings: Settings = Depends(get_settings),
    session_factory: async_sessionmaker[AsyncSession] = Depends(_get_session_factory),
    bus: EventBus = Depends(_get_bus),
) -> ApprovalResponse:
    """Approve a pending approval gate.

    Transitions the run from awaiting_approval → running.
    Returns 404 if run or approval not found.
    Returns 409 if run is not in awaiting_approval state or approval already decided.
    """
    return await _handle_approval_decision(
        run_id=run_id,
        body=body,
        user_id=user_id,
        wire_verb="approve",
        event_kind="approval.approve",
        next_state=RunState.running,
        settings=settings,
        session_factory=session_factory,
        bus=bus,
    )


@router.post("/{run_id}/reject", response_model=ApprovalResponse)
async def reject_run(
    run_id: uuid.UUID,
    body: ApprovalDecisionRequest,
    user_id: CurrentUserId,
    settings: Settings = Depends(get_settings),
    session_factory: async_sessionmaker[AsyncSession] = Depends(_get_session_factory),
    bus: EventBus = Depends(_get_bus),
) -> ApprovalResponse:
    """Reject a pending approval gate.

    Transitions the run from awaiting_approval → cancelled.
    Returns 404 if run or approval not found.
    Returns 409 if run is not in awaiting_approval state or approval already decided.
    """
    return await _handle_approval_decision(
        run_id=run_id,
        body=body,
        user_id=user_id,
        wire_verb="reject",
        event_kind="approval.reject",
        next_state=RunState.cancelled,
        settings=settings,
        session_factory=session_factory,
        bus=bus,
    )


async def _handle_approval_decision(
    run_id: uuid.UUID,
    body: ApprovalDecisionRequest,
    user_id: str | None,
    wire_verb: str,
    event_kind: str,
    next_state: RunState,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    bus: EventBus,
) -> ApprovalResponse:
    """Shared logic for approve and reject decisions.

    Maps wire_verb ("approve"/"reject") to past-tense decision vocabulary
    ("approved"/"rejected") so the DB column and on-disk marker agree.
    """
    try:
        approval_id = uuid.UUID(body.approval_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="approval_id must be a valid UUID")

    # Map wire verb to past-tense vocabulary at the route boundary.
    decision: Literal["approved", "rejected"] = _DECISION_MAP[wire_verb]

    async with session_factory() as session:
        run = await session.get(Run, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run_not_found")

        if settings.sp_deployment_mode == "cloud" and run.user_id != user_id:
            raise HTTPException(status_code=404, detail="run_not_found")

        current = RunState(run.state)
        if current != RunState.awaiting_approval:
            raise HTTPException(
                status_code=409,
                detail={
                    "error_code": "illegal_transition",
                    "message": (
                        f"Run is in state '{current.value}', expected 'awaiting_approval'."
                    ),
                },
            )

        approval = await session.get(Approval, approval_id)
        if approval is None or approval.run_id != run_id:
            raise HTTPException(status_code=404, detail="approval_not_found")

        if approval.decided_at is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "error_code": "illegal_transition",
                    "message": "Approval has already been decided.",
                },
            )

        now = _now_utc()
        approval.decided_at = now
        approval.decision = decision  # past tense: "approved" or "rejected"
        approval.reason = body.reason

        transition(RunState.awaiting_approval, next_state)
        run.state = next_state.value
        run.updated_at = now
        if next_state in _TERMINAL_STATES:
            run.finished_at = now

        ev = await _insert_run_event(session, run_id, event_kind)
        await session.commit()
        await session.refresh(approval)

    await bus.publish(run_id, _event_to_out(ev))

    cid = secrets.token_hex(8)
    logger.info(
        "approval_decision run_id=%s approval_id=%s decision=%s cid=%s",
        run_id,
        approval_id,
        decision,
        cid,
    )

    # Write the resume marker file (best-effort IPC — never blocks the response).
    # The DB approval row is the source of truth; the marker file is cooperative IPC.
    # An OSError here MUST NOT return a failure response to the caller.
    # `decided_at` was set to `now` above; we pass the local variable to avoid
    # a pyright warning about `approval.decided_at` being `datetime | None`.
    try:
        path = await asyncio.to_thread(
            write_approval_marker,
            workdir_root=settings.sp_run_workdir_root,
            run_id=run_id,
            approval_id=approval_id,
            decision=decision,
            decided_at=now,
            comment=body.reason,
        )
        logger.info(
            "approval_marker_written run_id=%s approval_id=%s path=%s",
            run_id,
            approval_id,
            path,
        )
    except Exception as exc:
        logger.error(
            "approval_marker_write_failed run_id=%s approval_id=%s error=%s cid=%s",
            run_id,
            approval_id,
            type(exc).__name__,
            cid,
        )
        try:
            async with session_factory() as fail_session:
                fail_ev = await _insert_run_event(
                    fail_session,
                    run_id,
                    "run.approval_marker_failed",
                    payload={
                        "approval_id": str(approval_id),
                        "correlation_id": cid,
                        "error": type(exc).__name__,
                    },
                )
                await fail_session.commit()
            await bus.publish(run_id, _event_to_out(fail_ev))
        except Exception as inner_exc:
            logger.error(
                "approval_marker_failed_event_emit_error run_id=%s: %r",
                run_id,
                inner_exc,
            )

    return ApprovalResponse.model_validate(approval)
