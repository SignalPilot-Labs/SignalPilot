"""Database-leased durable worker for standalone data chat."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import uuid
from contextlib import suppress
from typing import Any

import httpx
from sqlalchemy import select

from gateway.db.engine import get_session_factory, init_db
from gateway.db.models import GatewayChatRun
from gateway.standalone_chat.config import (
    lease_seconds,
    standalone_chat_enabled,
    worker_concurrency,
    worker_poll_seconds,
)
from gateway.standalone_chat.domain import RunStatus, select_context_for_summary
from gateway.standalone_chat.execution import (
    cancel_execution_session,
    cleanup_finished_execution,
    stream_execution,
)
from gateway.standalone_chat.projects import project_metadata_context
from gateway.store import standalone_chat as chat_store

logger = logging.getLogger(__name__)
_CLARIFICATION_PREFIX = "CLARIFICATION_REQUESTED:"


def _worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def _message_context(context: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"role": row.role, "content": row.content}
        for row in context["messages"]
        if row.role in {"user", "assistant"}
    ]


def _warm_context(
    context: dict[str, Any],
    *,
    summary_override: str | None = None,
) -> dict[str, Any]:
    conversation = context["conversation"]
    project = context["project"]
    artifact_refs: list[dict[str, Any]] = []
    artifacts = context["artifacts"]
    for index, artifact in enumerate(artifacts):
        snapshot = artifact.snapshot_json or {}
        reference: dict[str, Any] = {
            "id": artifact.id,
            "kind": artifact.kind,
            "filename": artifact.filename,
            "parent_artifact_id": artifact.parent_artifact_id,
            "schema": {
                "columns": snapshot.get("columns")
                or (snapshot.get("source") or {}).get("columns"),
                "truncated": snapshot.get("truncated", False),
            },
            "provenance": artifact.provenance_json,
            "freshness_at": artifact.freshness_at.isoformat() if artifact.freshness_at else None,
            "assumptions": artifact.assumptions,
            "exclusions": artifact.exclusions,
            "caveats": artifact.caveats,
        }
        # Keep schemas for every artifact and bounded snapshot data for the five
        # most recent artifacts so follow-up questions can refine exact results.
        if index >= max(0, len(artifacts) - 5):
            if artifact.kind == "report":
                reference["snapshot"] = {
                    "html_excerpt": str(snapshot.get("html") or "")[:20_000],
                }
            else:
                rows = (
                    (snapshot.get("source") or {}).get("rows")
                    if artifact.kind == "chart"
                    else snapshot.get("rows")
                )
                reference["snapshot"] = {
                    "spec": snapshot.get("spec") if artifact.kind == "chart" else None,
                    "rows": list(rows or [])[:200],
                    "snapshot_row_count": len(rows or []),
                }
        artifact_refs.append(reference)
    artifact_refs.reverse()
    return {
        "project": {
            "id": project.id,
            "name": project.display_name or project.name,
            "description": project.description,
            "default_branch": conversation.branch,
            "connection_name": project.connection_name,
            "dbt_metadata": project_metadata_context(project, conversation.branch or "main"),
        },
        "conversation_summary": summary_override or conversation.internal_summary,
        "prior_artifacts": artifact_refs,
    }


async def _append(run_id: str, event_type: str, payload: dict[str, Any]) -> None:
    factory = get_session_factory()
    async with factory() as db:
        await chat_store.append_event(
            db,
            run_id=run_id,
            event_type=event_type,
            payload=payload,
        )


async def _lease_renewer(run_id: str, worker_id: str, stop: asyncio.Event) -> None:
    interval = max(5.0, lease_seconds() / 3)
    factory = get_session_factory()
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except TimeoutError:
            pass
        async with factory() as db:
            if not await chat_store.renew_lease(
                db,
                run_id=run_id,
                worker_id=worker_id,
                lease_seconds=lease_seconds(),
            ):
                stop.set()
                return


async def _cancellation_monitor(run_id: str, worker_id: str, stop: asyncio.Event) -> None:
    factory = get_session_factory()
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=1.0)
            return
        except TimeoutError:
            pass
        async with factory() as db:
            run = await chat_store.get_worker_run(db, run_id=run_id, worker_id=worker_id)
            if run is None:
                stop.set()
                return
            if run.cancellation_requested_at:
                await cancel_execution_session(db, run)
                return


async def _persist_artifacts(
    *,
    run_id: str,
    worker_id: str,
    artifacts: list[dict[str, Any]],
) -> None:
    factory = get_session_factory()
    for artifact_payload in artifacts:
        normalized = {
            **artifact_payload,
            "snapshot": artifact_payload.get("snapshot") or artifact_payload.get("payload"),
        }
        async with factory() as db:
            run = await chat_store.get_worker_run(db, run_id=run_id, worker_id=worker_id)
            if run is None or run.cancellation_requested_at:
                return
            artifact = await chat_store.persist_artifact(db, run=run, payload=normalized)
        await _append(
            run_id,
            "artifact_created",
            {
                "artifact_id": artifact.id,
                "kind": artifact.kind,
                "filename": artifact.filename,
            },
        )


async def _update_summary(run_id: str) -> None:
    factory = get_session_factory()
    async with factory() as db:
        run = await db.get(GatewayChatRun, run_id)
        if run is None:
            return
        context = await chat_store.worker_context(db, run=run)
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
        await chat_store.update_internal_summary(
            db,
            conversation_id=context["conversation"].id,
            summary=str(selection["summary"]),
        )


async def _execute_claimed_run(run_id: str, worker_id: str) -> None:
    stop = asyncio.Event()
    renewer = asyncio.create_task(_lease_renewer(run_id, worker_id, stop))
    cancellation = asyncio.create_task(_cancellation_monitor(run_id, worker_id, stop))
    final_text = ""
    streamed_text = ""
    try:
        factory = get_session_factory()
        async with factory() as db:
            run = await chat_store.get_worker_run(db, run_id=run_id, worker_id=worker_id)
            if run is None:
                return
            recovering = run.execution_attempt > 1
            context = await chat_store.worker_context(db, run=run)
            project = context["project"]
            branch = context["conversation"].branch or project.default_branch or "main"
            connection_name = str(project.connection_name or "").strip()
            if not connection_name:
                raise RuntimeError("The selected production connection is unavailable")
            all_messages = _message_context(context)
            selection = select_context_for_summary(
                all_messages,
                artifact_refs=[],
                usable_context_chars=400_000,
            )
            messages = (
                list(selection["recent_messages"])
                if selection is not None
                else all_messages
            )
            prompt = next(
                (message["content"] for message in reversed(messages) if message["role"] == "user"),
                "",
            )
            warm_context = _warm_context(
                context,
                summary_override=(
                    str(selection["summary"])
                    if selection is not None and not context["conversation"].internal_summary
                    else None
                ),
            )

        await _append(
            run_id,
            "status",
            {"status": "running", "reset_text": recovering},
        )
        await _append(
            run_id,
            "progress",
            {"label": "Exploring the project and relevant data"},
        )

        last_error: Exception | None = None
        for notebook_attempt in range(2):
            try:
                async with factory() as db:
                    active_run = await chat_store.get_worker_run(
                        db,
                        run_id=run_id,
                        worker_id=worker_id,
                    )
                    if active_run is None:
                        return
                    async for event in stream_execution(
                        db,
                        run=active_run,
                        worker_id=worker_id,
                        branch=branch,
                        connection_name=connection_name,
                        prompt=prompt,
                        messages=messages,
                        warm_context=warm_context,
                    ):
                        if stop.is_set():
                            raise asyncio.CancelledError
                        event_type = str(event.get("type") or "")
                        content = str(event.get("content") or "")
                        if event_type == "text_delta":
                            streamed_text += content
                            await _append(run_id, "text_delta", {"delta": content})
                        elif event_type == "text":
                            final_text = content
                        elif event_type == "tool_use":
                            tool_name = str(event.get("tool_name") or "analysis tool")
                            tool_input = event.get("tool_input") or {}
                            await _append(
                                run_id,
                                "tool_started",
                                {"tool": tool_name, "input": tool_input},
                            )
                            if tool_name.endswith(("query_database", "explain_query", "validate_sql")):
                                sql = tool_input.get("sql") if isinstance(tool_input, dict) else None
                                if sql:
                                    await _append(run_id, "sql", {"sql": sql})
                            if any(
                                marker in tool_name
                                for marker in ("schema", "table", "relationship", "metric")
                            ):
                                source_refs = {
                                    key: value
                                    for key, value in (
                                        tool_input.items()
                                        if isinstance(tool_input, dict)
                                        else []
                                    )
                                    if key
                                    in {
                                        "metric_name",
                                        "model_name",
                                        "schema_name",
                                        "source_name",
                                        "table_name",
                                    }
                                }
                                await _append(
                                    run_id,
                                    "source",
                                    {"tool": tool_name, **source_refs},
                                )
                        elif event_type == "tool_result":
                            is_error = bool(event.get("is_error"))
                            await _append(
                                run_id,
                                "tool_completed",
                                {
                                    "tool_call_id": event.get("tool_call_id"),
                                    "summary": (
                                        "The governed tool returned an error."
                                        if is_error
                                        else "The governed tool completed."
                                    ),
                                    "error": is_error,
                                },
                            )
                        elif event_type == "error":
                            raise RuntimeError(content or "Notebook analysis failed")
                        elif event_type == "final":
                            final_text = content or final_text or streamed_text
                            await _persist_artifacts(
                                run_id=run_id,
                                worker_id=worker_id,
                                artifacts=[
                                    item
                                    for item in event.get("artifacts") or []
                                    if isinstance(item, dict)
                                ],
                            )
                last_error = None
                break
            except (httpx.HTTPError, OSError) as exc:
                last_error = exc
                if notebook_attempt == 0:
                    final_text = ""
                    streamed_text = ""
                    await _append(
                        run_id,
                        "status",
                        {"status": "running", "reset_text": True},
                    )
                    await _append(
                        run_id,
                        "progress",
                        {"label": "Reconnecting to the analysis runtime"},
                    )
                    continue
                raise
        if last_error:
            raise last_error

        answer = (final_text or streamed_text).strip()
        if answer.startswith(_CLARIFICATION_PREFIX):
            question = answer[len(_CLARIFICATION_PREFIX) :].strip()
            if not question:
                raise RuntimeError("The analysis requested an empty clarification")
            await _append(
                run_id,
                "clarification_requested",
                {"message": question},
            )
            async with factory() as db:
                await chat_store.wait_for_clarification(
                    db,
                    run_id=run_id,
                    worker_id=worker_id,
                    question=question,
                )
            await _append(run_id, "status", {"status": "waiting_for_user"})
            return
        if not answer:
            raise RuntimeError("The analysis runtime returned no answer")

        await _append(
            run_id,
            "progress",
            {
                "label": "Answer complete",
                "summary": "Reviewed governed project metadata, relevant sources, and query results.",
            },
        )
        async with factory() as db:
            message = await chat_store.complete_run(
                db,
                run_id=run_id,
                worker_id=worker_id,
                content=answer,
            )
            terminal_status = (
                await db.scalar(
                    select(GatewayChatRun.status).where(GatewayChatRun.id == run_id)
                )
                if message is None
                else RunStatus.completed.value
            )
        if message is not None:
            await _append(run_id, "status", {"status": "completed"})
            await _update_summary(run_id)
        elif terminal_status == RunStatus.cancelled.value:
            await _append(run_id, "status", {"status": "cancelled"})
    except asyncio.CancelledError:
        async with get_session_factory()() as db:
            changed = await chat_store.fail_run(
                db,
                run_id=run_id,
                worker_id=worker_id,
                code="cancelled",
                message="The run was stopped.",
            )
        if changed:
            with suppress(Exception):
                await _append(run_id, "status", {"status": "cancelled"})
    except Exception as exc:
        logger.warning("Standalone chat run %s failed: %s", run_id, type(exc).__name__)
        public_message = "I could not complete this analysis. You can inspect the work and retry."
        with suppress(Exception):
            await _append(
                run_id,
                "error",
                {
                    "code": "analysis_failed",
                    "message": public_message,
                    "technical_detail": type(exc).__name__,
                },
            )
        async with get_session_factory()() as db:
            changed = await chat_store.fail_run(
                db,
                run_id=run_id,
                worker_id=worker_id,
                code="analysis_failed",
                message=public_message,
            )
        if changed:
            with suppress(Exception):
                await _append(run_id, "status", {"status": "failed"})
    finally:
        stop.set()
        for task in (renewer, cancellation):
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        with suppress(Exception):
            async with get_session_factory()() as db:
                await cleanup_finished_execution(db, run_id=run_id)


async def run_worker() -> None:
    await init_db()
    if not standalone_chat_enabled():
        logger.info("Standalone chat worker disabled by feature flag")
        return
    worker_id = _worker_id()
    concurrency = worker_concurrency()
    active: set[asyncio.Task[None]] = set()
    logger.info("Standalone chat worker started worker_id=%s concurrency=%d", worker_id, concurrency)
    while True:
        active = {task for task in active if not task.done()}
        available = concurrency - len(active)
        if available > 0:
            factory = get_session_factory()
            async with factory() as db:
                run_ids = await chat_store.claim_runs(
                    db,
                    worker_id=worker_id,
                    limit=available,
                    lease_seconds=lease_seconds(),
                )
            for run_id in run_ids:
                active.add(asyncio.create_task(_execute_claimed_run(run_id, worker_id)))
        await asyncio.sleep(worker_poll_seconds())


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
