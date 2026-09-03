"""Unified artifacts index. Hermetic tests over aiosqlite.

Covers the read model (gateway/store/artifacts_index.py) and the
GET /api/artifacts route (gateway/api/artifacts.py): eval listing, org
isolation, provenance, filters, pagination, retention degradation, and the
composed-app route contract. Chat artifacts are conversation files now and
are not part of this index.
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


# Seed helpers


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


# Read model


class TestUnifiedListing:
    @pytest.mark.asyncio
    async def test_lists_eval_artifacts(self, db):
        await seed_eval_artifacts(db, stored=["orders.duckdb", "payments.duckdb"])

        records, total = await list_artifacts(db, org_id=ORG)
        assert total == 2
        assert {r.kind for r in records} == {"eval"}
        names = {r.name for r in records}
        assert names == {"orders.duckdb", "payments.duckdb"}
        for record in records:
            assert record.available is True
            assert record.download["route"].startswith("/api/")

    @pytest.mark.asyncio
    async def test_org_isolation_is_absolute(self, db):
        await seed_eval_artifacts(db, org_id=OTHER_ORG, stored=["secret.duckdb"])
        await seed_eval_artifacts(db, org_id=ORG, stored=["mine.duckdb"])

        records, total = await list_artifacts(db, org_id=ORG)
        assert total == 1
        assert records[0].name == "mine.duckdb"

        # And the other direction: the other org never sees ours.
        other, other_total = await list_artifacts(db, org_id=OTHER_ORG)
        assert other_total == 1
        assert "mine.duckdb" not in {r.name for r in other}

    @pytest.mark.asyncio
    async def test_org_id_is_mandatory(self, db):
        with pytest.raises(ValueError):
            await list_artifacts(db, org_id="")

    @pytest.mark.asyncio
    async def test_provenance_fields_are_populated(self, db):
        eval_run = await seed_eval_artifacts(db, task_id="q7", stored=["t.duckdb"])

        records, _ = await list_artifacts(db, org_id=ORG)
        assert len(records) == 1
        ev = records[0]
        assert ev.kind == "eval"
        assert ev.provenance == {"run_id": eval_run, "task_id": "q7"}
        assert ev.byte_size == 1000
        assert ev.download == {
            "route": f"/api/evals/runs/{eval_run}/artifacts/q7/t.duckdb"
        }
        assert ev.created_at == T0.isoformat()


class TestFilters:
    @pytest.mark.asyncio
    async def test_kind_filter(self, db):
        await seed_eval_artifacts(db)

        ev, ev_total = await list_artifacts(db, org_id=ORG, kind="eval")
        assert ev_total == 1 and ev[0].kind == "eval"

        # Notebook artifacts do not exist yet. The kind is reserved, not invented.
        nb, nb_total = await list_artifacts(db, org_id=ORG, kind="notebook")
        assert (nb, nb_total) == ([], 0)

        # Chat artifacts left the index with the publish tools.
        with pytest.raises(ValueError):
            await list_artifacts(db, org_id=ORG, kind="chat")
        with pytest.raises(ValueError):
            await list_artifacts(db, org_id=ORG, kind="bogus")

    @pytest.mark.asyncio
    async def test_run_filter(self, db):
        eval_run = await seed_eval_artifacts(db, stored=["x.duckdb"])
        await seed_eval_artifacts(db, stored=["y.duckdb"])

        records, total = await list_artifacts(db, org_id=ORG, run_id=eval_run)
        assert total == 1 and records[0].name == "x.duckdb"

    @pytest.mark.asyncio
    async def test_project_filter_excludes_evals(self, db):
        await seed_eval_artifacts(db)  # eval runs carry no workspace project

        records, total = await list_artifacts(db, org_id=ORG, project_id="proj-a")
        assert (records, total) == ([], 0)

    @pytest.mark.asyncio
    async def test_since_filter(self, db):
        old = T0 - timedelta(days=10)
        await seed_eval_artifacts(db, stored=["old.duckdb"], finished_at=old)
        await seed_eval_artifacts(db, stored=["new.duckdb"], finished_at=T0)

        records, total = await list_artifacts(
            db, org_id=ORG, since=T0 - timedelta(days=1)
        )
        assert total == 1
        assert {r.name for r in records} == {"new.duckdb"}


class TestPagination:
    @pytest.mark.asyncio
    async def test_limit_offset_walk_newest_first(self, db):
        for i in range(5):
            await seed_eval_artifacts(
                db, stored=[f"f{i}.duckdb"], finished_at=T0 + timedelta(minutes=i)
            )

        page1, total = await list_artifacts(db, org_id=ORG, limit=2, offset=0)
        page2, total2 = await list_artifacts(db, org_id=ORG, limit=2, offset=2)
        page3, total3 = await list_artifacts(db, org_id=ORG, limit=2, offset=4)
        assert total == total2 == total3 == 5
        walked = [r.name for r in page1 + page2 + page3]
        assert walked == ["f4.duckdb", "f3.duckdb", "f2.duckdb", "f1.duckdb", "f0.duckdb"]
        assert len({r.id for r in page1 + page2 + page3}) == 5


class TestRetentionDegradation:
    @pytest.mark.asyncio
    async def test_pruned_eval_blobs_still_list_with_available_false(self, db):
        """Retention (gateway/evals/retention.py) deletes eval artifact BLOBS
        by S3 prefix and flips GatewayEvalRun.artifacts_pruned. The task rows
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


# App-level route (composed app, scaffold pattern replicated locally)


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
    def test_route_lists_eval_artifacts_with_total(self, api):
        _seed_via(api, lambda s: seed_eval_artifacts(s, stored=["e.duckdb", "f.duckdb"]))

        response = api.get("/api/artifacts")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 2
        assert {a["kind"] for a in body["artifacts"]} == {"eval"}
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
        run_id = _seed_via(api, lambda s: seed_eval_artifacts(s, stored=["a.duckdb"]))
        _seed_via(api, lambda s: seed_eval_artifacts(s, stored=["b.duckdb"]))

        only_eval = api.get("/api/artifacts", params={"kind": "eval"}).json()
        assert only_eval["total"] == 2

        by_run = api.get("/api/artifacts", params={"run_id": run_id}).json()
        assert by_run["total"] == 1
        assert by_run["artifacts"][0]["name"] == "a.duckdb"

        paged = api.get("/api/artifacts", params={"limit": 1, "offset": 0}).json()
        assert paged["total"] == 2 and len(paged["artifacts"]) == 1

        since = api.get(
            "/api/artifacts", params={"since": (T0 + timedelta(days=1)).isoformat()}
        ).json()
        assert since["total"] == 0

    def test_route_rejects_bad_inputs(self, api):
        assert api.get("/api/artifacts", params={"kind": "bogus"}).status_code == 422
        assert api.get("/api/artifacts", params={"kind": "chat"}).status_code == 422
        assert api.get("/api/artifacts", params={"since": "not-a-date"}).status_code == 400
        assert api.get("/api/artifacts", params={"limit": 0}).status_code == 422

    def test_route_never_leaks_other_orgs(self, api):
        _seed_via(
            api,
            lambda s: seed_eval_artifacts(s, org_id=OTHER_ORG, stored=["theirs.duckdb"]),
        )
        body = api.get("/api/artifacts").json()
        assert body == {"artifacts": [], "total": 0}
