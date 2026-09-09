import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from gateway.agent_execution.contracts import AgentLaunchRequest
from gateway.agent_execution.service import AgentService
from gateway.db.models import (
    GatewayChatConversation,
    GatewayChatRun,
    GatewayChatMessage,
    GatewayChatRunEvent,
    GatewayWorkspaceProject,
    GatewayChatUserPreference,
    GatewaySetting,
)
from gateway.store import standalone_chat as chat_store
from gateway.store.standalone_chat.helpers import _stage_run_event


@pytest_asyncio.fixture
async def service(monkeypatch, tmp_path):
    engine = create_async_engine("sqlite+aiosqlite:///" + (tmp_path / "chat-test.db").as_posix())
    async with engine.begin() as connection:
        for model in (
            GatewayChatConversation,
            GatewayChatRun,
            GatewayChatMessage,
            GatewayChatRunEvent,
            GatewayWorkspaceProject,
            GatewayChatUserPreference,
            GatewaySetting,
        ):
            await connection.run_sync(lambda c, model=model: model.__table__.create(c))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    service = AgentService(factory)
    monkeypatch.setenv("SP_FEATURE_STANDALONE_CHAT", "true")
    monkeypatch.setenv("SP_FEATURE_MCP_AGENT", "true")
    monkeypatch.setenv("SP_RUNTIME_ENV", "test")
    monkeypatch.setenv("SP_WEB_URL", "http://localhost:3000")
    monkeypatch.setenv("SP_AGENT_MAX_CONCURRENT_PER_ORG", "2")
    async with factory() as db:
        db.add(
            GatewayWorkspaceProject(
                id="project",
                org_id="org",
                name="my_project",
                display_name="My Project",
                connection_name="warehouse",
                default_branch="main",
                status="active",
                created_at=time.time(),
                updated_at=time.time(),
            )
        )
        await db.commit()

    async def resolve(db, org_id, user_id, request):
        return await db.get(GatewayWorkspaceProject, "project"), "main", "a" * 40

    monkeypatch.setattr(service, "_resolve_request", resolve)
    yield service
    await engine.dispose()


def request(**kwargs):
    return AgentLaunchRequest(task="Inspect my_orders", **kwargs)


async def set_status(service, run_id, status):
    async with service.factory() as db:
        await db.execute(update(GatewayChatRun).where(GatewayChatRun.id == run_id).values(status=status))
        await db.commit()


async def test_launch_uses_real_chat_records_and_immediate_url(service):
    result = await service.start("org", "owner", request())
    assert result.status == "queued"
    assert result.chat_url == f"http://localhost:3000/chats/{result.thread_id}"
    assert result.events[0]["payload"]["chat_url"] == result.chat_url
    async with service.factory() as db:
        chat = await db.get(GatewayChatConversation, result.thread_id)
        run = await db.get(GatewayChatRun, result.run_id)
        assert chat.origin == "mcp_agent" and chat.commit_sha == "a" * 40
        assert run.conversation_id == chat.id and run.runtime_env == "test"
        assert (await db.get(GatewayChatMessage, run.user_message_id)).content == "Inspect my_orders"
        listed = await chat_store.list_conversations(db, org_id="org", user_id="owner")
        assert listed[0].id == chat.id
    assert not hasattr(service, "runtime") and not hasattr(service, "worker_loop")


async def test_account_cap_counts_all_users_environments_and_idempotency(service, monkeypatch):
    first = await service.start("org", "owner", request(client_request_id="retry"))
    await service.start("org", "second", request())
    monkeypatch.setenv("SP_AGENT_MAX_CONCURRENT_PER_ORG", "99")
    with pytest.raises(ValueError, match="concurrency limit"):
        await service.start("org", "third", request())
    repeated = await service.start("org", "owner", request(client_request_id="retry"))
    assert repeated.thread_id == first.thread_id
    monkeypatch.setenv("SP_RUNTIME_ENV", "another")
    with pytest.raises(ValueError, match="concurrency limit"):
        await service.start("org", "third", request())


async def test_continuation_uses_shared_run_and_cap(service):
    first = await service.start("org", "owner", request())
    await set_status(service, first.run_id, "completed")
    await service.start("org", "second", request())
    third = await service.start("org", "third", request())
    with pytest.raises(ValueError, match="concurrency limit"):
        await service.resume("org", "owner", first.thread_id, "Continue")
    await set_status(service, third.run_id, "completed")
    resumed = await service.resume("org", "owner", first.thread_id, "Continue")
    assert resumed.thread_id == first.thread_id and resumed.run_id != first.run_id


async def test_wait_passes_shared_events_and_disconnect_does_not_cancel(service):
    started = await service.start("org", "owner", request())
    waiter = asyncio.create_task(service.wait("org", "owner", started.thread_id, 1, started.run_id, 25))
    await asyncio.sleep(0.01)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    async with service.factory() as db:
        run = await db.get(GatewayChatRun, started.run_id)
        assert run.cancellation_requested_at is None
        _stage_run_event(db, run=run, event_type="tool_started", payload={"tool": "query_database", "sql": "SELECT 1"})
        await db.commit()
    result = await service.wait("org", "owner", started.thread_id, 1, started.run_id, 0)
    assert result.events[0]["payload"] == {"tool": "query_database", "sql": "SELECT 1"}
    assert result.events[0]["run_id"] == started.run_id
    assert "created_at" in result.events[0]


async def test_owner_environment_cursor_guards(service, monkeypatch):
    started = await service.start("org", "owner", request())
    for org, owner in [("other", "owner"), ("org", "other")]:
        with pytest.raises(ValueError, match="not found"):
            await service.get(org, owner, started.thread_id)
    with pytest.raises(ValueError, match="cursor"):
        await service.get("org", "owner", started.thread_id, 999)
    with pytest.raises(ValueError, match="turn changed"):
        await service.get("org", "owner", started.thread_id, run_id="different")
    monkeypatch.setenv("SP_RUNTIME_ENV", "foreign")
    with pytest.raises(ValueError, match="environment"):
        await service.get("org", "owner", started.thread_id)


async def test_failure_uses_shared_error_event(service):
    started = await service.start("org", "owner", request())
    async with service.factory() as db:
        run = await db.get(GatewayChatRun, started.run_id)
        run.status = "failed"
        run.public_error_code = "provider_error"
        run.public_error_message = "Provider rejected model"
        _stage_run_event(
            db,
            run=run,
            event_type="error",
            payload={
                "raw_error": "Original provider failure",
                "stderr": "CLI error",
                "full_trace": "safe trace",
                "diagnostic_context": {"run_id": run.id},
            },
        )
        await db.commit()
    result = await service.get("org", "owner", started.thread_id)
    assert result.raw_error == "Original provider failure" and result.stderr == "CLI error"
    assert result.full_trace == "safe trace" and result.diagnostic_context["run_id"] == result.run_id


async def test_cancel_delegates_shared_store(service, monkeypatch):
    started = await service.start("org", "owner", request())
    cancellation = AsyncMock()
    monkeypatch.setattr(chat_store, "request_cancellation", cancellation)
    await service.cancel("org", "owner", started.thread_id)
    assert cancellation.await_args.kwargs["run_id"] == started.run_id


async def test_browser_followup_and_retry_cannot_bypass_mcp_account_cap(service):
    first = await service.start("org", "owner", request())
    await set_status(service, first.run_id, "failed")
    await service.start("org", "second", request())
    await service.start("org", "third", request())
    async with service.factory() as db:
        with pytest.raises(RuntimeError, match="concurrency limit"):
            await chat_store.create_run(
                db, org_id="org", user_id="owner", conversation_id=first.thread_id, message="Again"
            )
    async with service.factory() as db:
        with pytest.raises(RuntimeError, match="concurrency limit"):
            await chat_store.retry_run(db, org_id="org", user_id="owner", run_id=first.run_id)


def test_default_feature_uses_chats_not_separate_runtime(monkeypatch):
    monkeypatch.delenv("SP_FEATURE_MCP_AGENT", raising=False)
    monkeypatch.setenv("SP_FEATURE_STANDALONE_CHAT", "true")
    AgentService.require_enabled()
    monkeypatch.setenv("SP_FEATURE_STANDALONE_CHAT", "false")
    with pytest.raises(ValueError, match="Chats is not enabled"):
        AgentService.require_enabled()
