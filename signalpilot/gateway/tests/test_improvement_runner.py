"""Improvement runner: seeding, ownership, and execution-payload plumbing."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.db.models import (
    GatewayBase,
    GatewayChatConversation,
    GatewayChatMessage,
    GatewayChatRun,
    GatewayUserSession,
    GatewayWorkspaceProject,
)
from gateway.improvements import runner
from gateway.improvements.runner import seed_improvement_run

ORG = "org_runner_test"
SHA = "a" * 40


@dataclass
class FakeReadiness:
    ready: bool = True
    branch: str | None = "main"
    code: str = "ready"
    message: str = "ok"


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    yield factory
    await engine.dispose()


def _project(org_id: str = ORG) -> GatewayWorkspaceProject:
    return GatewayWorkspaceProject(
        id=str(uuid.uuid4()),
        org_id=org_id,
        name="proj",
        display_name="Proj",
        connection_name="warehouse",
        default_branch="main",
        created_at=time.time(),
        updated_at=time.time(),
    )


@pytest.fixture()
def ready_project(monkeypatch: pytest.MonkeyPatch):
    async def fake_readiness(db, *, org_id, user_id, project, branch_override=None):
        return FakeReadiness()

    monkeypatch.setattr(runner, "evaluate_project_readiness", fake_readiness)
    monkeypatch.setattr(runner, "branch_head_sha", lambda project_id, branch: SHA)


@pytest.mark.asyncio
class TestSeedImprovementRun:
    async def test_seeds_conversation_run_and_message(self, session_factory, ready_project) -> None:
        async with session_factory() as db:
            project = _project()
            db.add(project)
            await db.commit()
            conversation_id, run_id = await seed_improvement_run(db, org_id=ORG, project=project)

        async with session_factory() as db:
            conversation = await db.get(GatewayChatConversation, conversation_id)
            run = await db.get(GatewayChatRun, run_id)
            message = (
                await db.execute(
                    select(GatewayChatMessage).where(GatewayChatMessage.conversation_id == conversation_id)
                )
            ).scalar_one()
        assert conversation.origin == "improvement"
        assert conversation.surface == "standalone"
        assert conversation.commit_sha == SHA
        assert conversation.title.startswith("Cost optimization")
        assert run.status == "queued"
        assert run.project_id == project.id
        assert message.role == "user"
        assert "cost-optimization" in message.content

    async def test_owner_is_most_recent_session_user(self, session_factory, ready_project) -> None:
        async with session_factory() as db:
            project = _project()
            db.add(project)
            db.add(
                GatewayUserSession(
                    id=str(uuid.uuid4()),
                    org_id=ORG,
                    user_id="user-old",
                    project_id="p1",
                    updated_at=time.time() - 1000,
                )
            )
            db.add(
                GatewayUserSession(
                    id=str(uuid.uuid4()),
                    org_id=ORG,
                    user_id="user-recent",
                    project_id="p2",
                    updated_at=time.time(),
                )
            )
            await db.commit()
            conversation_id, _ = await seed_improvement_run(db, org_id=ORG, project=project)
            conversation = await db.get(GatewayChatConversation, conversation_id)
            assert conversation.user_id == "user-recent"

    async def test_owner_falls_back_to_local(self, session_factory, ready_project) -> None:
        async with session_factory() as db:
            project = _project()
            db.add(project)
            await db.commit()
            conversation_id, _ = await seed_improvement_run(db, org_id=ORG, project=project)
            conversation = await db.get(GatewayChatConversation, conversation_id)
            assert conversation.user_id == "local"

    async def test_unready_project_raises(self, session_factory, monkeypatch) -> None:
        async def fake_readiness(db, *, org_id, user_id, project, branch_override=None):
            return FakeReadiness(ready=False, branch=None, code="no_branch", message="not synced")

        monkeypatch.setattr(runner, "evaluate_project_readiness", fake_readiness)
        async with session_factory() as db:
            project = _project()
            db.add(project)
            await db.commit()
            with pytest.raises(RuntimeError, match="not chat-ready"):
                await seed_improvement_run(db, org_id=ORG, project=project)

    async def test_missing_head_commit_raises(self, session_factory, monkeypatch) -> None:
        async def fake_readiness(db, *, org_id, user_id, project, branch_override=None):
            return FakeReadiness()

        monkeypatch.setattr(runner, "evaluate_project_readiness", fake_readiness)
        monkeypatch.setattr(runner, "branch_head_sha", lambda project_id, branch: None)
        async with session_factory() as db:
            project = _project()
            db.add(project)
            await db.commit()
            with pytest.raises(RuntimeError, match="head commit"):
                await seed_improvement_run(db, org_id=ORG, project=project)


# ---------------------------------------------------------------------------
# prepare_execution plumbing for improvement runs
# ---------------------------------------------------------------------------


@dataclass
class FakeRuntime:
    session_id: str = "sess-1"
    internal_base_url: str = "http://notebook:8888"


@pytest_asyncio.fixture
async def seeded_run(session_factory, ready_project):
    async with session_factory() as db:
        project = _project()
        db.add(project)
        await db.commit()
        conversation_id, run_id = await seed_improvement_run(db, org_id=ORG, project=project)
    return session_factory, conversation_id, run_id


@pytest.fixture()
def capture_execution(monkeypatch: pytest.MonkeyPatch):
    from gateway.standalone_chat import execution

    captured: dict = {}

    async def fake_ensure(db, **kwargs):
        return FakeRuntime()

    def fake_mint(**kwargs):
        captured["jwt_kwargs"] = kwargs
        return "jwt-token"

    async def fake_user_key(db, org_id, user_id):
        return None

    monkeypatch.setattr(execution, "ensure_execution_runtime", fake_ensure)
    monkeypatch.setattr(execution, "mint_session_jwt", fake_mint)
    monkeypatch.setattr(execution, "get_user_anthropic_key", fake_user_key)
    return captured


@pytest.mark.asyncio
class TestPrepareExecutionImprovement:
    async def test_improvement_run_gets_sandbox_capability_and_origin(
        self, seeded_run, capture_execution, monkeypatch
    ) -> None:
        from gateway.standalone_chat.execution import prepare_execution

        monkeypatch.setenv("SP_IMPROVEMENT_ANTHROPIC_KEY", "sk-improvement-test")
        factory, conversation_id, run_id = seeded_run
        async with factory() as db:
            run = await db.get(GatewayChatRun, run_id)
            prepared = await prepare_execution(
                db,
                run=run,
                worker_id="w1",
                branch="main",
                connection_name="warehouse",
                commit_sha=SHA,
                prompt="go",
                messages=[{"role": "user", "content": "go"}],
                warm_context={},
            )
        assert prepared.payload["run_origin"] == "improvement"
        assert "sandbox:execute" in capture_execution["jwt_kwargs"]["capabilities"]
        # OAuth-only for now: the improvement credential is always a Claude
        # Code OAuth token, regardless of its prefix.
        assert prepared.payload["runtime_auth"] == {"type": "oauth", "token": "sk-improvement-test"}

    async def test_improvement_oauth_token_uses_oauth_auth(
        self, seeded_run, capture_execution, monkeypatch
    ) -> None:
        from gateway.standalone_chat.execution import prepare_execution

        monkeypatch.setenv("SP_IMPROVEMENT_ANTHROPIC_KEY", "sk-ant-oat01-test-token")
        factory, conversation_id, run_id = seeded_run
        async with factory() as db:
            run = await db.get(GatewayChatRun, run_id)
            prepared = await prepare_execution(
                db,
                run=run,
                worker_id="w1",
                branch="main",
                connection_name="warehouse",
                commit_sha=SHA,
                prompt="go",
                messages=[{"role": "user", "content": "go"}],
                warm_context={},
            )
        assert prepared.payload["runtime_auth"] == {"type": "oauth", "token": "sk-ant-oat01-test-token"}

    async def test_user_run_has_no_sandbox_capability(
        self, session_factory, capture_execution, monkeypatch
    ) -> None:
        from gateway.standalone_chat.execution import prepare_execution
        from gateway.store.standalone_chat import create_conversation_with_run

        monkeypatch.setenv("SP_IMPROVEMENT_ANTHROPIC_KEY", "sk-improvement-test")
        async with session_factory() as db:
            project = _project()
            db.add(project)
            await db.commit()
            conversation, run = await create_conversation_with_run(
                db,
                org_id=ORG,
                user_id="user-1",
                project=project,
                branch="main",
                message="hi",
                commit_sha=SHA,
            )
            prepared = await prepare_execution(
                db,
                run=run,
                worker_id="w1",
                branch="main",
                connection_name="warehouse",
                commit_sha=SHA,
                prompt="hi",
                messages=[{"role": "user", "content": "hi"}],
                warm_context={},
            )
        assert prepared.payload["run_origin"] == "user"
        assert "sandbox:execute" not in capture_execution["jwt_kwargs"]["capabilities"]
        # The improvement billing key must never apply to user runs.
        assert prepared.payload.get("runtime_auth") is None
