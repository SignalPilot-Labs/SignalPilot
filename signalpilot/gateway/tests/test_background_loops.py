"""Background loop registry: every loop is scheduled, and cancellation is clean."""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock

import pytest

from gateway.background import cancel_background_tasks, start_background_tasks
from gateway.background import loops as loops_module
from gateway.background.loops import BACKGROUND_TASK_NAMES

EXPECTED_LOOPS = {
    "health_flush": loops_module.health_flush_loop,
    "health_cleanup": loops_module.health_cleanup_loop,
    "health_ping": loops_module.health_ping_loop,
    "pool_cleanup": loops_module.pool_cleanup_loop,
    "schema_refresh": loops_module.schema_refresh_loop,
    "notebook_lifecycle": loops_module.notebook_lifecycle_loop,
    "knowledge_retention": loops_module.knowledge_retention_loop,
    "schema_watch": loops_module.schema_watch_loop,
    "eval_reaper": loops_module.eval_reaper_loop,
    "eval_retention": loops_module.eval_retention_loop,
    "improvement_schedule": loops_module.improvement_schedule_loop,
    "dbt_map_reaper": loops_module.dbt_map_reaper_loop,
    "dashboard_refresh": loops_module.dashboard_refresh_loop,
    "repo_mirror_reconcile": loops_module.repo_mirror_reconcile_startup,
}


def _unused_session_factory():
    raise AssertionError("no loop should open a session before its first sleep elapses")


@pytest.fixture(autouse=True)
def _stub_eval_startup_recovery(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    # eval_reaper_loop runs one recovery pass before its first sleep; keep it
    # off the database so the registry tests stay hermetic.
    from gateway.evals import retention

    stub = AsyncMock(return_value=0)
    monkeypatch.setattr(retention, "recover_stale_runs", stub)
    return stub


def test_registry_names_match_expected_loops() -> None:
    assert list(BACKGROUND_TASK_NAMES) == list(EXPECTED_LOOPS)
    for fn in EXPECTED_LOOPS.values():
        assert inspect.iscoroutinefunction(fn)


async def test_start_registers_every_loop_by_name() -> None:
    tasks = start_background_tasks(_unused_session_factory)
    try:
        assert len(tasks) == len(EXPECTED_LOOPS) == 14
        assert [t.get_name() for t in tasks] == list(EXPECTED_LOOPS)
        for task, fn in zip(tasks, EXPECTED_LOOPS.values(), strict=True):
            assert isinstance(task, asyncio.Task)
            assert task.get_coro().__qualname__ == fn.__qualname__
        # Let every loop reach its first await; none may finish or raise.
        await asyncio.sleep(0)
        assert all(not t.done() for t in tasks)
    finally:
        await cancel_background_tasks(tasks)


async def test_cancel_awaits_cancellation_cleanly() -> None:
    tasks = start_background_tasks(_unused_session_factory)
    await asyncio.sleep(0)
    await cancel_background_tasks(tasks)
    assert all(t.done() for t in tasks)
    assert all(t.cancelled() for t in tasks)
    # Idempotent: cancelling already-finished tasks is a no-op.
    await cancel_background_tasks(tasks)
