"""Database-leased durable worker for standalone data chat."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import suppress
from typing import Any

import httpx

from gateway.db.engine import get_session_factory, init_db
from gateway.standalone_chat import worker_files
from gateway.standalone_chat.config import (
    lease_seconds,
    standalone_chat_enabled,
    worker_concurrency,
    worker_poll_seconds,
)
from gateway.standalone_chat.domain import (
    select_context_for_summary,
)
from gateway.standalone_chat.execution import (
    cancel_execution_session,
    cleanup_expired_approval_sandboxes,
    cleanup_expired_runtime_objects,
    cleanup_finished_execution,
    prepare_execution,
    stream_execution,
)
from gateway.standalone_chat.worker_context import (
    merge_text_delta as _merge_text_delta,
)
from gateway.standalone_chat.worker_context import (
    message_context as _message_context,
)
from gateway.standalone_chat.worker_context import (
    warm_context as _warm_context,
)
from gateway.standalone_chat.worker_errors import (
    AnalysisRuntimeError as _AnalysisRuntimeError,
)
from gateway.standalone_chat.worker_errors import (
    public_diagnostic_context as _public_diagnostic_context,
)
from gateway.standalone_chat.worker_errors import (
    public_error_message as _public_error_message,
)
from gateway.standalone_chat.worker_errors import (
    public_full_trace as _public_full_trace,
)
from gateway.standalone_chat.worker_events import (
    _cancellation_monitor,
    _lease_renewer,
    _notebook_started_payload,
    _persist_artifacts,
    _steering_monitor,
    _update_summary,
    _worker_id,
)
from gateway.store import standalone_chat as chat_store

logger = logging.getLogger(__name__)
_CLARIFICATION_PREFIX = "CLARIFICATION_REQUESTED:"


async def _append(run_id: str, event_type: str, payload: dict[str, Any]) -> None:
    factory = get_session_factory()
    async with factory() as db:
        await chat_store.append_event(
            db,
            run_id=run_id,
            event_type=event_type,
            payload=payload,
        )


async def _announce_notebook(run_id: str, payload: dict[str, Any]) -> None:
    """Append the notebook_started event and persist the conversation pointer.

    The pointer makes the conversation row the single source of truth for
    where the notebook lives. Persist only a complete id set: a partial
    payload cannot be attached to and must not clobber a good pointer.
    """
    await _append(run_id, "notebook_started", payload)
    gateway_session_id = payload.get("gateway_session_id")
    kernel_session_id = payload.get("kernel_session_id")
    notebook_path = payload.get("notebook_path")
    if not (gateway_session_id and kernel_session_id and notebook_path):
        return
    with suppress(Exception):
        factory = get_session_factory()
        async with factory() as db:
            await chat_store.set_conversation_notebook_for_run(
                db,
                run_id=run_id,
                gateway_session_id=str(gateway_session_id),
                kernel_session_id=str(kernel_session_id),
                notebook_path=str(notebook_path),
                name=str(payload.get("notebook") or "analysis"),
            )


async def _execute_claimed_run(run_id: str, worker_id: str) -> None:
    stop = asyncio.Event()
    renewer = asyncio.create_task(_lease_renewer(run_id, worker_id, stop))
    worker_task = asyncio.current_task()
    assert worker_task is not None
    cancellation = asyncio.create_task(_cancellation_monitor(run_id, worker_id, stop, worker_task))
    steering: asyncio.Task[None] | None = None
    final_text = ""
    streamed_text = ""
    report_proposal: dict[str, Any] | None = None
    report_action_outcome: dict[str, Any] | None = None
    dashboard_preview: dict[str, Any] | None = None
    starts_new_text_block = False
    tool_names_by_id: dict[str, str] = {}
    try:
        factory = get_session_factory()
        async with factory() as db:
            run = await chat_store.get_worker_run(db, run_id=run_id, worker_id=worker_id)
            if run is None:
                return
            # Captured for the file mirror; avoids re-querying per event.
            run_org_id, run_user_id = run.org_id, run.user_id
            run_conversation_id = run.conversation_id
            recovering = run.execution_attempt > 1
            context = await chat_store.worker_context(db, run=run)
            project = context["project"]
            branch = context["conversation"].branch or project.default_branch or "main"
            commit_sha = str(context["conversation"].commit_sha or "")
            if len(commit_sha) != 40:
                raise RuntimeError("The selected project commit is unavailable")
            connection_name = str(project.connection_name or "").strip()
            if not connection_name:
                raise RuntimeError("The selected production connection is unavailable")
            all_messages = _message_context(context)
            selection = select_context_for_summary(
                all_messages,
                artifact_refs=[],
                usable_context_chars=400_000,
            )
            messages = list(selection["recent_messages"]) if selection is not None else all_messages
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
            report_reference = warm_context.get("report_reference")
            if isinstance(report_reference, dict) and report_reference.get("report_id"):
                from gateway.store import chat_reports as report_store

                report_context = await report_store.load_report_context(
                    db,
                    org_id=run.org_id,
                    user_id=run.user_id,
                    project_id=run.project_id,
                    report_id=str(report_reference["report_id"]),
                )
                if report_context is not None:
                    warm_context["report_context"] = report_context.model_dump(mode="json")

        await _append(
            run_id,
            "status",
            {"status": "running", "reset_text": recovering},
        )

        # Runtime boot progress: emitted ONLY when the sandbox is actually
        # cold (fresh provision or snapshot resume). A warm conversation
        # reuses its running sandbox and the UI shows nothing.
        boot_started_at: dict[str, float] = {}

        async def _on_cold_boot(phase: str) -> None:
            boot_started_at.setdefault("t0", time.monotonic())
            await _append(run_id, "runtime_boot", {"phase": phase})

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
                    execution = await prepare_execution(
                        db,
                        run=active_run,
                        worker_id=worker_id,
                        branch=branch,
                        connection_name=connection_name,
                        commit_sha=commit_sha,
                        prompt=prompt,
                        messages=messages,
                        warm_context=warm_context,
                        on_cold_boot=_on_cold_boot,
                    )
                    if "t0" in boot_started_at:
                        await _append(
                            run_id,
                            "runtime_boot",
                            {
                                "phase": "ready",
                                "boot_ms": int((time.monotonic() - boot_started_at.pop("t0")) * 1000),
                            },
                        )
                    if steering is None:
                        steering = asyncio.create_task(
                            _steering_monitor(
                                run_id,
                                worker_id,
                                execution,
                                stop,
                            )
                        )
                async for event in stream_execution(execution):
                    if stop.is_set():
                        raise asyncio.CancelledError
                    event_type = str(event.get("type") or "")
                    content = str(event.get("content") or "")
                    parent_tool_call_id = str(event.get("parent_tool_call_id") or "")
                    if event_type == "text_delta":
                        if parent_tool_call_id:
                            # Subagent narration: recorded for its spawn card,
                            # never merged into the run's own narration.
                            if content:
                                await _append(
                                    run_id,
                                    "text_delta",
                                    {
                                        "delta": content,
                                        "parent_tool_call_id": parent_tool_call_id,
                                    },
                                )
                            continue
                        streamed_text, emitted_content = _merge_text_delta(
                            streamed_text,
                            content,
                            starts_new_block=starts_new_text_block,
                        )
                        if emitted_content:
                            await _append(
                                run_id,
                                "text_delta",
                                {"delta": emitted_content},
                            )
                            starts_new_text_block = False
                    elif event_type == "thinking_delta":
                        if content:
                            await _append(
                                run_id,
                                "thinking_delta",
                                {
                                    "delta": content,
                                    **({"parent_tool_call_id": parent_tool_call_id} if parent_tool_call_id else {}),
                                },
                            )
                    elif event_type == "text":
                        final_text = content
                    elif event_type == "progress":
                        await _append(
                            run_id,
                            "progress",
                            {"label": content or "Analysis is continuing"},
                        )
                    elif event_type == "tool_use":
                        # Subagent tool calls don't split the main narration.
                        if not parent_tool_call_id:
                            starts_new_text_block = bool(streamed_text)
                        tool_name = str(event.get("tool_name") or "analysis tool")
                        tool_input = event.get("tool_input") or {}
                        tool_call_id = str(event.get("tool_call_id") or "")
                        if tool_call_id:
                            tool_names_by_id[tool_call_id] = tool_name
                        await _append(
                            run_id,
                            "tool_started",
                            {
                                "tool": tool_name,
                                "input": tool_input,
                                # tool_call_id makes completion pairing exact
                                # (parallel subagents complete out of order);
                                # parent groups the step under its spawn.
                                "tool_call_id": tool_call_id or None,
                                **({"parent_tool_call_id": parent_tool_call_id} if parent_tool_call_id else {}),
                            },
                        )
                        # Mirror file writes with the raw tool input. Never raises.
                        await worker_files.mirror_file_tool(
                            run_id=run_id,
                            org_id=run_org_id,
                            user_id=run_user_id,
                            conversation_id=run_conversation_id,
                            tool_name=tool_name,
                            tool_input=tool_input,
                            secrets=worker_files.execution_secrets(execution),
                        )
                        # Side events (sql/source) attach to the latest OPEN
                        # top-level step in the UI — suppress them for
                        # subagent tools, whose SQL still shows on the child
                        # step from its input.
                        if parent_tool_call_id:
                            continue
                        if tool_name.endswith(("query_database", "explain_query", "validate_sql")):
                            sql = tool_input.get("sql") if isinstance(tool_input, dict) else None
                            if sql:
                                await _append(run_id, "sql", {"sql": sql})
                        if any(marker in tool_name for marker in ("schema", "table", "relationship", "metric")):
                            source_refs = {
                                key: value
                                for key, value in (tool_input.items() if isinstance(tool_input, dict) else [])
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
                        if not parent_tool_call_id:
                            starts_new_text_block = bool(streamed_text)
                        is_error = bool(event.get("is_error"))
                        tool_call_id = str(event.get("tool_call_id") or "")
                        completed_tool = tool_names_by_id.get(tool_call_id, "")
                        if is_error:
                            # Author-visible events redact tool errors. Log the raw
                            # error text here (server-side only) so operators can see
                            # exactly why a tool failed.
                            logger.warning(
                                "standalone-chat tool error tool=%s run=%s raw=%s",
                                completed_tool or "unknown",
                                run_id,
                                (content or "")[:2000],
                            )
                        completed_payload: dict[str, Any] = {
                            "tool_call_id": event.get("tool_call_id"),
                            "summary": (
                                "The tool returned an error."
                                if is_error
                                else "The tool completed."
                            ),
                            "error": is_error,
                        }
                        if parent_tool_call_id:
                            completed_payload["parent_tool_call_id"] = parent_tool_call_id
                        if completed_tool == "Agent" and not is_error and content:
                            # The Agent tool result IS the subagent's final
                            # report — surfaced in its card, same disclosure
                            # level as the agent's own streamed narration.
                            completed_payload["report"] = content[:4000]
                        await _append(
                            run_id,
                            "tool_completed",
                            completed_payload,
                        )
                        if not is_error and completed_tool.endswith("start_analysis_notebook"):
                            await _announce_notebook(
                                run_id,
                                _notebook_started_payload(
                                    tool_result_content=content,
                                    gateway_session_id=execution.session_id,
                                ),
                            )
                        if completed_tool.endswith("run_cells"):
                            await _append(
                                run_id,
                                "cell_executed",
                                {"status": "failed" if is_error else "completed"},
                            )
                    elif event_type == "notebook_started":
                        # Emitted by the runtime when it starts a replacement
                        # kernel (notebook recovery). The normal path derives
                        # this event from the start_analysis_notebook result.
                        recovery_payload: dict[str, Any] = {"status": "running"}
                        if execution.session_id:
                            recovery_payload["gateway_session_id"] = execution.session_id
                        if event.get("session_id"):
                            recovery_payload["kernel_session_id"] = str(event["session_id"])
                        if event.get("notebook_path"):
                            recovery_payload["notebook_path"] = str(event["notebook_path"])
                        if event.get("notebook"):
                            recovery_payload["notebook"] = str(event["notebook"])
                        await _announce_notebook(run_id, recovery_payload)
                    elif event_type == "error":
                        raise _AnalysisRuntimeError(
                            content,
                            full_trace=str(event.get("full_trace") or content or ""),
                            diagnostic_context=event.get("diagnostic_context"),
                        )
                    elif event_type == "final":
                        final_text = content or final_text or streamed_text
                        # Operator accounting: cost + token usage reported by
                        # the agent SDK, persisted on the run row.
                        raw_usage = event.get("usage")
                        raw_cost = event.get("cost_usd")
                        if raw_cost is not None or isinstance(raw_usage, dict):
                            with suppress(Exception):
                                async with factory() as db:
                                    await chat_store.record_run_usage(
                                        db,
                                        run_id=run_id,
                                        worker_id=worker_id,
                                        cost_usd=(raw_cost if isinstance(raw_cost, (int, float)) else None),
                                        usage=(raw_usage if isinstance(raw_usage, dict) else None),
                                    )
                        raw_report_proposal = event.get("report_proposal")
                        report_proposal = raw_report_proposal if isinstance(raw_report_proposal, dict) else None
                        raw_report_action_outcome = event.get("report_action_outcome")
                        report_action_outcome = (
                            raw_report_action_outcome if isinstance(raw_report_action_outcome, dict) else None
                        )
                        raw_dashboard_preview = event.get("dashboard_preview")
                        dashboard_preview = (
                            raw_dashboard_preview if isinstance(raw_dashboard_preview, dict) else None
                        )
                        await _persist_artifacts(
                            run_id=run_id,
                            worker_id=worker_id,
                            artifacts=[item for item in event.get("artifacts") or [] if isinstance(item, dict)],
                        )
                        if event.get("kernel_stopped"):
                            await _append(run_id, "kernel_stopped", {"status": "stopped"})
                last_error = None
                break
            except (httpx.HTTPError, OSError) as exc:
                last_error = exc
                if notebook_attempt == 0:
                    starts_new_text_block = bool(streamed_text)
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
            return
        if not answer:
            raise RuntimeError("The analysis runtime returned no answer")

        async with factory() as db:
            message = await chat_store.complete_run(
                db,
                run_id=run_id,
                worker_id=worker_id,
                content=answer,
                report_proposal=report_proposal,
                report_action_outcome=report_action_outcome,
                dashboard_preview=dashboard_preview,
            )
        if message is not None:
            await _update_summary(run_id)
    except asyncio.CancelledError:
        async with get_session_factory()() as db:
            run = await chat_store.get_worker_run(
                db,
                run_id=run_id,
                worker_id=worker_id,
            )
            await chat_store.fail_run(
                db,
                run_id=run_id,
                worker_id=worker_id,
                code="cancelled",
                message="The run was stopped.",
            )
            if run is not None:
                await cancel_execution_session(db, run)
    except Exception as exc:
        logger.warning(
            "Standalone chat run %s failed: %s",
            run_id,
            type(exc).__name__,
            exc_info=True,
        )
        public_message = _public_error_message(exc)
        full_trace = _public_full_trace(exc)
        diagnostic_context = _public_diagnostic_context(exc)
        diagnostic_context["run_id"] = run_id
        with suppress(Exception):
            await _append(
                run_id,
                "error",
                {
                    "code": "analysis_failed",
                    "message": public_message,
                    "full_trace": full_trace,
                    "diagnostic_context": diagnostic_context,
                },
            )
        async with get_session_factory()() as db:
            await chat_store.fail_run(
                db,
                run_id=run_id,
                worker_id=worker_id,
                code="analysis_failed",
                message=public_message,
            )
    finally:
        stop.set()
        for task in (renewer, cancellation, steering):
            if task is None:
                continue
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        with suppress(Exception):
            async with get_session_factory()() as db:
                await chat_store.finalize_undelivered_steering(
                    db,
                    run_id=run_id,
                )
        with suppress(Exception):
            async with get_session_factory()() as db:
                await cleanup_finished_execution(db, run_id=run_id)
        # Tear down the improvement-run agent sandbox (per-run). The chat agent
        # no longer creates one (collapsed to the notebook session). The dbt
        # executor is NOT released here: it is conversation-scoped and kept warm
        # across messages, freed by cleanup_idle_executors after the warm window.
        with suppress(Exception):
            from ..mcp.tools.sandbox_vm import release_session_sandbox

            await release_session_sandbox(f"chat:{run_id}")


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
                await cleanup_expired_approval_sandboxes(db)
                await cleanup_expired_runtime_objects(db)
                with suppress(Exception):
                    from .dbt_executor import cleanup_idle_executors

                    await cleanup_idle_executors()
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
