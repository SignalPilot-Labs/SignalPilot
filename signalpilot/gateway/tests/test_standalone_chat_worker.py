"""Focused worker lifecycle contracts for standalone data chat."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from gateway.standalone_chat import worker


@pytest.mark.asyncio
async def test_notebook_stream_does_not_hold_a_database_session(monkeypatch: pytest.MonkeyPatch) -> None:
    active_sessions = 0
    completed_runs: list[str] = []
    failed_runs: list[str] = []

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
        yield {"type": "final", "content": "Analysis complete", "artifacts": []}

    async def prepare_execution(*_args: Any, **_kwargs: Any) -> object:
        return object()

    async def complete_run(*_args: Any, **kwargs: Any) -> None:
        completed_runs.append(kwargs["run_id"])

    async def fail_run(*_args: Any, **kwargs: Any) -> None:
        failed_runs.append(kwargs["run_id"])

    async def wait_until_stopped(_run_id: str, _worker_id: str, stop: Any) -> None:
        await stop.wait()

    async def noop(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(worker, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(worker.chat_store, "get_worker_run", get_worker_run)
    monkeypatch.setattr(worker.chat_store, "worker_context", worker_context)
    monkeypatch.setattr(worker.chat_store, "complete_run", complete_run)
    monkeypatch.setattr(worker.chat_store, "fail_run", fail_run)
    monkeypatch.setattr(worker, "prepare_execution", prepare_execution)
    monkeypatch.setattr(worker, "stream_execution", stream_execution)
    monkeypatch.setattr(worker, "_warm_context", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(worker, "_append", noop)
    monkeypatch.setattr(worker, "_persist_artifacts", noop)
    monkeypatch.setattr(worker, "_lease_renewer", wait_until_stopped)
    monkeypatch.setattr(worker, "_cancellation_monitor", wait_until_stopped)
    monkeypatch.setattr(worker, "cleanup_finished_execution", noop)

    await worker._execute_claimed_run("run-a", "worker-a")

    assert completed_runs == ["run-a"]
    assert failed_runs == []
