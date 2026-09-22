"""Event payload builders and background helpers for the chat worker.

These helpers resolve shared collaborators (get_session_factory, chat_store,
_append) through the worker module. Test monkeypatches on the worker module
then reach the code paths in this module too.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import socket
import time
import uuid
from contextlib import suppress
from typing import Any

import httpx

from gateway.db.models import GatewayChatRun
from gateway.standalone_chat.config import lease_seconds
from gateway.standalone_chat.domain import select_context_for_summary
from gateway.standalone_chat.execution import steer_execution
from gateway.standalone_chat.worker_context import (
    message_context as _message_context,
)
from gateway.store import notebook_sessions as notebook_session_store

logger = logging.getLogger(__name__)

# A lease renewal that lands this much later than its interval means the
# worker's event loop stalled; the claim query may hand the run to another
# worker after the lease expires.
LEASE_RENEWAL_LATE_SECONDS = 10.0
# Bound on the notebook-runtime cancel call made before a re-execute.
PREVIOUS_ATTEMPT_CANCEL_TIMEOUT_SECONDS = 10.0


def _worker() -> Any:
    """Return the worker module. Import it late to avoid a circular import."""
    from gateway.standalone_chat import worker

    return worker


async def _cancel_previous_attempt(
    execution: Any,
    *,
    run_id: str,
    reason: str,
    timeout: float = PREVIOUS_ATTEMPT_CANCEL_TIMEOUT_SECONDS,
) -> bool:
    """Stop a still-running previous attempt of ``run_id`` on the runtime.

    Called before re-executing a re-claimed run (and on the worker's own
    reconnect). ``keep_kernels=1`` tells the runtime to stop the agent but
    leave its notebooks alive so the next /execute inherits them. Waits for
    a 2xx or the timeout; a failure only logs, the execute still proceeds.
    """
    url = execution.url.rsplit("/execute", 1)[0] + f"/cancel/{run_id}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                url,
                headers=execution.headers,
                params={"keep_kernels": "1"},
            )
    except (httpx.HTTPError, OSError) as exc:
        logger.warning(
            "Previous attempt cancel failed run_id=%s reason=%s error=%s",
            run_id,
            reason,
            type(exc).__name__,
        )
        return False
    logger.info(
        "Previous attempt cancel run_id=%s reason=%s status=%s",
        run_id,
        reason,
        response.status_code,
    )
    return response.is_success


def _worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


# Legacy fallback. Current notebook images flatten ToolResultBlock content
# with claude_agent_state.tool_result_text, so the result arrives as the
# tool's JSON text and json.loads below succeeds. Older sandbox images sent
# str(content_blocks) — a Python repr of a block list — and this regex pulls
# the ids out of that textually. Keep it until every pinned image is rebuilt.
_TOOL_RESULT_ID_RE = re.compile(
    r"[\"'](session_id|notebook_path|notebook)\\?[\"']\s*:\s*\\?[\"']([^\"'\\]+)"
)


def _notebook_started_payload(
    *,
    tool_result_content: str,
    gateway_session_id: str | None,
) -> dict[str, Any]:
    """Build the notebook_started event the live notebook panel attaches with.

    The start_analysis_notebook tool result is a JSON document carrying the
    kernel session id and notebook path inside the sandbox; combined with the
    gateway notebook session id the browser has everything it needs to open
    the run's notebook through the notebook proxy.
    """
    payload: dict[str, Any] = {"status": "running"}
    if gateway_session_id:
        payload["gateway_session_id"] = gateway_session_id
    started: dict[str, Any] = {}
    try:
        parsed = json.loads(tool_result_content or "{}")
        if isinstance(parsed, dict):
            started = parsed
    except (json.JSONDecodeError, TypeError):
        pass
    if not started:
        for key, value in _TOOL_RESULT_ID_RE.findall(
            tool_result_content or ""
        ):
            started.setdefault(key, value)
    if started.get("session_id"):
        payload["kernel_session_id"] = str(started["session_id"])
    if started.get("notebook_path"):
        payload["notebook_path"] = str(started["notebook_path"])
    # The notebook name defaults to "analysis" for older sandboxes.
    payload["notebook"] = str(started.get("notebook") or "analysis")
    return payload


async def _announce_notebook(run_id: str, payload: dict[str, Any]) -> None:
    """Append the notebook_started event and persist the conversation pointer.

    The pointer makes the conversation row the single source of truth for
    where the notebook lives. Persist only a complete id set: a partial
    payload cannot be attached to and must not clobber a good pointer.
    """
    await _worker()._append(run_id, "notebook_started", payload)
    gateway_session_id = payload.get("gateway_session_id")
    kernel_session_id = payload.get("kernel_session_id")
    notebook_path = payload.get("notebook_path")
    if not (gateway_session_id and kernel_session_id and notebook_path):
        return
    with suppress(Exception):
        factory = _worker().get_session_factory()
        async with factory() as db:
            await _worker().chat_store.set_conversation_notebook_for_run(
                db,
                run_id=run_id,
                gateway_session_id=str(gateway_session_id),
                kernel_session_id=str(kernel_session_id),
                notebook_path=str(notebook_path),
                name=str(payload.get("notebook") or "analysis"),
            )


async def empty_answer_error(
    *,
    run_id: str,
    worker_id: str,
    execution: Any,
    final_result: dict[str, Any] | None,
) -> Exception:
    """Explain a run that streamed to completion with no answer text.

    The two known causes are the runtime being stopped underneath the run
    (the notebook session is no longer running: snapshotted, stopped, or
    timed out) and the model ending its turn without text (the SDK result
    says so). Both are recorded on the error so the next occurrence is
    diagnosable from the run alone.
    """
    from gateway.standalone_chat.worker_errors import AnalysisRuntimeError

    session_status: str | None = None
    session_id = str(getattr(execution, "session_id", "") or "")
    if session_id:
        with suppress(Exception):
            factory = _worker().get_session_factory()
            async with factory() as db:
                run = await _worker().chat_store.get_worker_run(db, run_id=run_id, worker_id=worker_id)
                info = await notebook_session_store.get_session_internal(
                    db, session_id=session_id, org_id=str(run.org_id) if run else None
                )
                session_status = str(getattr(info, "status", "") or "") or None
    diagnostic: dict[str, Any] = {
        "notebook_session_id": session_id or None,
        "notebook_session_status": session_status,
        **dict(final_result or {}),
    }
    if session_status and session_status != "running":
        message = (
            "The analysis runtime was stopped while the run was in progress "
            f"(session {session_status}). Retry the message; the runtime resumes on the next run."
        )
        return AnalysisRuntimeError(
            message,
            full_trace=message,
            diagnostic_context=diagnostic,
            public_error_code="runtime_stopped",
            public_error_message=message,
        )
    return AnalysisRuntimeError(
        "The analysis runtime returned no answer",
        full_trace="The analysis runtime returned no answer",
        diagnostic_context=diagnostic,
    )


async def touch_run_session(run_id: str, worker_id: str) -> bool:
    """Ping the notebook session the run executes on, so the lifecycle loop
    sees it as active. Only the browser pings otherwise, and a chat run on
    a session older than the idle window was being snapshotted mid-run.
    Returns True when a session was pinged."""
    factory = _worker().get_session_factory()
    with suppress(Exception):
        async with factory() as db:
            run = await _worker().chat_store.get_worker_run(db, run_id=run_id, worker_id=worker_id)
            session_id = getattr(run, "execution_session_id", None) if run else None
            if not session_id:
                return False
            pinged = await notebook_session_store.ping_session_by_id(
                db, session_id=str(session_id), org_id=str(run.org_id)
            )
            return pinged is not None
    return False


async def _lease_renewer(run_id: str, worker_id: str, stop: asyncio.Event) -> None:
    interval = max(5.0, lease_seconds() / 3)
    factory = _worker().get_session_factory()
    last_renewed_at = time.monotonic()
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except TimeoutError:
            pass
        # Watchdog: a stalled event loop shows up here as a late wake-up.
        late_by = time.monotonic() - last_renewed_at - interval
        if late_by > LEASE_RENEWAL_LATE_SECONDS:
            logger.warning(
                "Lease renewal late run_id=%s worker_id=%s late_by_s=%.1f lease_s=%s",
                run_id,
                worker_id,
                late_by,
                lease_seconds(),
            )
        async with factory() as db:
            renewed = await _worker().chat_store.renew_lease(
                db,
                run_id=run_id,
                worker_id=worker_id,
                lease_seconds=lease_seconds(),
            )
        last_renewed_at = time.monotonic()
        if not renewed:
            logger.warning(
                "Lease renewal lost run_id=%s worker_id=%s; stopping the run",
                run_id,
                worker_id,
            )
            stop.set()
            return
        logger.info(
            "Lease renewed run_id=%s worker_id=%s lease_s=%s",
            run_id,
            worker_id,
            lease_seconds(),
        )
        await touch_run_session(run_id, worker_id)


async def _cancellation_monitor(
    run_id: str,
    worker_id: str,
    stop: asyncio.Event,
    worker_task: asyncio.Task[None],
) -> None:
    factory = _worker().get_session_factory()
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=1.0)
            return
        except TimeoutError:
            pass
        async with factory() as db:
            run = await _worker().chat_store.get_worker_run(
                db, run_id=run_id, worker_id=worker_id
            )
            if run is None:
                stop.set()
                return
            if run.cancellation_requested_at:
                stop.set()
                worker_task.cancel()
                return


async def _steering_monitor(
    run_id: str,
    worker_id: str,
    execution: Any,
    stop: asyncio.Event,
) -> None:
    """Deliver persisted interjections in order, retrying until accepted."""
    factory = _worker().get_session_factory()
    while not stop.is_set():
        async with factory() as db:
            pending = await _worker().chat_store.pending_steering_messages(
                db,
                run_id=run_id,
                worker_id=worker_id,
            )
        for message in pending:
            if stop.is_set():
                return
            try:
                accepted = await steer_execution(
                    execution,
                    run_id=run_id,
                    steering_id=message.id,
                    message=message.content,
                )
            except (httpx.HTTPError, OSError):
                accepted = False
            if not accepted:
                break
            async with factory() as db:
                await _worker().chat_store.mark_steering_message_picked_up(
                    db,
                    run_id=run_id,
                    worker_id=worker_id,
                    message_id=message.id,
                )
        try:
            await asyncio.wait_for(stop.wait(), timeout=0.35)
        except TimeoutError:
            pass


async def _update_summary(run_id: str) -> None:
    factory = _worker().get_session_factory()
    async with factory() as db:
        run = await db.get(GatewayChatRun, run_id)
        if run is None:
            return
        context = await _worker().chat_store.worker_context(db, run=run)
    messages = _message_context(context)
    selection = select_context_for_summary(
        messages,
        usable_context_chars=400_000,
    )
    if selection is None:
        return
    async with factory() as db:
        await _worker().chat_store.update_internal_summary(
            db,
            conversation_id=context["conversation"].id,
            summary=str(selection["summary"]),
        )
