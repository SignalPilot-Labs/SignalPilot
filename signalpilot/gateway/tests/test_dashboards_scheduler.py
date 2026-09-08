"""Scheduler: due claims, concurrency, agent-run polling, stale sweeps, settle races."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from gateway.dashboards import refresh as refresh_module
from gateway.dashboards import scheduler, store
from gateway.dashboards.scheduler import poll_agent_refreshes, run_due_dashboard_refreshes
from gateway.db.models import GatewayChatRun
from tests.dashboards_support import db, fake_storage, session_factory
from tests.test_dashboards_refresh import FakeExecutor, _manual_refresh, _published, run_refresh


class TestScheduler:
    async def test_two_concurrent_claims_yield_one_refresh(self, session_factory, db) -> None:
        storage, backend = fake_storage()
        dashboard, _ = await _published(db, storage, backend)
        due = datetime(2026, 9, 8, 6, 0, tzinfo=UTC)
        dashboard.next_refresh_at = due
        await db.commit()
        now = due + timedelta(minutes=1)

        async with session_factory() as a, session_factory() as b:
            seen_a = await store.get_dashboard_by_id(a, dashboard.id)
            seen_b = await store.get_dashboard_by_id(b, dashboard.id)
            first = await scheduler.claim_due_dashboard(a, seen_a, now=now)
            second = await scheduler.claim_due_dashboard(b, seen_b, now=now)
        assert first is not None and second is None
        await db.refresh(dashboard)
        assert store.aware(dashboard.next_refresh_at) == datetime(2026, 9, 9, 6, 0, tzinfo=UTC)
        refreshes = await store.list_refreshes(db, dashboard.id)
        assert [r.trigger for r in refreshes] == ["schedule"]
        assert store.aware(refreshes[0].scheduled_for) == due

    async def test_due_refresh_is_executed(self, session_factory, db) -> None:
        storage, backend = fake_storage()
        dashboard, _ = await _published(db, storage, backend)
        dashboard.next_refresh_at = datetime(2026, 9, 8, 6, 0, tzinfo=UTC)
        await db.commit()
        executed = await run_due_dashboard_refreshes(
            session_factory, now_utc=datetime(2026, 9, 8, 6, 1, tzinfo=UTC), storage=storage, executor=FakeExecutor()
        )
        assert executed == 1
        await db.refresh(dashboard)
        assert dashboard.last_refresh_status == "succeeded"
        assert await run_due_dashboard_refreshes(session_factory, now_utc=datetime(2026, 9, 8, 6, 1, tzinfo=UTC)) == 0

    async def test_in_progress_refresh_is_skipped(self, session_factory, db) -> None:
        storage, backend = fake_storage()
        dashboard, _ = await _published(db, storage, backend)
        active = await _manual_refresh(db, dashboard)
        active.status = "running"
        dashboard.next_refresh_at = datetime(2026, 9, 8, 6, 0, tzinfo=UTC)
        await db.commit()
        assert await run_due_dashboard_refreshes(session_factory, now_utc=datetime(2026, 9, 8, 6, 1, tzinfo=UTC)) == 0
        refreshes = await store.list_refreshes(db, dashboard.id)
        skipped = [r for r in refreshes if r.status == "skipped"]
        assert len(skipped) == 1 and skipped[0].error == scheduler.IN_PROGRESS_ERROR
        await db.refresh(dashboard)
        assert dashboard.last_refresh_status == "skipped"
        assert store.aware(dashboard.next_refresh_at) > datetime(2026, 9, 8, 6, 0, tzinfo=UTC)

    async def test_poll_fails_refresh_whose_run_vanished(self, session_factory, db) -> None:
        storage, backend = fake_storage()
        dashboard, _ = await _published(db, storage, backend)
        refresh = await _manual_refresh(db, dashboard, mode="agent")
        refresh.status = "running"
        refresh.run_id = "gone"
        await db.commit()
        assert (await db.get(GatewayChatRun, "gone")) is None
        assert await poll_agent_refreshes(session_factory, storage=storage) == 1
        await db.refresh(refresh)
        assert refresh.status == "failed"


class TestFinishCommit:
    async def test_success_lands_in_one_commit(self, session_factory, db) -> None:
        """Version row, current_version_id swap, refresh status and last_refresh_* commit together."""
        storage, backend = fake_storage()
        dashboard, _ = await _published(db, storage, backend)
        refresh = await _manual_refresh(db, dashboard)
        commits: list[dict] = []

        class Counting:
            """Session proxy that records what each commit would persist."""

            def __init__(self, session, refresh_row, dashboard_row):
                self.session = session
                self.refresh_row = refresh_row
                self.dashboard_row = dashboard_row

            def __getattr__(self, name):
                return getattr(self.session, name)

            async def commit(self):
                commits.append({"refresh": self.refresh_row.status, "current": self.dashboard_row.current_version_id})
                await self.session.commit()

        async with session_factory() as session:
            refresh_row = await store.get_refresh(session, refresh.id)
            dashboard_row = await store.get_dashboard_by_id(session, dashboard.id)
            version = await store.current_version(session, dashboard_row)
            spec = await storage.get_spec(version.spec_key)
            outcome = await refresh_module.run_sql_datasets(session, storage, FakeExecutor(), dashboard_row, version, spec)
            counting = Counting(session, refresh_row, dashboard_row)
            await refresh_module.finish_refresh(counting, storage, dashboard_row, refresh_row, outcome)
        assert len(commits) == 1
        assert commits[0]["refresh"] == "succeeded"
        assert commits[0]["current"] == refresh_row.version_id
        assert refresh_row.version_id != version.id


class TestStaleRows:
    async def test_stale_running_sql_and_queued_rows_are_failed(self, session_factory, db) -> None:
        storage, backend = fake_storage()
        dashboard, _ = await _published(db, storage, backend)
        now = datetime.now(UTC)
        budget = scheduler.sql_refresh_budget(1)
        stuck = await _manual_refresh(db, dashboard)
        stuck.status = "running"
        stuck.started_at = now - budget - timedelta(seconds=1)
        fresh = await _manual_refresh(db, dashboard)
        fresh.status = "running"
        fresh.started_at = now - budget + timedelta(minutes=1)
        wide = await _manual_refresh(db, dashboard)  # 4 datasets: the budget scales with work
        wide.status = "running"
        wide.detail = {"sql_datasets": 4}
        wide.started_at = now - budget - timedelta(minutes=1)
        assert scheduler.sql_refresh_budget(4) == scheduler.SQL_DATASET_TIMEOUT * 4 + scheduler.STALE_MARGIN
        stuck_finalizing = await _manual_refresh(db, dashboard, mode="agent")
        stuck_finalizing.status = "finalizing"
        stuck_finalizing.started_at = now - timedelta(hours=1)
        stuck_finalizing.detail = {"finalizing_at": (now - scheduler.FINALIZING_REFRESH_TIMEOUT - timedelta(seconds=1)).isoformat()}
        live_finalizing = await _manual_refresh(db, dashboard, mode="agent")
        live_finalizing.status = "finalizing"
        live_finalizing.started_at = now - timedelta(hours=1)
        live_finalizing.detail = {"finalizing_at": (now - timedelta(minutes=1)).isoformat()}
        agent = await _manual_refresh(db, dashboard, mode="agent")
        agent.status = "running"
        agent.started_at = now - timedelta(hours=1)
        agent.run_id = "run-live"
        orphan = await _manual_refresh(db, dashboard)
        orphan.created_at = now - scheduler.QUEUED_REFRESH_TIMEOUT - timedelta(seconds=1)
        waiting = await _manual_refresh(db, dashboard)
        waiting.created_at = now - timedelta(minutes=1)
        await db.commit()

        assert await scheduler.fail_stale_refreshes(session_factory, now_utc=now) == 3

        for row in (stuck, fresh, wide, stuck_finalizing, live_finalizing, agent, orphan, waiting):
            await db.refresh(row)
        assert (stuck.status, stuck.error) == ("failed", scheduler.TIMED_OUT_ERROR)
        assert (orphan.status, orphan.error) == ("failed", scheduler.NEVER_STARTED_ERROR)
        assert (stuck_finalizing.status, stuck_finalizing.error) == ("failed", scheduler.FINALIZE_INCOMPLETE_ERROR)
        assert stuck.finished_at is not None and orphan.finished_at is not None
        assert [row.status for row in (fresh, wide, live_finalizing, agent, waiting)] == [
            "running", "running", "finalizing", "running", "queued",
        ]
        await db.refresh(dashboard)
        assert dashboard.last_refresh_status == "failed"

    async def test_tick_settles_stale_rows(self, session_factory, db) -> None:
        storage, backend = fake_storage()
        dashboard, _ = await _published(db, storage, backend)
        orphan = await _manual_refresh(db, dashboard)
        orphan.created_at = datetime.now(UTC) - timedelta(hours=1)
        await db.commit()
        assert await scheduler.run_dashboard_scheduler_tick(session_factory) == (0, 1)


class TestSettleRace:
    async def test_sweep_failed_refresh_is_not_overwritten_by_a_late_finish(self, session_factory, db) -> None:
        storage, backend = fake_storage()
        dashboard, v1 = await _published(db, storage, backend)
        refresh = await _manual_refresh(db, dashboard)
        refresh.status = "running"
        refresh.started_at = store.utcnow()
        await db.commit()
        async with session_factory() as late:
            refresh_row = await store.get_refresh(late, refresh.id)
            dashboard_row = await store.get_dashboard_by_id(late, dashboard.id)
            version = await store.current_version(late, dashboard_row)
            spec = await storage.get_spec(version.spec_key)
            outcome = await refresh_module.run_sql_datasets(late, storage, FakeExecutor(), dashboard_row, version, spec)
            # The sweep settles the row while the late finisher is still working.
            assert await refresh_module.fail_refresh(db, dashboard, refresh, scheduler.TIMED_OUT_ERROR)
            assert await refresh_module.finish_refresh(late, storage, dashboard_row, refresh_row, outcome) is False
        await db.refresh(refresh)
        await db.refresh(dashboard)
        assert (refresh.status, refresh.error) == ("failed", scheduler.TIMED_OUT_ERROR)
        assert refresh.version_id is None
        assert dashboard.current_version_id == v1.id
        assert len(await store.list_versions(db, dashboard.id)) == 1

    async def test_fail_refresh_does_not_touch_a_settled_row(self, session_factory, db) -> None:
        storage, backend = fake_storage()
        dashboard, _ = await _published(db, storage, backend)
        refresh = await _manual_refresh(db, dashboard)
        await run_refresh(session_factory, refresh.id, storage=storage, executor=FakeExecutor())
        await db.refresh(refresh)
        assert refresh.status == "succeeded"
        assert await refresh_module.fail_refresh(db, dashboard, refresh, "late") is False
        await db.refresh(refresh)
        await db.refresh(dashboard)
        assert refresh.status == "succeeded" and refresh.error is None
        assert dashboard.last_refresh_status == "succeeded"

    async def test_run_refresh_records_the_sql_dataset_count(self, session_factory, db, monkeypatch) -> None:
        storage, backend = fake_storage()
        dashboard, _ = await _published(db, storage, backend)
        refresh = await _manual_refresh(db, dashboard)
        seen: list[dict] = []
        real = refresh_module.run_sql_datasets

        async def spy(db_, *args):
            seen.append(dict((await store.get_refresh(db_, refresh.id)).detail or {}))
            return await real(db_, *args)

        monkeypatch.setattr(refresh_module, "run_sql_datasets", spy)
        await run_refresh(session_factory, refresh.id, storage=storage, executor=FakeExecutor())
        assert seen == [{"sql_datasets": 1}]

    async def test_claim_to_finalizing_stamps_the_time(self, db) -> None:
        storage, backend = fake_storage()
        dashboard, _ = await _published(db, storage, backend)
        refresh = await _manual_refresh(db, dashboard, mode="agent")
        refresh.status = "running"
        await db.commit()
        now = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
        assert await store.claim_refresh_status(
            db, refresh_id=refresh.id, seen="running", new="finalizing", detail={"finalizing_at": now.isoformat()}
        )
        await db.refresh(refresh)
        assert refresh.status == "finalizing"
        assert scheduler.stale_error(refresh, now=now + timedelta(minutes=9)) is None
        assert scheduler.stale_error(refresh, now=now + timedelta(minutes=11)) == scheduler.FINALIZE_INCOMPLETE_ERROR


class TestFinalizingClaim:
    async def test_poll_claims_running_to_finalizing_once(self, session_factory, db, monkeypatch) -> None:
        storage, backend = fake_storage()
        dashboard, _ = await _published(db, storage, backend)
        refresh = await _manual_refresh(db, dashboard, mode="agent")
        refresh.status = "running"
        refresh.run_id = "gone"
        await db.commit()
        real_claim = store.claim_refresh_status

        async def racing_claim(db_, *, refresh_id, seen, new, detail=None):
            # Another replica wins the row between the list and the claim.
            async with session_factory() as other:
                assert await real_claim(other, refresh_id=refresh_id, seen=seen, new=new, detail=detail)
            return await real_claim(db_, refresh_id=refresh_id, seen=seen, new=new, detail=detail)

        monkeypatch.setattr(scheduler.store, "claim_refresh_status", racing_claim)
        assert await poll_agent_refreshes(session_factory, storage=storage) == 0
        await db.refresh(refresh)
        assert refresh.status == "finalizing"
        assert await store.active_refresh(db, dashboard.id) is not None
        # Without the race the poll wins the claim and settles the row.
        monkeypatch.setattr(scheduler.store, "claim_refresh_status", real_claim)
        refresh.status = "running"
        await db.commit()
        assert await poll_agent_refreshes(session_factory, storage=storage) == 1
        await db.refresh(refresh)
        assert refresh.status == "failed" and refresh.error == scheduler.RUN_VANISHED_ERROR

    async def test_finalize_crash_is_written_to_the_claimed_row(self, session_factory, db, monkeypatch) -> None:
        storage, backend = fake_storage()
        dashboard, _ = await _published(db, storage, backend)
        refresh = await _manual_refresh(db, dashboard, mode="agent")
        refresh.status = "running"
        refresh.run_id = "gone"
        await db.commit()
        real_fail = scheduler.fail_refresh
        calls = 0

        async def flaky_fail(db_, dashboard_, refresh_, error, detail=None):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("db hiccup")
            await real_fail(db_, dashboard_, refresh_, error, detail)

        monkeypatch.setattr(scheduler, "fail_refresh", flaky_fail)
        assert await poll_agent_refreshes(session_factory, storage=storage) == 1
        await db.refresh(refresh)
        assert refresh.status == "failed" and "db hiccup" in refresh.error
        assert calls == 2


class TestConcurrentDue:
    async def _due(self, db, storage, backend, count: int):
        rows = []
        for index in range(count):
            dashboard, _ = await _published(db, storage, backend, name=f"Board {index}")
            dashboard.next_refresh_at = datetime(2026, 9, 8, 6, 0, tzinfo=UTC)
            rows.append(dashboard)
        await db.commit()
        return rows

    async def test_due_refreshes_run_concurrently_under_the_semaphore(self, session_factory, db) -> None:
        storage, backend = fake_storage()
        boards = await self._due(db, storage, backend, 5)
        running = 0
        peak = 0

        class Gauge(FakeExecutor):
            async def execute(self, store_, **kwargs):
                nonlocal running, peak
                running += 1
                peak = max(peak, running)
                try:
                    await asyncio.sleep(0.05)
                    return await super().execute(store_, **kwargs)
                finally:
                    running -= 1

        executed = await run_due_dashboard_refreshes(
            session_factory, now_utc=datetime(2026, 9, 8, 6, 1, tzinfo=UTC), storage=storage, executor=Gauge()
        )
        assert executed == 5
        assert 1 < peak <= scheduler.MAX_CONCURRENT_REFRESHES
        for board in boards:
            await db.refresh(board)
        assert {board.last_refresh_status for board in boards} == {"succeeded"}

    async def test_one_crashing_refresh_does_not_stop_the_others(self, session_factory, db, monkeypatch) -> None:
        storage, backend = fake_storage()
        boards = await self._due(db, storage, backend, 3)
        real_run = scheduler.run_refresh

        async def flaky(session_factory_, refresh_id, **kwargs):
            async with session_factory_() as session:
                row = await store.get_refresh(session, refresh_id)
                if row.dashboard_id == boards[1].id:
                    raise RuntimeError("worker lost")
            await real_run(session_factory_, refresh_id, **kwargs)

        monkeypatch.setattr(scheduler, "run_refresh", flaky)
        executed = await run_due_dashboard_refreshes(
            session_factory, now_utc=datetime(2026, 9, 8, 6, 1, tzinfo=UTC), storage=storage, executor=FakeExecutor()
        )
        assert executed == 3
        for board in boards:
            await db.refresh(board)
        assert [board.last_refresh_status for board in boards] == ["succeeded", "failed", "succeeded"]
        failed = (await store.list_refreshes(db, boards[1].id))[0]
        assert failed.status == "failed" and "worker lost" in failed.error
