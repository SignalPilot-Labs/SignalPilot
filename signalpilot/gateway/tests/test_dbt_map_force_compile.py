"""Manual / settings-triggered compiles always rebuild; superseded attempts
cannot clobber the row of the attempt that replaced them."""

from __future__ import annotations

import time
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from gateway.db.models import GatewayBase, GatewayDbtManifest
from gateway.dbt_map import runner

ORG, PROJECT = "org", "proj"


@pytest.fixture
async def factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(GatewayBase.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    await engine.dispose()


async def _insert(factory, **overrides) -> GatewayDbtManifest:
    now = time.time() - 100
    row = GatewayDbtManifest(
        id=str(uuid.uuid4()), org_id=ORG, project_id=PROJECT, branch="main",
        revision=overrides.pop("revision", 2), status=overrides.pop("status", "success"),
        trigger="push", node_count=7, graph_key="g", manifest_key="m",
        dbt_project_dir="old_dir", created_at=now, updated_at=now, **overrides,
    )
    async with factory() as s:
        s.add(row)
        await s.commit()
    return row


async def _fetch(factory, row_id: str) -> GatewayDbtManifest:
    async with factory() as s:
        return (await s.execute(select(GatewayDbtManifest).where(GatewayDbtManifest.id == row_id))).scalar_one()


@pytest.mark.asyncio
async def test_unforced_claim_skips_a_compiled_revision(factory) -> None:
    row = await _insert(factory)
    async with factory() as s:
        assert await runner._claim(s, ORG, PROJECT, "main", 2, "push") is None
    assert (await _fetch(factory, row.id)).status == "success"


@pytest.mark.asyncio
async def test_forced_claim_rebuilds_a_compiled_revision(factory) -> None:
    row = await _insert(factory)
    async with factory() as s:
        claimed = await runner._claim(s, ORG, PROJECT, "main", 2, "manual", force=True)
    assert claimed is not None and claimed.id == row.id
    fresh = await _fetch(factory, row.id)
    assert fresh.status == "running"
    assert fresh.trigger == "manual"
    assert fresh.phase == "snapshot"
    assert fresh.created_at > row.created_at, "elapsed time restarts for the new attempt"
    # The previous map stays readable until the new one lands.
    assert fresh.graph_key == "g"


@pytest.mark.asyncio
async def test_forced_claim_supersedes_a_live_compile(factory) -> None:
    await _insert(factory, status="running", lease_expires_at=time.time() + 600)
    async with factory() as s:
        assert await runner._claim(s, ORG, PROJECT, "main", 2, "push") is None
        assert await runner._claim(s, ORG, PROJECT, "main", 2, "manual", force=True) is not None


@pytest.mark.asyncio
async def test_superseded_attempt_cannot_finish_the_new_attempt(factory) -> None:
    row = await _insert(factory)
    async with factory() as s:
        first = await runner._claim(s, ORG, PROJECT, "main", 2, "manual", force=True)
        old_attempt = first.created_at
    time.sleep(0.01)
    async with factory() as s:
        second = await runner._claim(s, ORG, PROJECT, "main", 2, "manual", force=True)
        new_attempt = second.created_at
    assert new_attempt > old_attempt

    # The cancelled first attempt tries to record "superseded" and a phase.
    async with factory() as s:
        await runner._set_phase(s, row.id, "dbt", attempt=old_attempt)
        await runner._finish(s, row.id, status="failed", error="superseded by a newer compile", attempt=old_attempt)
    fresh = await _fetch(factory, row.id)
    assert fresh.status == "running" and fresh.error is None and fresh.phase == "snapshot"

    # The live attempt's writes land, and success clears the phase.
    async with factory() as s:
        await runner._set_phase(s, row.id, "dbt", attempt=new_attempt, dbt_project_dir="new_dir")
    assert (await _fetch(factory, row.id)).phase == "dbt"
    async with factory() as s:
        await runner._finish(s, row.id, status="success", attempt=new_attempt, node_count=9)
    fresh = await _fetch(factory, row.id)
    assert (fresh.status, fresh.phase, fresh.node_count, fresh.dbt_project_dir) == ("success", None, 9, "new_dir")


def test_settings_change_forces_recompile(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    import gateway.dbt_map as dbt_map_pkg
    from gateway.api import workspace_projects

    calls: list = []
    monkeypatch.setattr(dbt_map_pkg, "schedule_compile", lambda *a, **k: calls.append((a, k)))
    proj = SimpleNamespace(id="p", default_branch="main", settings={"dbt_project_dir": "b"})
    workspace_projects._recompile_if_dbt_dir_changed("org", proj, {"dbt_project_dir": "a"})
    workspace_projects._recompile_if_dbt_dir_changed("org", proj, {"dbt_project_dir": "b"})
    workspace_projects._recompile_if_dbt_dir_changed("org", proj, None)
    assert [c[1] for c in calls] == [
        {"trigger": "settings", "force": True},
        {"trigger": "settings", "force": True},
    ]
