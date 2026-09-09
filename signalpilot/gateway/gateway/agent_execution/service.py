"""MCP adapter for the existing Chats store and worker; no separate runtime."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time

from sqlalchemy import select

from gateway.db.engine import get_session_factory
from gateway.db.models import GatewayChatConversation, GatewayChatMessage, GatewayChatRun, GatewayChatRunEvent
from gateway.git.repos import branch_head_sha
from gateway.standalone_chat.config import runtime_env, standalone_chat_enabled
from gateway.standalone_chat.projects import authorize_chat_project, evaluate_project_readiness
from gateway.store import Store, standalone_chat as chat_store
from gateway.store.standalone_chat.helpers import _stage_run_event, _event_info, _token_usage
from gateway.store.standalone_chat.admission import lock_agent_account, check_agent_capacity

from .chat_view import chat_url
from .contracts import AgentLaunchRequest, AgentResult


class AgentService:
    def __init__(self, factory=None):
        self._factory = factory

    @property
    def factory(self):
        return self._factory or get_session_factory()

    @staticmethod
    def require_enabled():
        if os.getenv("SP_FEATURE_MCP_AGENT", "true").lower() not in {"1", "true"}:
            raise ValueError("Cloud agent delegation is disabled")
        if not standalone_chat_enabled():
            raise ValueError("SignalPilot Chats is not enabled. Enable Chats to delegate agents through MCP.")

    async def _lock_org(self, db, org_id):
        await lock_agent_account(db, org_id)

    async def _capacity(self, db, org_id):
        await check_agent_capacity(db, org_id)

    async def _resolve_request(self, db, org_id, user_id, request):
        store = Store(db, org_id=org_id, user_id=user_id)
        settings = await store.load_settings()
        project_id = request.project_id or settings.mcp_agent_default_project_id
        setup = "Open Settings → MCP Connect and configure the SignalPilot agent defaults."
        if not project_id:
            raise ValueError(f"SignalPilot agent needs a default project. {setup}")
        project = await authorize_chat_project(db, org_id=org_id, user_id=user_id, project_id=project_id)
        if project is None or project.status != "active":
            raise ValueError(f"The selected agent project is unavailable. {setup}")
        saved_branch = (
            settings.mcp_agent_default_branch if project_id == settings.mcp_agent_default_project_id else None
        )
        branch = request.branch or saved_branch or project.default_branch or "main"
        saved_connection = (
            settings.mcp_agent_default_connection_name if project_id == settings.mcp_agent_default_project_id else None
        )
        connection = request.connection_name or saved_connection or project.connection_name
        if connection != project.connection_name:
            raise ValueError(
                f"SignalPilot agents use the project's Chats connection ({project.connection_name}). Update the project connection or MCP defaults in Settings."
            )
        readiness = await evaluate_project_readiness(
            db, org_id=org_id, user_id=user_id, project=project, branch_override=branch
        )
        if not readiness.ready:
            raise ValueError(
                f"Project is not ready for Chats: {readiness.message} Open the project's setup in Settings."
            )
        commit = branch_head_sha(project.id, branch)
        if not commit or len(commit) != 40:
            raise ValueError("The selected project commit is unavailable. Re-sync the project before starting Chats.")
        return project, branch, commit

    async def _owned(self, db, org_id, user_id, thread_id):
        row = await db.scalar(
            select(GatewayChatConversation).where(
                GatewayChatConversation.id == thread_id,
                GatewayChatConversation.org_id == org_id,
                GatewayChatConversation.user_id == user_id,
                GatewayChatConversation.origin == "mcp_agent",
                GatewayChatConversation.status == "active",
            )
        )
        if row is None:
            raise ValueError("Agent chat not found")
        return row

    async def _latest(self, db, org_id, user_id, thread_id):
        await self._owned(db, org_id, user_id, thread_id)
        run = await db.scalar(
            select(GatewayChatRun)
            .join(GatewayChatMessage, GatewayChatMessage.id == GatewayChatRun.user_message_id)
            .where(
                GatewayChatRun.conversation_id == thread_id,
                GatewayChatRun.org_id == org_id,
                GatewayChatRun.user_id == user_id,
            )
            .order_by(GatewayChatMessage.sequence.desc(), GatewayChatRun.created_at.desc(), GatewayChatRun.id.desc())
            .limit(1)
        )
        if run is None or (run.runtime_env or None) != (runtime_env() or None):
            raise ValueError("Agent chat run not found in this environment")
        return run

    @staticmethod
    def _queued_event(db, run):
        _stage_run_event(
            db, run=run, event_type="status", payload={"status": "queued", "chat_url": chat_url(run.conversation_id)}
        )

    async def start(self, org_id, user_id, request: AgentLaunchRequest, progress=None):
        self.require_enabled()
        async with self.factory() as db:
            await self._lock_org(db, org_id)
            idem = None
            if request.client_request_id:
                idem = (
                    "mcp-agent:"
                    + hashlib.sha256(json.dumps([org_id, user_id, request.client_request_id]).encode()).hexdigest()
                )
                existing = await db.scalar(
                    select(GatewayChatMessage.conversation_id).where(
                        GatewayChatMessage.org_id == org_id,
                        GatewayChatMessage.user_id == user_id,
                        GatewayChatMessage.idempotency_key == idem,
                    )
                )
                if existing:
                    await db.rollback()
                    return await self.get(org_id, user_id, existing)
            await self._capacity(db, org_id)
            project, branch, commit = await self._resolve_request(db, org_id, user_id, request)
            query_budget, chat_budget = await chat_store.default_chat_budgets(db, org_id=org_id, user_id=user_id)
            conversation, run = await chat_store.create_conversation_with_run(
                db,
                org_id=org_id,
                user_id=user_id,
                project=project,
                branch=branch,
                commit_sha=commit,
                message=request.task,
                origin="mcp_agent",
                commit=False,
                per_query_budget_usd=query_budget,
                chat_budget_usd=chat_budget,
            )
            conversation.title = request.task[:200]
            if idem:
                message = await db.get(GatewayChatMessage, run.user_message_id)
                message.idempotency_key = idem
            self._queued_event(db, run)
            await db.commit()
            thread_id = conversation.id
        return await self.get(org_id, user_id, thread_id)

    async def resume(self, org_id, user_id, thread_id, task, progress=None):
        self.require_enabled()
        if not task.strip() or len(task) > 16000:
            raise ValueError("Task must contain 1–16000 characters")
        async with self.factory() as db:
            await self._lock_org(db, org_id)
            run = await self._latest(db, org_id, user_id, thread_id)
            if run.status == "waiting_for_user":
                await chat_store.submit_clarification(db, org_id=org_id, user_id=user_id, run_id=run.id, message=task)
            elif run.status in {"completed", "failed", "cancelled"}:
                await self._capacity(db, org_id)
                await chat_store.create_run(db, org_id=org_id, user_id=user_id, conversation_id=thread_id, message=task)
            else:
                raise ValueError("Chat is still active. Wait for completion or respond to its question in Chats.")
        return await self.get(org_id, user_id, thread_id)

    async def get(self, org_id, user_id, thread_id, after_sequence=0, run_id=None, detail="summary", sequence=None):
        from .projection import SUMMARY_EVENT_TYPES, summarize_event

        if after_sequence < 0 or (sequence is not None and sequence < 1):
            raise ValueError("Activity cursor must be nonnegative and event sequence positive")
        if detail not in {"summary", "full"}:
            raise ValueError("Detail must be summary or full")
        async with self.factory() as db:
            await self._owned(db, org_id, user_id, thread_id)
            if run_id:
                run = await db.scalar(
                    select(GatewayChatRun).where(
                        GatewayChatRun.id == run_id,
                        GatewayChatRun.conversation_id == thread_id,
                        GatewayChatRun.org_id == org_id,
                        GatewayChatRun.user_id == user_id,
                    )
                )
                if run is None or (run.runtime_env or None) != (runtime_env() or None):
                    raise ValueError("Agent chat run not found in this environment")
            else:
                run = await self._latest(db, org_id, user_id, thread_id)
            if after_sequence > run.last_event_sequence:
                raise ValueError("Activity cursor exceeds the latest event")
            status = (
                "input_required" if run.status in {"waiting_for_user", "waiting_for_query_approval"} else run.status
            )
            terminal_summary = detail == "summary" and sequence is None and status not in {"queued", "running"}
            query = select(GatewayChatRunEvent).where(
                GatewayChatRunEvent.run_id == run.id,
                GatewayChatRunEvent.org_id == org_id,
                GatewayChatRunEvent.user_id == user_id,
                # Keep this page within the captured high-water mark even if
                # another transaction appends events during this read.
                GatewayChatRunEvent.sequence <= run.last_event_sequence,
            )
            if sequence is not None:
                query = query.where(GatewayChatRunEvent.sequence == sequence)
            else:
                query = query.where(GatewayChatRunEvent.sequence > after_sequence)
                if detail == "summary":
                    query = query.where(GatewayChatRunEvent.event_type.in_(SUMMARY_EVENT_TYPES))
            rows = (
                []
                if terminal_summary
                else (await db.scalars(query.order_by(GatewayChatRunEvent.sequence).limit(51))).all()
            )
            if sequence is not None and not rows:
                raise ValueError("Agent event not found")
            events, size, last = [], 0, after_sequence
            for row in rows[:50]:
                event = _event_info(row).model_dump(mode="json")
                if detail == "summary" and sequence is None:
                    event = summarize_event(event)
                cost = len(json.dumps(event))
                if events and size + cost > 12000:
                    break
                events.append(event)
                size += cost
                last = row.sequence
            if terminal_summary or (sequence is None and len(rows) <= 50 and len(events) == len(rows)):
                last = run.last_event_sequence
            result = AgentResult(
                status=status,
                thread_id=thread_id,
                run_id=run.id,
                chat_url=chat_url(thread_id),
                events=events,
                next_sequence=last,
                has_more=sequence is None and last < run.last_event_sequence,
                elapsed_seconds=max(
                    0,
                    int((run.terminal_at.timestamp() if run.terminal_at else time.time()) - run.created_at.timestamp()),
                ),
                error=run.public_error_message,
                error_code=run.public_error_code,
                usage=_token_usage(run.usage_json),
                cost_usd=run.cost_usd,
            )
            if (
                sequence is None
                and status in {"completed", "input_required"}
                and (after_sequence == 0 or after_sequence < run.last_event_sequence)
            ):
                message = await db.scalar(
                    select(GatewayChatMessage)
                    .where(
                        GatewayChatMessage.conversation_id == thread_id,
                        GatewayChatMessage.org_id == org_id,
                        GatewayChatMessage.user_id == user_id,
                        GatewayChatMessage.role == "assistant",
                        GatewayChatMessage.metadata_json["run_id"].as_string() == run.id,
                    )
                    .order_by(GatewayChatMessage.sequence.desc())
                    .limit(1)
                )
                if message:
                    if status == "input_required":
                        result.question = message.content
                    else:
                        result.summary = message.content
            if status == "failed":
                failed = await db.scalar(
                    select(GatewayChatRunEvent)
                    .where(
                        GatewayChatRunEvent.run_id == run.id,
                        GatewayChatRunEvent.org_id == org_id,
                        GatewayChatRunEvent.user_id == user_id,
                        GatewayChatRunEvent.event_type == "error",
                    )
                    .order_by(GatewayChatRunEvent.sequence.desc())
                    .limit(1)
                )
                if failed:
                    for field in (
                        "raw_error",
                        "stderr",
                        "raw_error_truncated",
                        "stderr_truncated",
                        "diagnostic_context",
                        "full_trace",
                        "error_type",
                        "error_stage",
                    ):
                        if field in failed.payload_json:
                            setattr(result, field, failed.payload_json[field])
                if not result.raw_error:
                    result.raw_error = run.public_error_message
            if status in {"queued", "running"}:
                result.next_action = f"Agent is working independently. Share {result.chat_url}. Wait only if the user asks for updates or you need its result; no narration or continued polling is required."
            elif status == "input_required":
                result.next_action = f"Ask the user for the requested clarification or approval. Open {result.chat_url}; approvals are handled in Chats."
            else:
                result.next_action = f"Use the final result. Full events and conversation context are available on explicit request; artifacts are in {result.chat_url}."
            return result

    async def wait(self, org_id, user_id, thread_id, after_sequence=0, run_id=None, wait_seconds=20, detail="summary"):
        if not 0 <= wait_seconds <= 25:
            raise ValueError("Wait duration must be between 0 and 25 seconds")
        deadline = time.monotonic() + wait_seconds
        initial = await self.get(org_id, user_id, thread_id, after_sequence, run_id, detail)
        if initial.status not in {"queued", "running"} or (detail == "full" and initial.events):
            return initial
        while time.monotonic() < deadline:
            await asyncio.sleep(min(0.5, max(0, deadline - time.monotonic())))
            async with self.factory() as db:
                state = (
                    await db.execute(
                        select(GatewayChatRun.status, GatewayChatRun.last_event_sequence).where(
                            GatewayChatRun.id == initial.run_id,
                            GatewayChatRun.org_id == org_id,
                            GatewayChatRun.user_id == user_id,
                            GatewayChatRun.conversation_id == thread_id,
                        )
                    )
                ).one_or_none()
            if state is None or state.status not in {"queued", "running"}:
                break
            if detail == "full" and state.last_event_sequence > initial.next_sequence:
                break
        result = await self.get(org_id, user_id, thread_id, after_sequence, initial.run_id, detail)
        result.heartbeat = not result.events and result.status in {"queued", "running"}
        return result

    async def context(self, org_id, user_id, thread_id, after_message_sequence=0, limit=20):
        from .contracts import AgentContextResult

        if after_message_sequence < 0 or not 1 <= limit <= 50:
            raise ValueError("Message cursor must be nonnegative and limit between 1 and 50")
        async with self.factory() as db:
            await self._latest(db, org_id, user_id, thread_id)
            rows = (
                await db.scalars(
                    select(GatewayChatMessage)
                    .where(
                        GatewayChatMessage.conversation_id == thread_id,
                        GatewayChatMessage.org_id == org_id,
                        GatewayChatMessage.user_id == user_id,
                        GatewayChatMessage.role.in_(["user", "assistant"]),
                        GatewayChatMessage.sequence > after_message_sequence,
                    )
                    .order_by(GatewayChatMessage.sequence)
                    .limit(limit + 1)
                )
            ).all()
            page = rows[:limit]
            return AgentContextResult(
                thread_id=thread_id,
                chat_url=chat_url(thread_id),
                messages=[
                    {
                        "id": row.id,
                        "role": row.role,
                        "content": row.content,
                        "sequence": row.sequence,
                        "created_at": row.created_at,
                        "run_id": (row.metadata_json or {}).get("run_id"),
                    }
                    for row in page
                ],
                next_message_sequence=page[-1].sequence if page else after_message_sequence,
                has_more=len(rows) > limit,
            )

    async def cancel(self, org_id, user_id, thread_id):
        async with self.factory() as db:
            run = await self._latest(db, org_id, user_id, thread_id)
            await chat_store.request_cancellation(db, org_id=org_id, user_id=user_id, run_id=run.id)
        return await self.get(org_id, user_id, thread_id)
