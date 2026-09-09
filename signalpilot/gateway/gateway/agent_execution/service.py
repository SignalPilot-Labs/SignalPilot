"""Durable, owner-scoped foreground delegation to cloud Docker workers."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
import uuid

from sqlalchemy import func, select, text, update

from gateway.db.engine import get_session_factory
from gateway.db.models import GatewayWorkspaceRevision, MCPAgentThread
from gateway.runtime.mode import runtime_env
from gateway.store import Store, org_secrets
from gateway.workspace_store import WorkspaceStore, workspace_object_storage

from . import artifacts, auth
from .contracts import AgentRequest, AgentResult, RuntimeResult
from .docker import DockerAgent

logger = logging.getLogger(__name__)


class AgentService:
    def __init__(self, factory=None, storage=None, runtime=None):
        self._factory = factory
        self.storage = storage if storage is not None else workspace_object_storage()
        self.runtime = runtime

    @property
    def factory(self):
        return self._factory or get_session_factory()

    @staticmethod
    def require_enabled():
        if os.getenv("SP_FEATURE_MCP_AGENT", "true").lower() not in {"1", "true"}:
            raise ValueError("Cloud agent delegation is disabled")
        for key in ("SP_AGENT_IMAGE", "SP_AGENT_DOCKER_NETWORK", "SP_AGENT_MCP_URL", "SP_AGENT_MODEL"):
            if not os.getenv(key):
                raise ValueError("Cloud agent configuration is incomplete")

    async def _owned(self, db, org_id, user_id, thread_id):
        row = await db.scalar(
            select(MCPAgentThread).where(
                MCPAgentThread.id == thread_id, MCPAgentThread.org_id == org_id, MCPAgentThread.user_id == user_id,
                MCPAgentThread.runtime_env == runtime_env(),
            )
        )
        if row is None:
            raise ValueError("Agent thread not found")
        if row.retained_until <= time.time():
            raise ValueError("Agent thread retention expired; start a new thread")
        if row.status in {"queued", "running"} and (
            row.expires_at <= time.time() or (row.status == "running" and row.lease_expires_at <= time.time())
        ):
            await db.execute(
                update(MCPAgentThread)
                .where(
                    MCPAgentThread.id == row.id,
                    MCPAgentThread.run_id == row.run_id,
                    MCPAgentThread.status == row.status,
                    (
                        (MCPAgentThread.expires_at <= time.time())
                        | ((MCPAgentThread.status == "running") & (MCPAgentThread.lease_expires_at <= time.time()))
                    ),
                )
                .values(status="failed", result={"error": "Agent deadline exceeded"}, updated_at=time.time())
            )
            await db.commit()
            await db.refresh(row)
        return row

    async def _validate(self, db, org_id, user_id, request, resolve_key=True):
        store = Store(db, org_id=org_id, user_id=user_id)
        project = await store.get_workspace_project(request.project_id)
        if project is None or project.status != "active":
            raise ValueError("Active workspace project not found")
        if await store.get_connection(request.connection_name) is None:
            raise ValueError("Connection not found")
        if not resolve_key:
            revision = await db.scalar(
                select(GatewayWorkspaceRevision.id).where(
                    GatewayWorkspaceRevision.org_id == org_id,
                    GatewayWorkspaceRevision.project_id == request.project_id,
                    GatewayWorkspaceRevision.branch == request.branch,
                    GatewayWorkspaceRevision.revision == request.revision,
                )
            )
            if revision is None:
                raise ValueError("Workspace revision not found")
            return None
        key = await org_secrets.resolve_anthropic_key(db, org_id)
        if not key:
            raise ValueError("Configure an organization Anthropic API key")
        return key

    async def _lock_org(self, db, org_id):
        # All start/resume admissions serialize across gateway replicas. Never
        # hold this lock while a container runs.
        dialect = db.bind.dialect.name
        if dialect == "postgresql":
            lock_id = int.from_bytes(hashlib.sha256(("mcp-agent:" + org_id).encode()).digest()[:8], "big", signed=True)
            await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_id})
        elif dialect == "sqlite":
            await db.execute(text("BEGIN IMMEDIATE"))
        else:
            raise ValueError("Agent admission requires PostgreSQL")

    async def _capacity(self, db, org_id):
        maximum = min(20, max(1, int(os.getenv("SP_AGENT_MAX_CONCURRENT_PER_ORG", "2"))))
        active = await db.scalar(
            select(func.count())
            .select_from(MCPAgentThread)
            .where(
                MCPAgentThread.org_id == org_id,
                MCPAgentThread.runtime_env == runtime_env(),
                MCPAgentThread.status.in_(["queued", "running"]),
                MCPAgentThread.expires_at > time.time(),
            )
        )
        if active >= maximum:
            raise ValueError("Organization agent concurrency limit reached")

    async def start(self, org_id, user_id, request: AgentRequest, progress=None):
        self.require_enabled()
        async with self.factory() as db:
            await self._lock_org(db, org_id)
            if request.client_request_id:
                existing = await db.scalar(
                    select(MCPAgentThread).where(
                        MCPAgentThread.org_id == org_id,
                        MCPAgentThread.user_id == user_id,
                        MCPAgentThread.client_request_id == request.client_request_id,
                    )
                )
                if existing:
                    existing_id = existing.id
                    await db.rollback()
                    return await self.get(org_id, user_id, existing_id)
            await self._capacity(db, org_id)
            await self._validate(db, org_id, user_id, request, resolve_key=False)
            now = time.time()
            row = MCPAgentThread(
                id=str(uuid.uuid4()),
                org_id=org_id,
                user_id=user_id,
                runtime_env=runtime_env(),
                run_id=str(uuid.uuid4()),
                status="queued",
                expires_at=now + 300,
                lease_expires_at=0,
                enqueued_at=now,
                event_sequence=0,
                retained_until=now + 7 * 86400,
                client_request_id=request.client_request_id,
                updated_at=now,
                attempt=1,
                request=request.model_dump(),
                history=[],
                result={},
                snapshot_key="",
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)
        return await self.get(org_id, user_id, row.id)

    async def resume(self, org_id, user_id, thread_id, task, progress=None):
        self.require_enabled()
        if not task.strip() or len(task) > 16000:
            raise ValueError("Task must contain 1–16000 characters")
        async with self.factory() as db:
            await self._lock_org(db, org_id)
            row = await self._owned(db, org_id, user_id, thread_id)
            if row.status not in {"completed", "input_required"}:
                raise ValueError("Only completed or input-required threads can continue")
            if row.attempt >= 12:
                raise ValueError("Thread continuation limit reached; start a new thread")
            request = AgentRequest.model_validate({**row.request, "task": task})
            await self._capacity(db, org_id)
            await self._validate(db, org_id, user_id, request, resolve_key=False)
            run_id = str(uuid.uuid4())
            claimed = await db.execute(
                update(MCPAgentThread)
                .where(
                    MCPAgentThread.id == row.id,
                    MCPAgentThread.run_id == row.run_id,
                    MCPAgentThread.status == row.status,
                )
                .values(
                    run_id=run_id,
                    status="queued",
                    request=request.model_dump(),
                    result={},
                    attempt=row.attempt + 1,
                    expires_at=time.time() + 300,
                    lease_expires_at=0,
                    event_sequence=0,
                    enqueued_at=time.time(),
                    updated_at=time.time(),
                )
            )
            if claimed.rowcount != 1:
                raise ValueError("Thread was already continued; fetch its latest status")
            await db.commit()
            await db.refresh(row)
        return await self.get(org_id, user_id, row.id)

    async def get(self, org_id, user_id, thread_id, after_sequence=0, run_id=None):
        async with self.factory() as db:
            row = await self._owned(db, org_id, user_id, thread_id)
            if run_id is not None and run_id != row.run_id:
                raise ValueError("Agent turn changed; get latest state and restart the cursor")
            result = AgentResult(
                status=row.status,
                thread_id=row.id,
                run_id=row.run_id,
                **{k: v for k, v in row.result.items() if k != "artifact_prefix"},
            )
            prefix = row.result.get("artifact_prefix")
            from .events import read_events

            if after_sequence > row.event_sequence:
                raise ValueError("Event cursor is ahead of this agent turn")
            result.events = await read_events(db, org_id, row.id, row.run_id, after_sequence, limit=50)
            bounded, size = [], 0
            for item in result.events:
                item_size = len(json.dumps(item, ensure_ascii=False))
                if bounded and size + item_size > 12000:
                    break
                bounded.append(item)
                size += item_size
            result.events = bounded
            result.next_sequence = result.events[-1]["sequence"] if result.events else after_sequence
            result.has_more = row.event_sequence > result.next_sequence
            result.elapsed_seconds = max(0, int(time.time() - row.enqueued_at))
            result.next_action = (
                "Show the user meaningful new activity and evidence from events, including redacted SQL. "
                "Then call wait_signalpilot_agent with thread_id, run_id and after_sequence=next_sequence. "
                "Continue until terminal status; do not ask the user to poll."
                if row.status in {"queued", "running"}
                else "Ask the user the question, then continue_signalpilot_agent with their answer."
                if row.status == "input_required"
                else "Report the outcome and verification to the user, including available artifact links."
            )
            if result.has_more:
                result.next_action = (
                    "Show meaningful new evidence, then call wait_signalpilot_agent with the same "
                    "thread_id and run_id and after_sequence=next_sequence to read remaining activity before reporting the outcome."
                )
            if prefix:
                ttl = max(1, min(600, int(row.retained_until - time.time())))
                result.output = {
                    "patch_url": await self.storage.presign_get(prefix + "/changes.patch", expires_seconds=ttl),
                    "snapshot_url": await self.storage.presign_get(prefix + "/output.tgz", expires_seconds=ttl),
                    "expires_in_seconds": ttl,
                }
            return result

    async def cancel(self, org_id, user_id, thread_id):
        async with self.factory() as db:
            row = await self._owned(db, org_id, user_id, thread_id)
            await db.execute(
                update(MCPAgentThread)
                .where(
                    MCPAgentThread.id == row.id,
                    MCPAgentThread.run_id == row.run_id,
                    MCPAgentThread.status.in_(["queued", "running"]),
                )
                .values(status="cancelled", updated_at=time.time(), result={})
            )
            await db.commit()
        return await self.get(org_id, user_id, thread_id)

    async def wait(self, org_id, user_id, thread_id, after_sequence=0, run_id=None, wait_seconds=20):
        if not isinstance(after_sequence, int) or after_sequence < 0 or not 0 <= wait_seconds <= 25:
            raise ValueError("Invalid cursor or wait duration; use 0–25 seconds")
        deadline = time.monotonic() + wait_seconds
        while True:
            result = await self.get(org_id, user_id, thread_id, after_sequence, run_id)
            if result.events or result.status not in {"queued", "running"}:
                return result
            if time.monotonic() >= deadline:
                result.heartbeat = True
                return result
            await asyncio.sleep(min(0.25, max(0, deadline - time.monotonic())))

    async def run_once(self):
        """Claim one queued turn atomically. Never replay an orphaned running turn."""
        self.require_enabled()
        async with self.factory() as db:
            await db.execute(
                update(MCPAgentThread)
                .where(
                    MCPAgentThread.status.in_(["queued", "running"]),
                    MCPAgentThread.runtime_env == runtime_env(),
                    (
                        (MCPAgentThread.expires_at <= time.time())
                        | (MCPAgentThread.retained_until <= time.time())
                        | ((MCPAgentThread.status == "running") & (MCPAgentThread.lease_expires_at <= time.time()))
                    ),
                )
                .values(
                    status="failed",
                    result={"error": "Worker lease or deadline expired; start a new turn"},
                    updated_at=time.time(),
                )
            )
            candidate = await db.scalar(
                select(MCPAgentThread)
                .where(
                    MCPAgentThread.status == "queued",
                    MCPAgentThread.runtime_env == runtime_env(),
                    MCPAgentThread.expires_at > time.time(),
                    MCPAgentThread.retained_until > time.time(),
                )
                .order_by(MCPAgentThread.enqueued_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if candidate is None:
                await db.commit()
                return False
            claimed = await db.execute(
                update(MCPAgentThread)
                .where(
                    MCPAgentThread.id == candidate.id,
                    MCPAgentThread.run_id == candidate.run_id,
                    MCPAgentThread.status == "queued",
                )
                .values(
                    status="running",
                    lease_expires_at=time.time() + 45,
                    expires_at=min(time.time() + candidate.request["timeout_seconds"], candidate.retained_until),
                    updated_at=time.time(),
                )
            )
            if claimed.rowcount != 1:
                await db.rollback()
                return False
            await db.commit()
            await db.refresh(candidate)
        await self._execute(candidate)
        return True

    async def worker_loop(self):
        tasks = set()
        try:
            while True:
                try:
                    self.require_enabled()
                    for task in list(tasks):
                        if task.done():
                            tasks.remove(task)
                            if task.cancelled():
                                continue
                            try:
                                task.result()
                            except Exception as exc:
                                logger.warning("Agent worker failed type=%s", type(exc).__name__)
                    if len(tasks) < 4:
                        tasks.add(asyncio.create_task(self.run_once()))
                except ValueError:
                    pass  # An unconfigured runtime leaves the rest of the gateway available.
                await asyncio.sleep(0.5)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute(self, row):
        request = AgentRequest.model_validate(row.request)
        owner_task = asyncio.current_task()

        async def renew():
            while True:
                await asyncio.sleep(10)
                async with self.factory() as db:
                    renewed = await db.execute(
                        update(MCPAgentThread)
                        .where(
                            MCPAgentThread.id == row.id,
                            MCPAgentThread.run_id == row.run_id,
                            MCPAgentThread.status == "running",
                            MCPAgentThread.lease_expires_at > time.time(),
                        )
                        .values(lease_expires_at=time.time() + 45)
                    )
                    await db.commit()
                    if renewed.rowcount != 1:
                        owner_task.cancel()
                        return

        heartbeat = asyncio.create_task(renew())

        async def cancelled():
            async with self.factory() as db:
                active = await db.scalar(
                    select(MCPAgentThread.id).where(
                        MCPAgentThread.id == row.id,
                        MCPAgentThread.run_id == row.run_id,
                        MCPAgentThread.status == "running",
                        MCPAgentThread.expires_at > time.time(),
                        MCPAgentThread.lease_expires_at > time.time(),
                    )
                )
                return active is None

        async def event(raw):
            from .events import append_event

            await append_event(self.factory, row.id, row.run_id, row.org_id, {**raw, "type": "progress"})

        try:
            async with asyncio.timeout(max(1, row.expires_at - time.time())):
                async with self.factory() as db:
                    key = await self._validate(db, row.org_id, row.user_id, request)
                    if not row.snapshot_key:
                        _, row.snapshot_key = await WorkspaceStore(self.storage).build_snapshot(
                            db,
                            org_id=row.org_id,
                            project_id=request.project_id,
                            branch=request.branch,
                            revision=request.revision,
                        )
                    await db.commit()
                before_bytes = await self.storage.get_bytes(row.snapshot_key)
                if before_bytes is None:
                    raise ValueError("Project snapshot unavailable")
                before = artifacts.read_archive(before_bytes)
                # Repack a sanitized input to prevent project credentials entering the worker.
                prefix = (
                    "mcp-agents/"
                    + hashlib.sha256(row.org_id.encode()).hexdigest()[:24]
                    + "/"
                    + row.id
                    + "/"
                    + row.run_id
                )
                await self.storage.put_bytes(prefix + "/input.tgz", artifacts.pack(before))
                payload = {
                    **request.model_dump(),
                    "api_key": key,
                    "mcp_token": auth.mint(row, request.timeout_seconds),
                    "mcp_url": os.environ["SP_AGENT_MCP_URL"],
                    "model": os.environ["SP_AGENT_MODEL"],
                    "snapshot_url": await self.storage.presign_get(
                        prefix + "/input.tgz", expires_seconds=request.timeout_seconds
                    ),
                    "history": row.history,
                }
                from gateway.mcp.audit import AGENT_ALLOWED_MCP_TOOLS

                payload["allowed_mcp_tools"] = sorted(AGENT_ALLOWED_MCP_TOOLS)
                await event({"stage": "starting"})
                runtime = self.runtime or DockerAgent()
                if await cancelled():
                    raise asyncio.CancelledError()
                raw, output = await runtime.run(
                    run_id=row.run_id, payload=payload, on_event=event, is_cancelled=cancelled
                )
                outcome = RuntimeResult.model_validate(raw)
                after = artifacts.read_archive(output)
                secrets = (key, payload["mcp_token"])
                if any(secret.encode() in data for secret in secrets for data in after.values()):
                    raise ValueError("Agent output contains execution credentials")
                for secret in secrets:
                    outcome.summary = outcome.summary.replace(secret, "[REDACTED]")
                    if outcome.question:
                        outcome.question = outcome.question.replace(secret, "[REDACTED]")
                    outcome.verification = [text.replace(secret, "[REDACTED]") for text in outcome.verification]
                changed, patch = artifacts.patch(before, after)
                await self.storage.put_bytes(prefix + "/output.tgz", artifacts.pack(after))
                await self.storage.put_bytes(prefix + "/changes.patch", patch, content_type="text/plain")
                result = outcome.model_dump(exclude={"status"}) | {"changed_files": changed, "artifact_prefix": prefix}
                history = (
                    [
                        *row.history,
                        {"role": "user", "content": request.task},
                        {
                            "role": "assistant",
                            "content": outcome.summary
                            + ("\nQuestion: " + outcome.question if outcome.question else ""),
                        },
                    ]
                )[-12:]
                async with self.factory() as db:
                    await db.execute(
                        update(MCPAgentThread)
                        .where(
                            MCPAgentThread.id == row.id,
                            MCPAgentThread.run_id == row.run_id,
                            MCPAgentThread.status == "running",
                            MCPAgentThread.expires_at > time.time(),
                            MCPAgentThread.lease_expires_at > time.time(),
                        )
                        .values(
                            status=outcome.status,
                            result=result,
                            history=history,
                            snapshot_key=prefix + "/output.tgz",
                            updated_at=time.time(),
                        )
                    )
                    await db.commit()
        except asyncio.CancelledError:

            async def persist_cancel():
                async with self.factory() as db:
                    await db.execute(
                        update(MCPAgentThread)
                        .where(
                            MCPAgentThread.id == row.id,
                            MCPAgentThread.run_id == row.run_id,
                            MCPAgentThread.status == "running",
                        )
                        .values(
                            status="failed",
                            result={"error": "Worker stopped; start a new turn"},
                            updated_at=time.time(),
                        )
                    )
                    await db.commit()

            await asyncio.shield(persist_cancel())
            raise
        except Exception as exc:
            logger.warning("Agent execution failed run=%s type=%s", row.run_id, type(exc).__name__)
            async with self.factory() as db:
                await db.execute(
                    update(MCPAgentThread)
                    .where(
                        MCPAgentThread.id == row.id,
                        MCPAgentThread.run_id == row.run_id,
                        MCPAgentThread.status == "running",
                    )
                    .values(status="failed", result={"error": "Agent execution failed"}, updated_at=time.time())
                )
                await db.commit()
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
