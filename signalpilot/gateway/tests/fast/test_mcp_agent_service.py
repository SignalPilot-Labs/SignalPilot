import asyncio
import os
import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from gateway.agent_execution import artifacts, auth
from gateway.agent_execution.contracts import AgentRequest
from gateway.agent_execution.service import AgentService
from gateway.db.models import MCPAgentEvent, MCPAgentThread

_mint = auth.mint


def test_feature_defaults_enabled_with_runtime_configuration(monkeypatch):
    monkeypatch.delenv("SP_FEATURE_MCP_AGENT", raising=False)
    for name in ("SP_AGENT_IMAGE", "SP_AGENT_DOCKER_NETWORK", "SP_AGENT_MCP_URL", "SP_AGENT_MODEL"):
        monkeypatch.setenv(name, "configured")
    AgentService.require_enabled()


def test_explicit_false_disables_feature(monkeypatch):
    monkeypatch.setenv("SP_FEATURE_MCP_AGENT", "false")
    with pytest.raises(ValueError, match="delegation is disabled"):
        AgentService.require_enabled()


@pytest.mark.parametrize("missing", ["SP_AGENT_IMAGE", "SP_AGENT_DOCKER_NETWORK", "SP_AGENT_MCP_URL", "SP_AGENT_MODEL"])
def test_enabled_default_requires_each_runtime_setting(monkeypatch, missing):
    monkeypatch.delenv("SP_FEATURE_MCP_AGENT", raising=False)
    for name in ("SP_AGENT_IMAGE", "SP_AGENT_DOCKER_NETWORK", "SP_AGENT_MCP_URL", "SP_AGENT_MODEL"):
        monkeypatch.setenv(name, "configured")
    monkeypatch.delenv(missing)
    with pytest.raises(ValueError, match="configuration is incomplete"):
        AgentService.require_enabled()


@pytest_asyncio.fixture
async def service(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(lambda c: MCPAgentThread.__table__.create(c))
        await connection.run_sync(lambda c: MCPAgentEvent.__table__.create(c))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    objects = {"original": artifacts.pack({"models/my_orders.sql": b"select 1\n"})}
    storage = SimpleNamespace()

    async def put(key, data, **kwargs):
        objects[key] = data

    storage.put_bytes = put
    storage.get_bytes = AsyncMock(side_effect=lambda key: objects.get(key))
    storage.presign_get = AsyncMock(side_effect=lambda key, **kwargs: "https://objects.invalid/" + key)
    runtime = SimpleNamespace(
        run=AsyncMock(
            return_value=(
                {"status": "completed", "summary": "Updated model"},
                artifacts.pack({"models/my_orders.sql": b"select 2\n"}),
            )
        )
    )
    instance = AgentService(factory, storage, runtime)
    monkeypatch.setattr(instance, "require_enabled", lambda: None)
    monkeypatch.setattr(instance, "_validate", AsyncMock(return_value="secret"))
    monkeypatch.setattr(
        "gateway.agent_execution.service.WorkspaceStore.build_snapshot", AsyncMock(return_value=(1, "original"))
    )
    monkeypatch.setattr(auth, "mint", lambda *args: "spa_fake")
    monkeypatch.setenv("SP_AGENT_MODEL", "configured-model")
    monkeypatch.setenv("SP_AGENT_MCP_URL", "https://gateway.invalid/mcp")
    yield instance
    await engine.dispose()


def request():
    return AgentRequest(task="Update model", project_id="project", revision=1, connection_name="warehouse")


async def finish(service):
    started = await service.start("org", "owner", request())
    assert await service.run_once()
    return await service.get("org", "owner", started.thread_id)


@pytest.mark.asyncio
async def test_queue_wait_disconnect_and_final_artifacts(service):
    entered, release = asyncio.Event(), asyncio.Event()

    async def run(**kwargs):
        await kwargs["on_event"](
            {"stage": "local_tool", "tool": "Edit", "path": "models/my_orders.sql", "status": "completed"}
        )
        entered.set()
        await release.wait()
        return {"status": "completed", "summary": "done"}, artifacts.pack({"model.sql": b"select 1\n"})

    service.runtime.run = AsyncMock(side_effect=run)
    started = await asyncio.wait_for(service.start("org", "owner", request()), 1)
    assert started.status == "queued"
    service.runtime.run.assert_not_awaited()
    worker = asyncio.create_task(service.run_once())
    try:
        await asyncio.wait_for(entered.wait(), 5)
        activity = await service.wait("org", "owner", started.thread_id, run_id=started.run_id)
        assert activity.status == "running"
        assert activity.events[-1]["path"] == "models/my_orders.sql"
        assert "wait_signalpilot_agent" in activity.next_action
        waiter = asyncio.create_task(
            service.wait("org", "owner", started.thread_id, activity.next_sequence, started.run_id)
        )
        await asyncio.sleep(0.05)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert not worker.done()
        assert (await service.get("org", "owner", started.thread_id)).status == "running"
    finally:
        release.set()
        await worker
    assert (await service.get("org", "owner", started.thread_id)).output


@pytest.mark.asyncio
async def test_continuation_owner_and_cursor_isolation(service):
    first = await finish(service)
    assert first.changed_files == ["models/my_orders.sql"]
    with pytest.raises(ValueError, match="not found"):
        await service.wait("other", "owner", first.thread_id, wait_seconds=0)
    with pytest.raises(ValueError, match="not found"):
        await service.cancel("org", "other", first.thread_id)
    with pytest.raises(ValueError, match="cursor"):
        await service.wait("org", "owner", first.thread_id, 999, wait_seconds=0)
    second = await service.resume("org", "owner", first.thread_id, "Verify again")
    assert second.status == "queued" and second.run_id != first.run_id
    with pytest.raises(ValueError, match="turn changed"):
        await service.wait("org", "owner", first.thread_id, run_id=first.run_id, wait_seconds=0)
    await service.run_once()
    assert service.runtime.run.call_args.kwargs["payload"]["history"][0]["content"] == "Update model"
    assert (await service.get("org", "owner", first.thread_id)).changed_files == []


@pytest.mark.asyncio
async def test_queued_cancel_and_cross_replica_running_cancel(service):
    queued = await service.start("org", "owner", request())
    assert (await service.cancel("org", "owner", queued.thread_id)).status == "cancelled"
    assert not await service.run_once()
    started = await service.start("org", "owner", request())
    entered, release = asyncio.Event(), asyncio.Event()

    async def run(**kwargs):
        entered.set()
        await release.wait()
        assert await kwargs["is_cancelled"]()
        return {"status": "completed", "summary": "late"}, artifacts.pack({"model.sql": b"select 1\n"})

    service.runtime.run = run
    worker = asyncio.create_task(service.run_once())
    await asyncio.wait_for(entered.wait(), 5)
    await AgentService(service.factory, service.storage).cancel("org", "owner", started.thread_id)
    release.set()
    await worker
    final = await service.get("org", "owner", started.thread_id)
    assert final.status == "cancelled" and final.output is None


@pytest.mark.asyncio
async def test_restart_picks_queue_but_never_replays_orphan(service):
    started = await service.start("org", "owner", request())
    replica = AgentService(service.factory, service.storage, service.runtime)
    replica.require_enabled, replica._validate = service.require_enabled, service._validate
    assert await replica.run_once()
    assert (await service.get("org", "owner", started.thread_id)).status == "completed"
    orphan = await service.start("org", "owner", request())
    async with service.factory() as db:
        row = await db.get(MCPAgentThread, orphan.thread_id)
        row.status, row.lease_expires_at = "running", time.time() - 1
        await db.commit()
    assert not await replica.run_once()
    assert (await service.get("org", "owner", orphan.thread_id)).status == "failed"
    assert service.runtime.run.await_count == 1


@pytest.mark.asyncio
async def test_failure_redaction_heartbeat_and_admission(service, monkeypatch):
    monkeypatch.setenv("SP_AGENT_MAX_CONCURRENT_PER_ORG", "1")
    req = request().model_copy(update={"client_request_id": "retry"})
    queued = await service.start("org", "owner", req)
    assert (await service.start("org", "owner", req)).thread_id == queued.thread_id
    with pytest.raises(ValueError, match="concurrency"):
        await service.start("org", "other", request())
    heartbeat = await service.wait("org", "owner", queued.thread_id, wait_seconds=0)
    assert heartbeat.heartbeat and not heartbeat.events
    service.runtime.run.side_effect = RuntimeError("secret")
    await service.run_once()
    failed = await service.get("org", "owner", queued.thread_id)
    assert failed.status == "failed" and "secret" not in failed.model_dump_json()
    async with service.factory() as db:
        row = await db.get(MCPAgentThread, queued.thread_id)
        assert "secret" not in str(row.request)
        row.retained_until = time.time() - 1
        await db.commit()
    with pytest.raises(ValueError, match="retention"):
        await service.get("org", "owner", queued.thread_id)


@pytest.mark.asyncio
async def test_question_history_and_untrusted_runtime_activity(service):
    async def run(**kwargs):
        await kwargs["on_event"]({"type": "query_finished", "tool": "query_database", "sql": "secret"})
        return {
            "status": "input_required",
            "summary": "Need direction",
            "question": "Which date column?",
        }, artifacts.pack({"model.sql": b"select 1\n"})

    service.runtime.run = AsyncMock(side_effect=run)
    first = await finish(service)
    assert first.status == "input_required"
    assert all(event["type"] == "progress" for event in first.events)
    await service.resume("org", "owner", first.thread_id, "created_at")
    await service.run_once()
    assert "Which date column?" in service.runtime.run.call_args.kwargs["payload"]["history"][-1]["content"]


@pytest.mark.asyncio
async def test_cancelled_child_does_not_stop_supervisor_or_siblings(service):
    sibling_started, next_started, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls = 0

    async def child():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise asyncio.CancelledError()
        if calls == 2:
            sibling_started.set()
            await release.wait()
        else:
            next_started.set()
        return True

    service.run_once = child
    supervisor = asyncio.create_task(service.worker_loop())
    try:
        await asyncio.wait_for(sibling_started.wait(), 3)
        await asyncio.wait_for(next_started.wait(), 3)
        assert not supervisor.done() and not release.is_set()
    finally:
        release.set()
        supervisor.cancel()
        with pytest.raises(asyncio.CancelledError):
            await supervisor


@pytest.mark.asyncio
async def test_expired_lease_revokes_signed_token(service, monkeypatch):
    import jwt

    started = await service.start("org", "owner", request())
    monkeypatch.setattr(auth, "get_session_factory", lambda: service.factory)
    monkeypatch.setattr(auth, "load_session_jwt_secret", lambda: "a" * 64)
    async with service.factory() as db:
        row = await db.get(MCPAgentThread, started.thread_id)
        row.status, row.lease_expires_at = "running", time.time() + 45
        await db.commit()
        token = _mint(row, 60)
    assert (await auth.verify(token))["run_id"] == started.run_id
    async with service.factory() as db:
        row = await db.get(MCPAgentThread, started.thread_id)
        row.lease_expires_at = time.time() - 1
        await db.commit()
    with pytest.raises(jwt.InvalidTokenError):
        await auth.verify(token)


@pytest.mark.asyncio
async def test_terminal_event_pages_are_drained(service):
    async def run(**kwargs):
        for _ in range(60):
            await kwargs["on_event"]({"stage": "working"})
        return {"status": "completed", "summary": "done"}, artifacts.pack({"model.sql": b"select 1\n"})

    service.runtime.run = run
    first = await finish(service)
    assert first.status == "completed" and first.has_more and len(first.events) == 50
    assert "remaining activity" in first.next_action
    rest = await service.wait("org", "owner", first.thread_id, first.next_sequence, first.run_id)
    assert not rest.has_more and len(rest.events) == 11


@pytest.mark.asyncio
async def test_dense_sql_pages_preserve_cursor_under_output_budget(service):
    first = await finish(service)
    async with service.factory() as db:
        row = await db.get(MCPAgentThread, first.thread_id)
        for sequence in range(2, 32):
            payload = {"sequence": sequence, "type": "query_started", "sql_preview": "SELECT " + "column_name, " * 95}
            db.add(
                MCPAgentEvent(
                    id=str(uuid.uuid4()),
                    thread_id=row.id,
                    run_id=row.run_id,
                    org_id=row.org_id,
                    sequence=sequence,
                    created_at=time.time(),
                    payload=payload,
                )
            )
        row.event_sequence = 31
        await db.commit()
    import json

    page = await service.wait("org", "owner", first.thread_id, run_id=first.run_id)
    assert page.has_more and len(page.events) < 50
    assert sum(len(json.dumps(item, ensure_ascii=False)) for item in page.events) <= 12000
    seen = [item["sequence"] for item in page.events]
    while page.has_more:
        page = await service.wait("org", "owner", first.thread_id, page.next_sequence, first.run_id)
        seen.extend(item["sequence"] for item in page.events)
    assert seen == list(range(1, 32))


@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("SP_MCP_AGENT_TEST_DB_URL"), reason="isolated PostgreSQL DSN not configured")
async def test_postgres_admission_and_exclusive_claim(service, monkeypatch):
    from sqlalchemy import delete

    engine = create_async_engine(os.environ["SP_MCP_AGENT_TEST_DB_URL"])
    service._factory = async_sessionmaker(engine, expire_on_commit=False)
    org = "mcp-admission-test-" + uuid.uuid4().hex
    monkeypatch.setenv("SP_AGENT_MAX_CONCURRENT_PER_ORG", "1")
    try:
        admissions = await asyncio.gather(
            service.start(org, "owner", request()), service.start(org, "owner", request()), return_exceptions=True
        )
        assert sum(isinstance(value, ValueError) for value in admissions) == 1
        claims = await asyncio.gather(service.run_once(), service.run_once())
        assert sorted(claims) == [False, True]
        assert service.runtime.run.await_count == 1
    finally:
        async with service.factory() as db:
            await db.execute(delete(MCPAgentEvent).where(MCPAgentEvent.org_id == org))
            await db.execute(delete(MCPAgentThread).where(MCPAgentThread.org_id == org))
            await db.commit()
        await engine.dispose()
