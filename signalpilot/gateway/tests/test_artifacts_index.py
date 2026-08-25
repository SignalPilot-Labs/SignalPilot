"""Unified artifacts index — hermetic tests over aiosqlite.

Covers the read model (gateway/store/artifacts_index.py) and the
GET /api/artifacts route (gateway/api/artifacts.py): cross-kind listing,
org isolation, provenance, filters, pagination, retention degradation,
and the composed-app route contract.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from gateway.db.models import (
    GatewayBase,
    GatewayChatArtifact,
    GatewayChatRun,
    GatewayEvalRun,
    GatewayEvalRunTask,
)
from gateway.store.artifacts_index import list_artifacts

ORG = "test-org"
OTHER_ORG = "someone-else"
T0 = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)


def _uid() -> str:
    return str(uuid.uuid4())


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


# ── Seed helpers ─────────────────────────────────────────────────────────────


async def seed_chat_artifact(
    db,
    *,
    org_id: str = ORG,
    project_id: str = "proj-1",
    conversation_id: str | None = None,
    filename: str = "revenue.csv",
    created_at: datetime = T0,
    session_id: str | None = "vs-123",
) -> tuple[str, str]:
    """Insert a chat run + one artifact; returns (run_id, artifact_id)."""
    run = GatewayChatRun(
        id=_uid(),
        org_id=org_id,
        user_id="user-1",
        conversation_id=conversation_id or _uid(),
        project_id=project_id,
        user_message_id=_uid(),
        status="succeeded",
        execution_session_id=session_id,
    )
    artifact = GatewayChatArtifact(
        id=_uid(),
        org_id=org_id,
        user_id="user-1",
        conversation_id=run.conversation_id,
        run_id=run.id,
        kind="table",
        filename=filename,
        mime_type="text/csv",
        snapshot_json={"columns": ["a"], "rows": [[1]]},
        byte_size=42,
        created_at=created_at,
    )
    db.add_all([run, artifact])
    await db.commit()
    return run.id, artifact.id


async def seed_eval_artifacts(
    db,
    *,
    org_id: str = ORG,
    run_id: str | None = None,
    task_id: str = "q1",
    stored: list[str] | None = None,
    finished_at: datetime = T0,
    artifacts_pruned: bool = False,
) -> str:
    """Insert an eval run + one task whose capture_result stored files."""
    run_id = run_id or f"run-{uuid.uuid4().hex[:8]}"
    stored = stored if stored is not None else ["orders.duckdb"]
    tables = {
        name.removesuffix(".duckdb"): {"file": name, "file_bytes": 1000 + i}
        for i, name in enumerate(stored)
    }
    run = GatewayEvalRun(
        id=run_id,
        org_id=org_id,
        status="completed",
        created_at=finished_at.isoformat(),
        artifacts_pruned=artifacts_pruned,
    )
    task = GatewayEvalRunTask(
        id=_uid(),
        run_id=run_id,
        org_id=org_id,
        task_id=task_id,
        status="done",
        finished_at=finished_at.isoformat(),
        capture_result={"mode": "full", "tables": tables, "stored": stored, "bytes": 2048},
    )
    db.add_all([run, task])
    await db.commit()
    return run_id


# ── Read model ───────────────────────────────────────────────────────────────


class TestUnifiedListing:
    @pytest.mark.asyncio
    async def test_lists_across_chat_and_eval_kinds(self, db):
        await seed_chat_artifact(db, filename="chart.csv")
        await seed_eval_artifacts(db, stored=["orders.duckdb", "payments.duckdb"])

        records, total = await list_artifacts(db, org_id=ORG)
        assert total == 3
        assert {r.kind for r in records} == {"chat", "eval"}
        names = {r.name for r in records}
        assert names == {"chart.csv", "orders.duckdb", "payments.duckdb"}
        for record in records:
            assert record.available is True
            assert record.download["route"].startswith("/api/")

    @pytest.mark.asyncio
    async def test_org_isolation_is_absolute(self, db):
        await seed_chat_artifact(db, org_id=OTHER_ORG, filename="secret.csv")
        await seed_eval_artifacts(db, org_id=OTHER_ORG, stored=["secret.duckdb"])
        await seed_chat_artifact(db, org_id=ORG, filename="mine.csv")

        records, total = await list_artifacts(db, org_id=ORG)
        assert total == 1
        assert records[0].name == "mine.csv"

        # And the other direction: the other org never sees ours.
        other, other_total = await list_artifacts(db, org_id=OTHER_ORG)
        assert other_total == 2
        assert "mine.csv" not in {r.name for r in other}

    @pytest.mark.asyncio
    async def test_org_id_is_mandatory(self, db):
        with pytest.raises(ValueError):
            await list_artifacts(db, org_id="")

    @pytest.mark.asyncio
    async def test_provenance_fields_are_populated(self, db):
        conversation = _uid()
        chat_run, artifact_id = await seed_chat_artifact(
            db, conversation_id=conversation, project_id="proj-xyz", session_id="vs-9"
        )
        eval_run = await seed_eval_artifacts(db, task_id="q7", stored=["t.duckdb"])

        records, _ = await list_artifacts(db, org_id=ORG)
        by_kind = {r.kind: r for r in records}

        chat = by_kind["chat"]
        assert chat.id == artifact_id
        assert chat.provenance == {
            "conversation_id": conversation,
            "run_id": chat_run,
            "project_id": "proj-xyz",
            "session_id": "vs-9",
        }
        assert chat.content_type == "text/csv"
        assert chat.byte_size == 42
        assert chat.download == {"route": f"/api/chat/artifacts/{artifact_id}/download"}

        ev = by_kind["eval"]
        assert ev.provenance == {"run_id": eval_run, "task_id": "q7"}
        assert ev.byte_size == 1000
        assert ev.download == {
            "route": f"/api/evals/runs/{eval_run}/artifacts/q7/t.duckdb"
        }
        assert ev.created_at == T0.isoformat()


class TestFilters:
    @pytest.mark.asyncio
    async def test_kind_filter(self, db):
        await seed_chat_artifact(db)
        await seed_eval_artifacts(db)

        chat, chat_total = await list_artifacts(db, org_id=ORG, kind="chat")
        assert chat_total == 1 and chat[0].kind == "chat"

        ev, ev_total = await list_artifacts(db, org_id=ORG, kind="eval")
        assert ev_total == 1 and ev[0].kind == "eval"

        # Notebook artifacts do not exist yet — the kind is reserved, not invented.
        nb, nb_total = await list_artifacts(db, org_id=ORG, kind="notebook")
        assert (nb, nb_total) == ([], 0)

        with pytest.raises(ValueError):
            await list_artifacts(db, org_id=ORG, kind="bogus")

    @pytest.mark.asyncio
    async def test_run_filter_matches_both_kinds(self, db):
        chat_run, _ = await seed_chat_artifact(db, filename="a.csv")
        await seed_chat_artifact(db, filename="b.csv")
        eval_run = await seed_eval_artifacts(db, stored=["x.duckdb"])
        await seed_eval_artifacts(db, stored=["y.duckdb"])

        records, total = await list_artifacts(db, org_id=ORG, run_id=chat_run)
        assert total == 1 and records[0].name == "a.csv"

        records, total = await list_artifacts(db, org_id=ORG, run_id=eval_run)
        assert total == 1 and records[0].name == "x.duckdb"

    @pytest.mark.asyncio
    async def test_project_filter_scopes_chat_and_excludes_evals(self, db):
        await seed_chat_artifact(db, project_id="proj-a", filename="in-a.csv")
        await seed_chat_artifact(db, project_id="proj-b", filename="in-b.csv")
        await seed_eval_artifacts(db)  # eval runs carry no workspace project

        records, total = await list_artifacts(db, org_id=ORG, project_id="proj-a")
        assert total == 1
        assert records[0].name == "in-a.csv"

    @pytest.mark.asyncio
    async def test_since_filter_spans_kinds(self, db):
        old = T0 - timedelta(days=10)
        await seed_chat_artifact(db, filename="old.csv", created_at=old)
        await seed_eval_artifacts(db, stored=["old.duckdb"], finished_at=old)
        await seed_chat_artifact(db, filename="new.csv", created_at=T0)
        await seed_eval_artifacts(db, stored=["new.duckdb"], finished_at=T0)

        records, total = await list_artifacts(
            db, org_id=ORG, since=T0 - timedelta(days=1)
        )
        assert total == 2
        assert {r.name for r in records} == {"new.csv", "new.duckdb"}


class TestPagination:
    @pytest.mark.asyncio
    async def test_limit_offset_walk_newest_first(self, db):
        for i in range(5):
            await seed_chat_artifact(
                db, filename=f"f{i}.csv", created_at=T0 + timedelta(minutes=i)
            )

        page1, total = await list_artifacts(db, org_id=ORG, limit=2, offset=0)
        page2, total2 = await list_artifacts(db, org_id=ORG, limit=2, offset=2)
        page3, total3 = await list_artifacts(db, org_id=ORG, limit=2, offset=4)
        assert total == total2 == total3 == 5
        walked = [r.name for r in page1 + page2 + page3]
        assert walked == ["f4.csv", "f3.csv", "f2.csv", "f1.csv", "f0.csv"]
        assert len({r.id for r in page1 + page2 + page3}) == 5


class TestRetentionDegradation:
    @pytest.mark.asyncio
    async def test_pruned_eval_blobs_still_list_with_available_false(self, db):
        """Retention (gateway/evals/retention.py) deletes eval artifact BLOBS
        by S3 prefix and flips GatewayEvalRun.artifacts_pruned — the task rows
        carrying provenance survive the artifact window. The index therefore
        keeps listing the records, flagged unavailable."""
        pruned_run = await seed_eval_artifacts(
            db, stored=["gone.duckdb"], artifacts_pruned=True
        )
        live_run = await seed_eval_artifacts(db, stored=["here.duckdb"])

        records, total = await list_artifacts(db, org_id=ORG, kind="eval")
        assert total == 2
        by_run = {r.provenance["run_id"]: r for r in records}
        assert by_run[pruned_run].available is False
        assert by_run[pruned_run].name == "gone.duckdb"  # provenance intact
        assert by_run[live_run].available is True


# ── App-level route (composed app, scaffold pattern replicated locally) ─────


def _artifacts_app(factory):
    """A fresh FastAPI app carrying only the unified artifacts surface."""
    from fastapi import FastAPI

    from gateway.api.artifacts import router as artifacts_router
    from gateway.auth import resolve_org_id, resolve_user_id
    from gateway.db.engine import get_db
    from gateway.security.scope_guard import _resolve_user_id as scope_resolve_user_id

    app = FastAPI()
    app.include_router(artifacts_router)

    async def _get_db():
        async with factory() as session:
            yield session

    async def _user() -> str:
        return "test-user"

    async def _org() -> str:
        return ORG

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[resolve_user_id] = _user
    app.dependency_overrides[resolve_org_id] = _org
    app.dependency_overrides[scope_resolve_user_id] = _user
    return app


@pytest.fixture
def api():
    import asyncio

    from fastapi.testclient import TestClient

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    async def _create_all():
        async with engine.begin() as conn:
            await conn.run_sync(GatewayBase.metadata.create_all)

    asyncio.run(_create_all())
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    client = TestClient(_artifacts_app(factory))
    client.factory = factory
    yield client
    asyncio.run(engine.dispose())


def _seed_via(api, coro_fn):
    import asyncio

    async def _run():
        async with api.factory() as session:
            return await coro_fn(session)

    return asyncio.run(_run())


class TestArtifactsRoute:
    def test_route_lists_across_kinds_with_total(self, api):
        _seed_via(api, lambda s: seed_chat_artifact(s, filename="c.csv"))
        _seed_via(api, lambda s: seed_eval_artifacts(s, stored=["e.duckdb"]))

        response = api.get("/api/artifacts")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 2
        assert {a["kind"] for a in body["artifacts"]} == {"chat", "eval"}
        for artifact in body["artifacts"]:
            assert set(artifact) == {
                "id",
                "kind",
                "name",
                "content_type",
                "byte_size",
                "created_at",
                "available",
                "provenance",
                "download",
            }
            assert artifact["download"]["route"].startswith("/api/")

    def test_route_applies_filters_and_pagination(self, api):
        run_id, _ = _seed_via(api, lambda s: seed_chat_artifact(s, filename="a.csv"))
        _seed_via(api, lambda s: seed_eval_artifacts(s, stored=["b.duckdb"]))

        only_chat = api.get("/api/artifacts", params={"kind": "chat"}).json()
        assert only_chat["total"] == 1
        assert only_chat["artifacts"][0]["name"] == "a.csv"

        by_run = api.get("/api/artifacts", params={"run_id": run_id}).json()
        assert by_run["total"] == 1

        paged = api.get("/api/artifacts", params={"limit": 1, "offset": 0}).json()
        assert paged["total"] == 2 and len(paged["artifacts"]) == 1

        since = api.get(
            "/api/artifacts", params={"since": (T0 + timedelta(days=1)).isoformat()}
        ).json()
        assert since["total"] == 0

    def test_route_rejects_bad_inputs(self, api):
        assert api.get("/api/artifacts", params={"kind": "bogus"}).status_code == 422
        assert api.get("/api/artifacts", params={"since": "not-a-date"}).status_code == 400
        assert api.get("/api/artifacts", params={"limit": 0}).status_code == 422

    def test_route_never_leaks_other_orgs(self, api):
        _seed_via(
            api,
            lambda s: seed_chat_artifact(s, org_id=OTHER_ORG, filename="theirs.csv"),
        )
        _seed_via(
            api,
            lambda s: seed_eval_artifacts(s, org_id=OTHER_ORG, stored=["theirs.duckdb"]),
        )
        body = api.get("/api/artifacts").json()
        assert body == {"artifacts": [], "total": 0}
