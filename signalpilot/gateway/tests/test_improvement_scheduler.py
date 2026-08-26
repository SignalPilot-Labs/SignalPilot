"""Automated improvement runs: due-time logic, day-slot uniqueness, scheduling paths.

The due-check works on America/New_York calendar days. The DST cases pin the
2026 US transitions: spring forward on 2026-03-08, fall back on 2026-11-01.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.db.models import (
    GatewayBase,
    GatewayImprovementRun,
    GatewaySetting,
    GatewayWorkspaceProject,
)
from gateway.improvements import runner, scheduler
from gateway.improvements.scheduler import (
    et_date_str,
    improvement_run_due,
    run_due_improvement_runs,
)
from gateway.models.settings import GatewaySettings
from gateway.store.settings import load_settings, save_settings
from gateway.store.standalone_chat import create_conversation_with_run

ORG = "org_improvement_test"


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


class TestEtDateStr:
    def test_utc_evening_is_same_et_day(self) -> None:
        # 2026-08-10 01:00 UTC is still 2026-08-09 21:00 EDT.
        assert et_date_str(_utc(2026, 8, 10, 1, 0)) == "2026-08-09"

    def test_et_daytime_matches_utc_date(self) -> None:
        assert et_date_str(_utc(2026, 8, 10, 15, 0)) == "2026-08-10"

    def test_naive_datetime_is_treated_as_utc(self) -> None:
        assert et_date_str(datetime(2026, 8, 10, 1, 0)) == "2026-08-09"


class TestImprovementRunDue:
    def test_no_previous_run_is_due(self) -> None:
        assert improvement_run_due(_utc(2026, 8, 10, 12, 0), None) is True

    def test_before_midnight_et_not_due(self) -> None:
        # now = Aug 9 23:50 EDT; last run earlier the same ET day.
        now = _utc(2026, 8, 10, 3, 50)
        last = _utc(2026, 8, 9, 14, 0)
        assert improvement_run_due(now, last) is False

    def test_after_midnight_et_due(self) -> None:
        # now = Aug 10 00:10 EDT; last run on the previous ET day.
        now = _utc(2026, 8, 10, 4, 10)
        last = _utc(2026, 8, 9, 14, 0)
        assert improvement_run_due(now, last) is True

    def test_second_call_same_et_day_not_due(self) -> None:
        first_fire = _utc(2026, 8, 10, 4, 10)  # Aug 10 00:10 EDT
        later_same_day = _utc(2026, 8, 10, 23, 0)  # Aug 10 19:00 EDT
        assert improvement_run_due(later_same_day, first_fire) is False

    def test_utc_date_rollover_alone_does_not_make_due(self) -> None:
        # The UTC date has advanced to Aug 10, but ET is still Aug 9.
        now = _utc(2026, 8, 10, 1, 0)  # Aug 9 21:00 EDT
        last = _utc(2026, 8, 9, 12, 0)  # Aug 9 ET
        assert improvement_run_due(now, last) is False

    def test_dst_spring_forward_same_day_not_due(self) -> None:
        # 2026-03-08: 02:00 EST jumps to 03:00 EDT. Last at 01:30 EST,
        # now at 04:00 EDT — same ET calendar day despite the offset change.
        last = _utc(2026, 3, 8, 6, 30)  # 01:30 EST
        now = _utc(2026, 3, 8, 8, 0)  # 04:00 EDT
        assert improvement_run_due(now, last) is False

    def test_dst_spring_forward_next_day_due(self) -> None:
        last = _utc(2026, 3, 8, 8, 0)  # Mar 8, 04:00 EDT
        now = _utc(2026, 3, 9, 5, 0)  # Mar 9, 01:00 EDT
        assert improvement_run_due(now, last) is True

    def test_dst_fall_back_repeated_hour_not_due(self) -> None:
        # 2026-11-01: 02:00 EDT falls back to 01:00 EST. The 01:30 wall time
        # occurs twice; both passes are the same ET calendar day.
        last = _utc(2026, 11, 1, 5, 30)  # 01:30 EDT (first pass)
        now = _utc(2026, 11, 1, 6, 30)  # 01:30 EST (second pass)
        assert improvement_run_due(now, last) is False

    def test_dst_fall_back_next_midnight_due(self) -> None:
        last = _utc(2026, 11, 1, 6, 30)  # Nov 1, 01:30 EST
        now = _utc(2026, 11, 2, 5, 0)  # Nov 2, 00:00 EST exactly
        assert improvement_run_due(now, last) is True


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    yield factory
    await engine.dispose()


async def _enable_org(factory, org_id: str = ORG, *, enabled: bool = True) -> None:
    async with factory() as session:
        session.add(
            GatewaySetting(
                org_id=org_id,
                user_id="user-1",
                settings_json={"improvement_runs_enabled": enabled},
            )
        )
        await session.commit()


async def _add_project(
    factory,
    org_id: str = ORG,
    *,
    name: str | None = None,
    connection_name: str | None = "warehouse",
    updated_at: float | None = None,
    status: str = "active",
) -> GatewayWorkspaceProject:
    project = GatewayWorkspaceProject(
        id=str(uuid.uuid4()),
        org_id=org_id,
        name=name or f"proj-{uuid.uuid4().hex[:8]}",
        display_name="Project",
        connection_name=connection_name,
        status=status,
        created_at=time.time(),
        updated_at=updated_at if updated_at is not None else time.time(),
    )
    async with factory() as session:
        session.add(project)
        await session.commit()
    return project


async def _improvement_rows(factory, org_id: str = ORG) -> list[GatewayImprovementRun]:
    async with factory() as session:
        return list(
            (
                await session.execute(select(GatewayImprovementRun).where(GatewayImprovementRun.org_id == org_id))
            ).scalars()
        )


class TestDaySlotUniqueness:
    async def test_duplicate_org_day_row_is_rejected(self, session_factory) -> None:
        async with session_factory() as session:
            session.add(GatewayImprovementRun(org_id=ORG, started_et_date="2026-08-10", status="seeded"))
            await session.commit()
        async with session_factory() as session:
            session.add(GatewayImprovementRun(org_id=ORG, started_et_date="2026-08-10", status="queued"))
            with pytest.raises(IntegrityError):
                await session.commit()

    async def test_same_day_other_org_is_fine(self, session_factory) -> None:
        async with session_factory() as session:
            session.add(GatewayImprovementRun(org_id=ORG, started_et_date="2026-08-10"))
            session.add(GatewayImprovementRun(org_id="org_other", started_et_date="2026-08-10"))
            await session.commit()


class TestRunDueImprovementRuns:
    async def test_disabled_org_is_not_processed(self, session_factory) -> None:
        await _enable_org(session_factory, enabled=False)
        await _add_project(session_factory)
        assert await run_due_improvement_runs(session_factory) == 0
        assert await _improvement_rows(session_factory) == []

    async def test_org_without_settings_row_is_not_processed(self, session_factory) -> None:
        await _add_project(session_factory)
        assert await run_due_improvement_runs(session_factory) == 0

    async def test_no_eligible_project_records_skip_and_consumes_day(self, session_factory) -> None:
        await _enable_org(session_factory)
        # Projects without a connection or not active are not eligible.
        await _add_project(session_factory, connection_name=None)
        await _add_project(session_factory, connection_name="conn", status="archived")

        assert await run_due_improvement_runs(session_factory) == 1
        rows = await _improvement_rows(session_factory)
        assert len(rows) == 1
        assert rows[0].status == "skipped"
        assert rows[0].project_id is None
        assert "no active project" in rows[0].detail_json["reason"]

        # The day slot is consumed: a second sweep does nothing.
        assert await run_due_improvement_runs(session_factory) == 0
        assert len(await _improvement_rows(session_factory)) == 1

    async def test_seeds_most_recent_connected_project(self, session_factory, monkeypatch: pytest.MonkeyPatch) -> None:
        await _enable_org(session_factory)
        now = time.time()
        await _add_project(session_factory, connection_name="old", updated_at=now - 100)
        target = await _add_project(session_factory, connection_name="new", updated_at=now - 10)
        # Most recently updated overall, but no connection: must be passed over.
        await _add_project(session_factory, connection_name=None, updated_at=now)

        seeded: list[dict] = []

        async def fake_seed(db, *, org_id, project, trigger):
            seeded.append({"org_id": org_id, "project_id": project.id, "trigger": trigger})
            return "conv-1", "run-1"

        monkeypatch.setattr(runner, "seed_improvement_run", fake_seed)

        assert await run_due_improvement_runs(session_factory) == 1
        assert seeded == [{"org_id": ORG, "project_id": target.id, "trigger": "scheduled"}]
        rows = await _improvement_rows(session_factory)
        assert len(rows) == 1
        assert rows[0].status == "seeded"
        assert rows[0].project_id == target.id
        assert rows[0].conversation_id == "conv-1"
        assert rows[0].run_id == "run-1"

        # Same ET day: nothing more to do, and the runner is not called again.
        assert await run_due_improvement_runs(session_factory) == 0
        assert len(seeded) == 1

    async def test_seeding_failure_marks_failed_and_consumes_day(self, session_factory) -> None:
        await _enable_org(session_factory)
        await _add_project(session_factory)

        # The stub runner raises NotImplementedError — the org's failure is
        # recorded, the day slot is consumed, and the loop does not raise.
        assert await run_due_improvement_runs(session_factory) == 1
        rows = await _improvement_rows(session_factory)
        assert len(rows) == 1
        assert rows[0].status == "failed"
        assert "not chat-ready" in rows[0].detail_json["error"]
        assert await run_due_improvement_runs(session_factory) == 0

    async def test_one_org_failure_does_not_break_the_loop(
        self, session_factory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await _enable_org(session_factory, "org_a")
        await _enable_org(session_factory, "org_b")
        await _add_project(session_factory, "org_a")
        await _add_project(session_factory, "org_b")

        async def fake_seed(db, *, org_id, project, trigger):
            if org_id == "org_a":
                raise RuntimeError("boom")
            return "conv-b", "run-b"

        monkeypatch.setattr(runner, "seed_improvement_run", fake_seed)

        assert await run_due_improvement_runs(session_factory) == 2
        (row_a,) = await _improvement_rows(session_factory, "org_a")
        (row_b,) = await _improvement_rows(session_factory, "org_b")
        assert row_a.status == "failed"
        assert row_b.status == "seeded"

    async def test_new_et_day_fires_again(self, session_factory, monkeypatch: pytest.MonkeyPatch) -> None:
        await _enable_org(session_factory)
        await _add_project(session_factory)

        async def fake_seed(db, *, org_id, project, trigger):
            return "conv", "run"

        monkeypatch.setattr(runner, "seed_improvement_run", fake_seed)

        day_one = _utc(2026, 8, 10, 12, 0)
        day_one_late = _utc(2026, 8, 11, 3, 50)  # still Aug 10 ET (23:50 EDT)
        day_two = _utc(2026, 8, 11, 4, 10)  # Aug 11 ET (00:10 EDT)
        assert await run_due_improvement_runs(session_factory, now_utc=day_one) == 1
        assert await run_due_improvement_runs(session_factory, now_utc=day_one_late) == 0
        assert await run_due_improvement_runs(session_factory, now_utc=day_two) == 1
        rows = await _improvement_rows(session_factory)
        assert sorted(row.started_et_date for row in rows) == ["2026-08-10", "2026-08-11"]

    async def test_scheduler_module_imports_without_runner(self) -> None:
        """The runner import is deferred to call time."""
        import importlib

        importlib.reload(scheduler)


class TestSettingsRoundTrip:
    async def test_defaults_to_false(self, session_factory) -> None:
        async with session_factory() as session:
            settings = await load_settings(session, org_id=ORG)
        assert settings.improvement_runs_enabled is False

    async def test_enabled_flag_round_trips(self, session_factory) -> None:
        async with session_factory() as session:
            settings = await load_settings(session, org_id=ORG)
            settings = settings.model_copy(update={"improvement_runs_enabled": True})
            await save_settings(session, org_id=ORG, user_id="user-1", settings=settings)
        async with session_factory() as session:
            reloaded = await load_settings(session, org_id=ORG)
        assert reloaded.improvement_runs_enabled is True
        # The scheduler reads the flag straight from the stored JSON.
        async with session_factory() as session:
            row = (await session.execute(select(GatewaySetting).where(GatewaySetting.org_id == ORG))).scalar_one()
        assert row.settings_json["improvement_runs_enabled"] is True

    def test_pydantic_json_round_trip(self) -> None:
        settings = GatewaySettings(improvement_runs_enabled=True)
        assert GatewaySettings(**settings.model_dump()).improvement_runs_enabled is True


class TestConversationOrigin:
    async def test_create_conversation_with_run_sets_origin(self, session_factory) -> None:
        project = await _add_project(session_factory)
        async with session_factory() as session:
            conversation, run = await create_conversation_with_run(
                session,
                org_id=ORG,
                user_id="user-1",
                project=project,
                branch="main",
                message="improve things",
                origin="improvement",
            )
        assert conversation.origin == "improvement"
        assert run.status == "queued"

    async def test_origin_defaults_to_user(self, session_factory) -> None:
        project = await _add_project(session_factory)
        async with session_factory() as session:
            conversation, _run = await create_conversation_with_run(
                session,
                org_id=ORG,
                user_id="user-1",
                project=project,
                branch="main",
                message="hello",
            )
        assert conversation.origin == "user"
