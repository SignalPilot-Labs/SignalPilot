"""Focused worker lifecycle contracts for standalone data chat."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from gateway.standalone_chat import worker


@pytest.mark.asyncio
async def test_cancellation_monitor_interrupts_the_active_worker_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop = asyncio.Event()

    class FakeSessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_args: object) -> None:
            return None

    async def get_worker_run(*_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(cancellation_requested_at="2026-08-19T12:00:00Z")

    async def wait_forever() -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(worker, "get_session_factory", lambda: FakeSessionContext)
    monkeypatch.setattr(worker.chat_store, "get_worker_run", get_worker_run)
    worker_task = asyncio.create_task(wait_forever())

    await worker._cancellation_monitor("run-a", "worker-a", stop, worker_task)

    assert stop.is_set()
    with pytest.raises(asyncio.CancelledError):
        await worker_task


@pytest.mark.asyncio
async def test_notebook_stream_does_not_hold_a_database_session(monkeypatch: pytest.MonkeyPatch) -> None:
    active_sessions = 0
    completed_runs: list[str] = []
    failed_runs: list[str] = []
    appended_events: list[tuple[str, dict[str, Any]]] = []

    class FakeSessionContext:
        async def __aenter__(self) -> object:
            nonlocal active_sessions
            active_sessions += 1
            return object()

        async def __aexit__(self, *_args: object) -> None:
            nonlocal active_sessions
            active_sessions -= 1

    def session_factory() -> FakeSessionContext:
        return FakeSessionContext()

    run = SimpleNamespace(
        id="run-a",
        execution_attempt=1,
        cancellation_requested_at=None,
    )
    project = SimpleNamespace(
        connection_name="production",
        default_branch="main",
    )
    conversation = SimpleNamespace(
        branch="main",
        commit_sha="a" * 40,
    )
    message = SimpleNamespace(role="user", content="Diagnose revenue")

    async def get_worker_run(*_args: Any, **_kwargs: Any) -> Any:
        return run

    async def worker_context(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {
            "project": project,
            "conversation": conversation,
            "messages": [message],
        }

    async def stream_execution(*_args: Any, **_kwargs: Any):
        if active_sessions:
            raise RuntimeError("database session remained open during notebook execution")
        yield {
            "type": "tool_use",
            "tool_name": "mcp__signalpilot-notebook__run_cells",
            "tool_call_id": "failed-run",
            "tool_input": {"cell_ids": ["cell-a"]},
        }
        yield {
            "type": "tool_result",
            "tool_call_id": "failed-run",
            "is_error": True,
        }
        yield {
            "type": "progress",
            "content": "Restarting analysis in a clean notebook",
        }
        yield {"type": "final", "content": "Analysis complete", "artifacts": []}

    async def prepare_execution(*_args: Any, **_kwargs: Any) -> object:
        return object()

    async def complete_run(*_args: Any, **kwargs: Any) -> None:
        completed_runs.append(kwargs["run_id"])

    async def fail_run(*_args: Any, **kwargs: Any) -> None:
        failed_runs.append(kwargs["run_id"])

    async def wait_until_stopped(
        _run_id: str,
        _worker_id: str,
        stop: Any,
        _worker_task: Any = None,
    ) -> None:
        await stop.wait()

    async def noop(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def append_event(
        _run_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        appended_events.append((event_type, payload))

    monkeypatch.setattr(worker, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(worker.chat_store, "get_worker_run", get_worker_run)
    monkeypatch.setattr(worker.chat_store, "worker_context", worker_context)
    monkeypatch.setattr(worker.chat_store, "complete_run", complete_run)
    monkeypatch.setattr(worker.chat_store, "fail_run", fail_run)
    monkeypatch.setattr(worker, "prepare_execution", prepare_execution)
    monkeypatch.setattr(worker, "stream_execution", stream_execution)
    monkeypatch.setattr(worker, "_warm_context", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(worker, "_append", append_event)
    monkeypatch.setattr(worker, "_persist_artifacts", noop)
    monkeypatch.setattr(worker, "_lease_renewer", wait_until_stopped)
    monkeypatch.setattr(worker, "_cancellation_monitor", wait_until_stopped)
    monkeypatch.setattr(worker, "cleanup_finished_execution", noop)

    await worker._execute_claimed_run("run-a", "worker-a")

    assert completed_runs == ["run-a"]
    assert failed_runs == []
    assert ("cell_executed", {"status": "failed"}) in appended_events
    assert (
        "progress",
        {"label": "Restarting analysis in a clean notebook"},
    ) in appended_events


@pytest.mark.asyncio
async def test_terminal_notebook_validation_error_persists_no_answer_or_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed_runs: list[str] = []
    failed_runs: list[str] = []
    persisted_artifacts: list[str] = []

    class FakeSessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_args: object) -> None:
            return None

    run = SimpleNamespace(
        id="run-dirty",
        execution_attempt=1,
        cancellation_requested_at=None,
    )
    context = {
        "project": SimpleNamespace(
            connection_name="production",
            default_branch="main",
        ),
        "conversation": SimpleNamespace(
            branch="main",
            commit_sha="a" * 40,
            internal_summary=None,
        ),
        "messages": [SimpleNamespace(role="user", content="Diagnose revenue")],
        "artifacts": [],
        "query_approvals": [],
        "query_proposals": [],
        "query_executions": [],
        "query_results": [],
    }

    async def get_worker_run(*_args: Any, **_kwargs: Any) -> Any:
        return run

    async def worker_context(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return context

    async def stream_execution(*_args: Any, **_kwargs: Any):
        yield {
            "type": "error",
            "content": "Notebook validation failed after one clean retry; the answer was rejected.",
        }

    async def prepare_execution(*_args: Any, **_kwargs: Any) -> object:
        return object()

    async def complete_run(*_args: Any, **kwargs: Any) -> None:
        completed_runs.append(kwargs["run_id"])

    async def fail_run(*_args: Any, **kwargs: Any) -> None:
        failed_runs.append(kwargs["run_id"])

    async def persist_artifacts(*_args: Any, **kwargs: Any) -> None:
        persisted_artifacts.append(kwargs["run_id"])

    async def wait_until_stopped(
        _run_id: str,
        _worker_id: str,
        stop: Any,
        _worker_task: Any = None,
    ) -> None:
        await stop.wait()

    async def noop(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(worker, "get_session_factory", lambda: FakeSessionContext)
    monkeypatch.setattr(worker.chat_store, "get_worker_run", get_worker_run)
    monkeypatch.setattr(worker.chat_store, "worker_context", worker_context)
    monkeypatch.setattr(worker.chat_store, "complete_run", complete_run)
    monkeypatch.setattr(worker.chat_store, "fail_run", fail_run)
    monkeypatch.setattr(worker, "prepare_execution", prepare_execution)
    monkeypatch.setattr(worker, "stream_execution", stream_execution)
    monkeypatch.setattr(worker, "_warm_context", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(worker, "_append", noop)
    monkeypatch.setattr(worker, "_persist_artifacts", persist_artifacts)
    monkeypatch.setattr(worker, "_lease_renewer", wait_until_stopped)
    monkeypatch.setattr(worker, "_cancellation_monitor", wait_until_stopped)
    monkeypatch.setattr(worker, "cleanup_finished_execution", noop)

    await worker._execute_claimed_run("run-dirty", "worker-a")

    assert completed_runs == []
    assert persisted_artifacts == []
    assert failed_runs == ["run-dirty"]
