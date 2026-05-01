"""Run and approval routes for the Workspaces API.

auth: TODO(round-5) — routes are currently open (no JWT/Clerk auth).

Route summary:
  POST   /v1/runs                      Submit a new run
  GET    /v1/runs/{run_id}             Fetch run state
  GET    /v1/runs/{run_id}/events      SSE stream of run events
  POST   /v1/runs/{run_id}/approve     Approve a pending approval gate
  POST   /v1/runs/{run_id}/reject      Reject a pending approval gate

SSE ordering (load-bearing — do not reorder):
  1. Existence check fires BEFORE EventSourceResponse is constructed.
     sse-starlette swallows exceptions raised inside the generator after
     headers have flushed, so the 404 MUST be raised in the route function
     body before returning EventSourceResponse.
  2. Persisted events are snapshotted while the DB session is still open.
  3. Live bus events are drained until stream_end or a run-terminal event.

If this file grows past ~250 lines, split SSE into routes/runs_events.py.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sse_starlette.sse import EventSourceResponse

from workspaces_api.agent.inference import resolve_inference_source
from workspaces_api.agent.spawner import SpawnRequest, Spawner
from workspaces_api.config import Settings, get_settings
from workspaces_api.events.bus import EventBus
from workspaces_api.models import Approval, Run, RunEvent
from workspaces_api.schemas import (
    ApprovalDecisionRequest,
    ApprovalResponse,
    RunCreateRequest,
    RunEventOut,
    RunResponse,
)
from workspaces_api.states import RunState, transition

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/runs")

_TERMINAL_STATES = {RunState.succeeded, RunState.failed, RunState.cancelled}


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


@router.post("", status_code=201, response_model=RunResponse)
async def submit_run(
    body: RunCreateRequest,
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
        )
        await spawner.spawn(spawn_req)

        transition(RunState(run.state), RunState.running)
        run.state = RunState.running.value
        run.updated_at = _now_utc()

        ev = await _insert_run_event(session, run.id, "run.started")
        await session.commit()
        await session.refresh(run)

    await bus.publish(run.id, _event_to_out(ev))
    logger.info("run_started run_id=%s mode=%s", run.id, bundle.mode)
    return _run_to_response(run)


@router.get("/{run_id}", response_model=RunResponse)
async def get_run(
    run_id: uuid.UUID,
    session_factory: async_sessionmaker[AsyncSession] = Depends(_get_session_factory),
) -> RunResponse:
    """Fetch run state by ID."""
    async with session_factory() as session:
        run = await session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run_not_found")
    return _run_to_response(run)


@router.get("/{run_id}/events")
async def stream_events(
    run_id: uuid.UUID,
    session_factory: async_sessionmaker[AsyncSession] = Depends(_get_session_factory),
    bus: EventBus = Depends(_get_bus),
) -> EventSourceResponse:
    """SSE stream of run events.

    The 404 existence check fires BEFORE EventSourceResponse is constructed.
    sse-starlette swallows generator-time exceptions after headers flush;
    putting the check inside the generator would silently produce a 200
    with zero frames for non-existent runs.
    """
    async with session_factory() as session:
        run = await session.get(Run, run_id)
        if run is None:
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
        decision="approve",
        event_kind="approval.approve",
        next_state=RunState.running,
        session_factory=session_factory,
        bus=bus,
    )


@router.post("/{run_id}/reject", response_model=ApprovalResponse)
async def reject_run(
    run_id: uuid.UUID,
    body: ApprovalDecisionRequest,
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
        decision="reject",
        event_kind="approval.reject",
        next_state=RunState.cancelled,
        session_factory=session_factory,
        bus=bus,
    )


async def _handle_approval_decision(
    run_id: uuid.UUID,
    body: ApprovalDecisionRequest,
    decision: str,
    event_kind: str,
    next_state: RunState,
    session_factory: async_sessionmaker[AsyncSession],
    bus: EventBus,
) -> ApprovalResponse:
    """Shared logic for approve and reject decisions."""
    try:
        approval_id = uuid.UUID(body.approval_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="approval_id must be a valid UUID")

    async with session_factory() as session:
        run = await session.get(Run, run_id)
        if run is None:
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
        approval.decision = decision
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
    logger.info(
        "approval_decision run_id=%s approval_id=%s decision=%s",
        run_id,
        approval_id,
        decision,
    )
    return ApprovalResponse.model_validate(approval)
