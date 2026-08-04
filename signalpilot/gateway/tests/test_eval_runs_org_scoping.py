"""Verify organization scope for evaluation state and run routes.

Each state query uses an organization identifier. The tests verify the store
and route layers with one in-memory SQLite session.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.api import eval_runs as eval_runs_module
from gateway.api.deps import get_store
from gateway.api.eval_runs import router as eval_runs_router
from gateway.config import get_governance_settings
from gateway.config.evals import get_eval_run_settings
from gateway.db.models import GatewayBase
from gateway.store import Store
from gateway.store import evals as evals_store

RUN_A = "run-20260101-010101-aaaaaa"
RUN_B = "run-20260101-020202-bbbbbb"


@pytest.fixture(autouse=True)
def _settings_cache(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SP_ADMIN_USER_IDS", "u1")
    monkeypatch.setenv("SP_EVAL_ALLOWED_ORGS", "org-a,org-b")
    get_governance_settings.cache_clear()
    get_eval_run_settings.cache_clear()
    yield
    get_governance_settings.cache_clear()
    get_eval_run_settings.cache_clear()


@pytest_asyncio.fixture
async def factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(GatewayBase.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    await engine.dispose()


@pytest_asyncio.fixture
async def session(factory) -> AsyncSession:
    async with factory() as s:
        yield s


async def _seed_run(session, org_id: str, run_id: str) -> None:
    await evals_store.create_run(
        session,
        org_id=org_id,
        run_id=run_id,
        created_at="2026-01-01T00:00:00+00:00",
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
        tasks=[{"task_id": "q1", "title": f"question for {org_id}"}],
    )
    await evals_store.update_run(session, org_id=org_id, run_id=run_id, status="completed")


# Verify organization scope in the storage layer.


class TestStoreOrgScoping:
    async def test_run_state_is_per_org(self, session) -> None:
        await _seed_run(session, "org-a", RUN_A)

        assert await evals_store.get_run(session, org_id="org-a", run_id=RUN_A) is not None
        assert await evals_store.get_run(session, org_id="org-b", run_id=RUN_A) is None
        assert await evals_store.list_runs(session, org_id="org-b") == []
        assert await evals_store.get_tasks(session, org_id="org-b", run_id=RUN_A) == []
        assert await evals_store.run_exists(session, org_id="org-b", run_id=RUN_A) is False

    async def test_listing_only_returns_the_callers_runs(self, session) -> None:
        await _seed_run(session, "org-a", RUN_A)
        await _seed_run(session, "org-b", RUN_B)
        assert [r["id"] for r in await evals_store.list_runs(session, org_id="org-a")] == [RUN_A]
        assert [r["id"] for r in await evals_store.list_runs(session, org_id="org-b")] == [RUN_B]

    async def test_config_is_per_org(self, session) -> None:
        await evals_store.save_config(
            session, org_id="org-a", cfg={"repo_url": "https://example.com/a.git"}
        )
        await evals_store.save_config(
            session, org_id="org-b", cfg={"repo_url": "https://example.com/b.git"}
        )
        assert (await evals_store.get_config(session, org_id="org-a"))["repo_url"].endswith("a.git")
        assert (await evals_store.get_config(session, org_id="org-b"))["repo_url"].endswith("b.git")

    async def test_org_without_config_sees_defaults(self, session) -> None:
        await evals_store.save_config(session, org_id="org-a", cfg={"repo_url": "x"})
        assert (await evals_store.get_config(session, org_id="org-b"))["repo_url"] == ""

    async def test_task_updates_cannot_cross_orgs(self, session) -> None:
        await _seed_run(session, "org-a", RUN_A)
        await evals_store.update_task(
            session, org_id="org-b", run_id=RUN_A, task_id="q1", verdict="CORRECT"
        )
        (task,) = await evals_store.get_tasks(session, org_id="org-a", run_id=RUN_A)
        assert task["verdict"] is None

    async def test_accuracy_and_regressions_are_scoped(self, session) -> None:
        await evals_store.append_accuracy(
            session,
            org_id="org-a",
            entry={
                "run_id": RUN_A,
                "created_at": "2026-01-01T00:00:00+00:00",
                "trigger": "manual",
                "eval_set_name": "s",
                "eval_set_ref": "r",
                "build_fingerprint": "f",
                "tasks_total": 1,
                "tasks_passed": 1,
                "accuracy_pct": 100.0,
                "coverage_pct": None,
                "kb_doc_ids": [],
            },
        )
        assert await evals_store.list_accuracy(session, org_id="org-a") != []
        assert await evals_store.list_accuracy(session, org_id="org-b") == []


# Verify organization scope in the route layer.


class _FakeObjectStore:
    """In-memory stand-in for S3 so transcript routes can be proven scoped."""

    def __init__(self) -> None:
        self.texts: dict[str, str] = {}

    transcript_key = staticmethod(
        lambda org, run, task: f"evals/{org}/runs/{run}/transcripts/{task}.log"
    )
    setup_log_key = staticmethod(
        lambda org, run, task, phase: f"evals/{org}/runs/{run}/setup/{task}-{phase}.log"
    )

    async def get_text(self, key: str) -> str | None:
        return self.texts.get(key)


@pytest.fixture
def fake_obj(monkeypatch: pytest.MonkeyPatch) -> _FakeObjectStore:
    obj = _FakeObjectStore()
    monkeypatch.setattr(eval_runs_module, "get_object_store", lambda: obj)
    return obj


class _RouteStore(Store):
    async def get_connection(self, name: str):
        if name == "eval-warehouse":
            return object()
        return await super().get_connection(name)


def _app(session, org_id: str) -> FastAPI:
    app = FastAPI()
    app.include_router(eval_runs_router)
    app.dependency_overrides[get_store] = lambda: _RouteStore(
        session, org_id=org_id, user_id="u1"
    )
    return app


def _client(session, org_id: str) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=_app(session, org_id)), base_url="http://t")


class TestEvalRouteOrgScoping:
    async def test_config_written_by_one_org_is_invisible_to_another(self, session) -> None:
        async with _client(session, "org-a") as client:
            resp = await client.put(
                "/api/evals/config",
                json={"repo_url": "https://a.example/a.git", "connection": "eval-warehouse"},
            )
            assert resp.status_code == 200
        async with _client(session, "org-b") as client:
            body = (await client.get("/api/evals/config")).json()
        assert body["repo_url"] == ""

    async def test_one_org_cannot_overwrite_anothers_config(self, session) -> None:
        async with _client(session, "org-a") as client:
            await client.put(
                "/api/evals/config",
                json={"repo_url": "https://a.example/a.git", "connection": "eval-warehouse"},
            )
        async with _client(session, "org-b") as client:
            await client.put(
                "/api/evals/config",
                json={"repo_url": "https://b.example/b.git", "connection": "eval-warehouse"},
            )
        async with _client(session, "org-a") as client:
            body = (await client.get("/api/evals/config")).json()
        assert body["repo_url"] == "https://a.example/a.git"

    async def test_run_listing_is_scoped(self, session) -> None:
        await _seed_run(session, "org-a", RUN_A)
        await _seed_run(session, "org-b", RUN_B)
        async with _client(session, "org-a") as client:
            ids = [r["id"] for r in (await client.get("/api/evals/runs")).json()["runs"]]
        assert ids == [RUN_A]

    async def test_foreign_run_detail_is_404(self, session) -> None:
        await _seed_run(session, "org-a", RUN_A)
        async with _client(session, "org-b") as client:
            assert (await client.get(f"/api/evals/runs/{RUN_A}")).status_code == 404
        async with _client(session, "org-a") as client:
            assert (await client.get(f"/api/evals/runs/{RUN_A}")).status_code == 200

    async def test_foreign_run_progress_is_404(self, session) -> None:
        await _seed_run(session, "org-a", RUN_A)
        async with _client(session, "org-b") as client:
            assert (await client.get(f"/api/evals/runs/{RUN_A}/progress")).status_code == 404
        async with _client(session, "org-a") as client:
            assert (await client.get(f"/api/evals/runs/{RUN_A}/progress")).status_code == 200

    async def test_transcript_keys_are_org_prefixed(self, session, fake_obj) -> None:
        """A foreign org asking for the same run/task reads its own (absent)
        key, never org-a's object."""
        await _seed_run(session, "org-a", RUN_A)
        fake_obj.texts[_FakeObjectStore.transcript_key("org-a", RUN_A, "q1")] = "secret-a"

        async with _client(session, "org-b") as client:
            resp = await client.get(f"/api/evals/runs/{RUN_A}/tasks/q1/transcript")
        assert resp.status_code == 404

        async with _client(session, "org-a") as client:
            resp = await client.get(f"/api/evals/runs/{RUN_A}/tasks/q1/transcript")
        assert resp.status_code == 200
        assert resp.text == "secret-a"

    async def test_setup_log_keys_are_org_prefixed(self, session, fake_obj) -> None:
        await _seed_run(session, "org-a", RUN_A)
        fake_obj.texts[_FakeObjectStore.setup_log_key("org-a", RUN_A, "q1", "setup")] = "log-a"

        async with _client(session, "org-b") as client:
            assert (
                await client.get(f"/api/evals/runs/{RUN_A}/tasks/q1/setup/setup/log")
            ).status_code == 404
        async with _client(session, "org-a") as client:
            resp = await client.get(f"/api/evals/runs/{RUN_A}/tasks/q1/setup/setup/log")
        assert resp.status_code == 200
        assert resp.text == "log-a"

    async def test_accuracy_route_is_scoped(self, session) -> None:
        await evals_store.append_accuracy(
            session,
            org_id="org-a",
            entry={
                "run_id": RUN_A,
                "created_at": "2026-01-01T00:00:00+00:00",
                "trigger": "manual",
                "eval_set_name": "s",
                "eval_set_ref": "r",
                "build_fingerprint": "f",
                "tasks_total": 1,
                "tasks_passed": 1,
                "accuracy_pct": 100.0,
                "coverage_pct": None,
                "kb_doc_ids": [],
            },
        )
        async with _client(session, "org-b") as client:
            body = (await client.get("/api/evals/accuracy")).json()
        assert body == {"history": [], "regressions": []}

    async def test_bad_run_id_is_rejected_before_any_lookup(self, session) -> None:
        async with _client(session, "org-a") as client:
            assert (await client.get("/api/evals/runs/not-a-run")).status_code == 400
