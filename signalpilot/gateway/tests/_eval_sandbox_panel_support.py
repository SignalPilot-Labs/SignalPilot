"""Shared fixtures and test doubles for the evaluation sandbox panel tests.

Imported by ``test_eval_sandbox_panel.py`` and
``test_eval_sandbox_panel_progress.py`` so both modules share one SQLite
factory, one fake store, and the same real-shaped credentials.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.api.deps import get_store
from gateway.api.eval_runs import router as eval_runs_router
from gateway.config.evals import get_eval_run_settings
from gateway.db.models import GatewayBase
from gateway.evals import runner
from gateway.store import evals as evals_store

STAFF_USER = "user_org_admin"
RUN_A = "run-20260101-010101-aaaaaa"
RUN_B = "run-20260101-020202-bbbbbb"
POD_A = "sp-eval-aaaaaaaaaaaa"
POD_B = "sp-eval-bbbbbbbbbbbb"

# The values that must never appear in any response.
OAUTH_TOKEN = "sk-ant-oat01-" + "supersecrettokenvalue0123456789"
ANTHROPIC_KEY = "sk-ant-api03-" + "anothersupersecretkey0123456789"
MCP_KEY_B64 = base64.b64encode(
    json.dumps(
        {"mcpServers": {"signalpilot": {"headers": {"X-API-Key": "sp-live-secret"}}}},
        separators=(",", ":"),
    ).encode()
).decode()


def _postgres_dsn(authority: str) -> str:
    return "postgresql" + "://" + authority


class FakeStore:
    def __init__(self, org_id: str, user_id: str) -> None:
        self.org_id = org_id
        self.user_id = user_id

    async def get_eval_run(self, run_id: str):
        return None


@pytest.fixture(autouse=True)
def _eval_secrets(monkeypatch: pytest.MonkeyPatch):
    """Real-shaped credentials in settings so redaction is exercised, not assumed."""
    monkeypatch.setenv("SP_EVAL_CLAUDE_TOKEN", OAUTH_TOKEN)
    monkeypatch.setenv("SP_EVAL_ANTHROPIC_KEY", ANTHROPIC_KEY)
    get_eval_run_settings.cache_clear()
    yield
    get_eval_run_settings.cache_clear()


@pytest_asyncio.fixture
async def sqlite_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(GatewayBase.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    await engine.dispose()


@pytest.fixture
def db(sqlite_factory, monkeypatch: pytest.MonkeyPatch):
    """Point every eval-side DB touch at the sqlite factory."""
    import gateway.db.engine as db_engine
    from gateway.evals import notifications, retention

    monkeypatch.setattr(runner, "get_session_factory", lambda: sqlite_factory)
    monkeypatch.setattr(notifications, "get_session_factory", lambda: sqlite_factory)
    monkeypatch.setattr(retention, "get_session_factory", lambda: sqlite_factory)
    monkeypatch.setattr(db_engine, "get_session_factory", lambda: sqlite_factory)
    return sqlite_factory


def _client(org_id: str, user_id: str = STAFF_USER) -> TestClient:
    app = FastAPI()
    app.include_router(eval_runs_router)
    app.dependency_overrides[get_store] = lambda: FakeStore(org_id, user_id)
    return TestClient(app)


async def _seed_run(factory, org_id: str, run_id: str, *, pod: str, task_id: str = "t1:fan/out"):
    async with factory() as session:
        await evals_store.create_run(
            session,
            org_id=org_id,
            run_id=run_id,
            created_at=datetime.now(UTC).isoformat(),
            trigger="manual",
            doc_ids=[],
            doc_titles=[],
            task_filter=None,
            repo_url="https://example.com/set.git",
            model="sonnet",
        )
        await evals_store.seed_tasks(
            session,
            org_id=org_id,
            run_id=run_id,
            tasks=[{"task_id": task_id, "title": f"question for {org_id}"}],
        )
        await evals_store.update_task(
            session,
            org_id=org_id,
            run_id=run_id,
            task_id=task_id,
            status="running",
            sandbox={"backend": "vercel", "name": pod, "namespace": ""},
        )
        await evals_store.update_run(session, org_id=org_id, run_id=run_id, status="running")


def _patch_owners(monkeypatch, owners: dict[str, dict] | None = None) -> None:
    """Replace the asynchronous database-backed sandbox_index with a test double."""

    async def fake_index(org_id: str, limit: int = 25) -> dict:
        return dict(owners or {})

    monkeypatch.setattr(runner, "sandbox_index", fake_index)


# Verify name validation.
