"""Refresh execution: sql mode with a fake executor, agent-mode finalize, crash path.

Scheduler claims, sweeps, and races live in test_dashboards_scheduler.py."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from gateway.dashboards import refresh as refresh_module
from gateway.dashboards import scheduler, service, store
from gateway.dashboards.refresh import finalize_agent_refresh, run_refresh
from gateway.dashboards.scheduler import poll_agent_refreshes, run_due_dashboard_refreshes
from gateway.dashboards.serializers import RefreshSettingsIn
from gateway.dashboards.storage import DashboardStorage
from gateway.db.models import GatewayChatRun
from gateway.db.models.dashboards import new_refresh_id
from gateway.governance.query_executor import GovernedQueryError
from gateway.store import standalone_chat as chat_store
from tests.dashboards_support import (
    ORG,
    USER,
    add_conversation_with_files,
    db,
    fake_manifest,
    fake_storage,
    publish_body,
    session_factory,
    spec_json,
)


class FakeExecutor:
    def __init__(self, rows=None, *, error: Exception | None = None, delay: float = 0.0) -> None:
        self.rows = rows if rows is not None else [{"month": "2026-03-01", "revenue": 130}]
        self.error = error
        self.delay = delay
        self.calls: list[dict] = []

    async def execute(self, store_, **kwargs):
        self.calls.append(kwargs)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        columns = [{"name": key} for key in self.rows[0]] if self.rows else []
        return SimpleNamespace(rows=list(self.rows), columns=columns)


async def _published(db, storage, backend, **overrides):
    rows = fake_manifest(backend)
    return await service.publish(
        db, storage, org_id=ORG, user_id=USER, is_admin=False, conversation_id="conv-1",
        file_row=rows[0], manifest=rows, body=publish_body(**overrides), project_id="project-a",
    )


async def _manual_refresh(db, dashboard, mode="sql"):
    return await store.create_refresh(db, dashboard=dashboard, refresh_id=new_refresh_id(), mode=mode, trigger="manual")


class TestSqlRefresh:
    async def test_success_writes_version_and_swaps(self, session_factory, db) -> None:
        storage, backend = fake_storage()
        dashboard, v1 = await _published(db, storage, backend)
        refresh = await _manual_refresh(db, dashboard)
        executor = FakeExecutor()

        await run_refresh(session_factory, refresh.id, storage=storage, executor=executor)

        await db.refresh(refresh)
        await db.refresh(dashboard)
        assert refresh.status == "succeeded"
        assert refresh.started_at is not None and refresh.finished_at is not None
        v2 = await store.get_version(db, dashboard_id=dashboard.id, version_id=refresh.version_id)
        assert v2.version_no == 2 and v2.produced_by == "refresh" and v2.producer_ref == refresh.id
        assert dashboard.current_version_id == v2.id
        assert dashboard.last_refresh_status == "succeeded"
        assert backend.objects[v2.dataset_keys["monthly"]] == b"month,revenue\n2026-03-01,130\n"
        assert v2.dataset_keys["regions"] == v1.dataset_keys["regions"]  # carried by reference
        assert v2.dataset_meta["monthly"]["row_count"] == 1
        assert refresh.detail["datasets"]["monthly"] == {"status": "refreshed", "row_count": 1}
        assert refresh.detail["datasets"]["regions"]["status"] == "carried"
        assert refresh.detail["datasets"]["inline"]["status"] == "inline"
        assert "sql_datasets" not in refresh.detail  # replaced by the outcome detail
        call = executor.calls[0]
        assert call["connection_name"] == "warehouse" and call["row_limit"] == 50_000
        assert call["context"].path == "dashboard" and call["context"].project_id == "project-a"

    async def test_missing_column_keeps_old_version_and_fails(self, session_factory, db) -> None:
        storage, backend = fake_storage()
        dashboard, v1 = await _published(db, storage, backend)
        refresh = await _manual_refresh(db, dashboard)
        executor = FakeExecutor(rows=[{"month": "2026-03-01", "amount": 5}])

        await run_refresh(session_factory, refresh.id, storage=storage, executor=executor)

        await db.refresh(refresh)
        await db.refresh(dashboard)
        assert refresh.status == "failed"
        assert "revenue" in refresh.error and "rev_line" in refresh.error
        assert refresh.version_id is None
        assert dashboard.current_version_id == v1.id
        assert dashboard.last_refresh_status == "failed"
        assert refresh.detail["charts"][0]["failed"] is True
        assert refresh.detail["notification"]["channel"] == "log"
        assert len(await store.list_versions(db, dashboard.id)) == 1

    async def test_empty_after_nonempty_fails(self, session_factory, db) -> None:
        storage, backend = fake_storage()
        dashboard, v1 = await _published(db, storage, backend)
        refresh = await _manual_refresh(db, dashboard)

        await run_refresh(session_factory, refresh.id, storage=storage, executor=FakeExecutor(rows=[]))

        await db.refresh(refresh)
        assert refresh.status == "failed"
        assert "no rows" in refresh.error
        assert refresh.detail["datasets"]["monthly"]["status"] == "failed"

    async def test_query_error_fails_without_notification_when_disabled(self, session_factory, db) -> None:
        storage, backend = fake_storage()
        dashboard, _ = await _published(db, storage, backend, notify_on_failure=False)
        refresh = await _manual_refresh(db, dashboard)
        executor = FakeExecutor(error=GovernedQueryError("query_blocked", "nope"))

        await run_refresh(session_factory, refresh.id, storage=storage, executor=executor)

        await db.refresh(refresh)
        assert refresh.status == "failed"
        assert refresh.error == "monthly: query_blocked: nope"
        assert "notification" not in refresh.detail

    async def test_timeout_fails(self, session_factory, db, monkeypatch) -> None:
        monkeypatch.setattr(refresh_module, "SQL_TIMEOUT_SECONDS", -30)
        storage, backend = fake_storage()
        dashboard, _ = await _published(db, storage, backend)
        refresh = await _manual_refresh(db, dashboard)
        await run_refresh(session_factory, refresh.id, storage=storage, executor=FakeExecutor(delay=0.05))
        await db.refresh(refresh)
        assert refresh.status == "failed"
        assert "timed out" in refresh.error


class TestAgentRefresh:
    async def _agent_refresh_with_run(self, db, backend, *, run_status="completed", write_files=True, spec_override=None):
        conversation, run, rows = await add_conversation_with_files(db, backend)
        storage = DashboardStorage(backend)
        dashboard, v1 = await service.publish(
            db, storage, org_id=ORG, user_id=USER, is_admin=False, conversation_id=conversation.id,
            file_row=rows[0], manifest=rows,
            body=publish_body(refresh=RefreshSettingsIn(interval_minutes=1440, timezone="UTC", mode="agent")),
            project_id="project-a",
        )
        # The agent run: a second run in the same conversation writes new files.
        run.status = "completed"
        agent_run = GatewayChatRun(
            org_id=ORG,
            user_id=USER,
            conversation_id=conversation.id,
            project_id="project-a",
            user_message_id=run.user_message_id,
            status=run_status,
        )
        db.add(agent_run)
        await db.commit()
        run = agent_run
        refresh = await store.create_refresh(db, dashboard=dashboard, refresh_id=new_refresh_id(), mode="agent", trigger="manual")
        refresh.status = "running"
        refresh.started_at = store.utcnow()
        refresh.run_id = run.id
        refresh.conversation_id = conversation.id
        await db.commit()
        if write_files:
            spec = spec_override or await storage.get_spec(v1.spec_key)
            for path, data in (
                (f"artifacts/{dashboard.slug}.dashboard.json", json.dumps(spec).encode()),
                ("artifacts/monthly.csv", b"month,revenue\n2026-04-01,140\n2026-05-01,150\n"),
            ):
                backend.objects[f"chat2/{path}"] = data
                await chat_store.upsert_conversation_file(
                    db, org_id=ORG, user_id=USER, conversation_id=conversation.id, path=path,
                    filename=path.rsplit("/", 1)[-1], mime_type=None, byte_size=len(data),
                    content_hash=hashlib.sha256(data).hexdigest(), object_key=f"chat2/{path}",
                    origin_run_id=run.id, origin="mirror",
                )
        return storage, dashboard, v1, refresh, run

    async def test_finalize_completed_run_creates_version(self, db) -> None:
        _, backend = fake_storage()
        storage, dashboard, v1, refresh, run = await self._agent_refresh_with_run(db, backend)
        await finalize_agent_refresh(db, refresh, run, storage=storage)
        assert refresh.status == "succeeded"
        v2 = await store.get_version(db, dashboard_id=dashboard.id, version_id=refresh.version_id)
        assert v2.version_no == 2
        assert v2.dataset_meta["monthly"]["row_count"] == 2
        assert v2.dataset_keys["regions"] == v1.dataset_keys["regions"]
        assert dashboard.current_version_id == v2.id

    async def test_finalize_failed_run_fails(self, db) -> None:
        _, backend = fake_storage()
        storage, dashboard, v1, refresh, run = await self._agent_refresh_with_run(db, backend, run_status="failed", write_files=False)
        run.public_error_message = "budget exceeded"
        await finalize_agent_refresh(db, refresh, run, storage=storage)
        assert refresh.status == "failed"
        assert "budget exceeded" in refresh.error
        assert dashboard.current_version_id == v1.id

    async def test_finalize_missing_files_fails(self, db) -> None:
        _, backend = fake_storage()
        storage, dashboard, v1, refresh, run = await self._agent_refresh_with_run(db, backend, write_files=False)
        await finalize_agent_refresh(db, refresh, run, storage=storage)
        assert refresh.status == "failed"
        assert "did not write" in refresh.error

    async def test_finalize_rejects_changed_chart_ids(self, db) -> None:
        _, backend = fake_storage()
        changed = spec_json()
        changed["charts"][0]["id"] = "renamed"
        storage, dashboard, v1, refresh, run = await self._agent_refresh_with_run(db, backend, spec_override=changed)
        await finalize_agent_refresh(db, refresh, run, storage=storage)
        assert refresh.status == "failed"
        assert "chart ids" in refresh.error

    async def test_poll_finalizes_terminal_runs_only(self, session_factory, db) -> None:
        _, backend = fake_storage()
        storage, dashboard, v1, refresh, run = await self._agent_refresh_with_run(db, backend, run_status="running")
        assert await poll_agent_refreshes(session_factory, storage=storage) == 0
        run.status = "completed"
        await db.commit()
        assert await poll_agent_refreshes(session_factory, storage=storage) == 1
        await db.refresh(refresh)
        assert refresh.status == "succeeded"

    async def test_poll_times_out_stale_runs(self, session_factory, db) -> None:
        _, backend = fake_storage()
        storage, dashboard, v1, refresh, run = await self._agent_refresh_with_run(db, backend, run_status="running")
        late = datetime.now(UTC) + scheduler.AGENT_REFRESH_TIMEOUT + timedelta(minutes=1)
        assert await poll_agent_refreshes(session_factory, now_utc=late, storage=storage) == 1
        await db.refresh(refresh)
        assert refresh.status == "failed" and "2 hours" in refresh.error

    async def test_run_refresh_agent_mode_seeds_and_stays_running(self, session_factory, db, monkeypatch) -> None:
        storage, backend = fake_storage()
        dashboard, _ = await _published(db, storage, backend, refresh=RefreshSettingsIn(interval_minutes=None, timezone="UTC", mode="agent"))
        refresh = await _manual_refresh(db, dashboard, mode="agent")

        async def fake_seed(db_, dashboard_, spec):
            assert spec["title"] == "Revenue"
            return "conv-x", "run-x"

        monkeypatch.setattr(refresh_module, "seed_agent_run", fake_seed)
        await run_refresh(session_factory, refresh.id, storage=storage)
        await db.refresh(refresh)
        assert refresh.status == "running"
        assert (refresh.conversation_id, refresh.run_id) == ("conv-x", "run-x")

    async def test_refresh_message_lists_sql_datasets(self, db) -> None:
        storage, backend = fake_storage()
        dashboard, _ = await _published(db, storage, backend)
        message = refresh_module.refresh_message(dashboard, spec_json())
        assert "`monthly` -> `artifacts/monthly.csv` on connection `warehouse`" in message
        assert "artifacts/revenue.dashboard.json" in message
        assert "dashboard_sample_data" in message
        assert "—" not in message


class TestCrashPath:
    async def test_crash_after_start_marks_refresh_failed(self, session_factory, db) -> None:
        """A crash inside run_refresh must not leave the row stuck in "running"."""
        storage, backend = fake_storage()
        dashboard, _v1 = await _published(db, storage, backend)
        refresh = await _manual_refresh(db, dashboard)

        async def broken_get_spec(key):
            raise RuntimeError("spec store down")

        storage.get_spec = broken_get_spec  # type: ignore[method-assign]
        await run_refresh(session_factory, refresh.id, storage=storage, executor=FakeExecutor())

        await db.refresh(refresh)
        await db.refresh(dashboard)
        assert refresh.status == "failed"
        assert "spec store down" in (refresh.error or "")
        assert refresh.finished_at is not None
        assert dashboard.last_refresh_status == "failed"
        assert await store.active_refresh(db, dashboard.id) is None
