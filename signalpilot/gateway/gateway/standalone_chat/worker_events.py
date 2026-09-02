"""Event payload builders and background helpers for the chat worker.

These helpers resolve shared collaborators (get_session_factory, chat_store,
_append) through the worker module. Test monkeypatches on the worker module
then reach the code paths in this module too.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import socket
import uuid
from typing import Any

import httpx

from gateway.db.models import GatewayChatRun
from gateway.standalone_chat.config import lease_seconds
from gateway.standalone_chat.domain import select_context_for_summary
from gateway.standalone_chat.execution import steer_execution
from gateway.standalone_chat.worker_context import (
    message_context as _message_context,
)


def _worker() -> Any:
    """Return the worker module. Import it late to avoid a circular import."""
    from gateway.standalone_chat import worker

    return worker


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


async def _lease_renewer(run_id: str, worker_id: str, stop: asyncio.Event) -> None:
    interval = max(5.0, lease_seconds() / 3)
    factory = _worker().get_session_factory()
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except TimeoutError:
            pass
        async with factory() as db:
            if not await _worker().chat_store.renew_lease(
                db,
                run_id=run_id,
                worker_id=worker_id,
                lease_seconds=lease_seconds(),
            ):
                stop.set()
                return


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


async def _persist_artifacts(
    *,
    run_id: str,
    worker_id: str,
    artifacts: list[dict[str, Any]],
) -> None:
    factory = _worker().get_session_factory()
    for artifact_payload in artifacts:
        normalized = {
            **artifact_payload,
            "snapshot": artifact_payload.get("snapshot") or artifact_payload.get("payload"),
        }
        async with factory() as db:
            run = await _worker().chat_store.get_worker_run(
                db, run_id=run_id, worker_id=worker_id
            )
            if run is None or run.cancellation_requested_at:
                return
            artifact = await _worker().chat_store.persist_artifact(
                db, run=run, payload=normalized
            )
        await _worker()._append(
            run_id,
            "artifact_created",
            {
                "artifact_id": artifact.id,
                "kind": artifact.kind,
                "filename": artifact.filename,
            },
        )


async def _update_summary(run_id: str) -> None:
    factory = _worker().get_session_factory()
    async with factory() as db:
        run = await db.get(GatewayChatRun, run_id)
        if run is None:
            return
        context = await _worker().chat_store.worker_context(db, run=run)
    messages = _message_context(context)
    artifact_refs = [
        {
            "id": artifact.id,
            "kind": artifact.kind,
            "filename": artifact.filename,
            "provenance": artifact.provenance_json,
        }
        for artifact in context["artifacts"]
    ]
    selection = select_context_for_summary(
        messages,
        artifact_refs=artifact_refs,
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
