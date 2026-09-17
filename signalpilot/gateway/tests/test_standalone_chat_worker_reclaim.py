"""Re-claimed and reconnected runs stop the previous attempt before executing."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from gateway.standalone_chat import worker, worker_events


class FakeSessionContext:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *_args: object) -> None:
        return None


def _patch_worker(
    monkeypatch: pytest.MonkeyPatch,
    *,
    run: Any,
    stream_execution: Any,
    calls: list[str],
) -> dict[str, list[str]]:
    outcome: dict[str, list[str]] = {"completed": [], "failed": []}
    context = {
        "project": SimpleNamespace(connection_name="production", default_branch="main"),
        "conversation": SimpleNamespace(branch="main", commit_sha="a" * 40, internal_summary=None),
        "messages": [SimpleNamespace(role="user", content="Diagnose revenue")],
    }

    async def get_worker_run(*_args: Any, **_kwargs: Any) -> Any:
        return run

    async def worker_context(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return context

    async def prepare_execution(*_args: Any, **_kwargs: Any) -> object:
        return SimpleNamespace(url="http://runtime/api/standalone-chat/execute", headers={}, session_id=None)

    async def cancel_previous_attempt(_execution: Any, *, run_id: str, reason: str) -> bool:
        calls.append(f"cancel:{run_id}:{reason}")
        return True

    async def complete_run(*_args: Any, **kwargs: Any) -> None:
        outcome["completed"].append(kwargs["run_id"])

    async def fail_run(*_args: Any, **kwargs: Any) -> None:
        outcome["failed"].append(kwargs["run_id"])

    async def wait_until_stopped(_run_id: str, _worker_id: str, stop: Any, _task: Any = None) -> None:
        await stop.wait()

    async def steering_stub(_run_id: str, _worker_id: str, _execution: Any, stop: Any) -> None:
        await stop.wait()

    async def noop(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def no_interrupted(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr(worker, "get_session_factory", lambda: FakeSessionContext)
    monkeypatch.setattr(worker.chat_store, "get_worker_run", get_worker_run)
    monkeypatch.setattr(worker.chat_store, "worker_context", worker_context)
    monkeypatch.setattr(worker.chat_store, "complete_run", complete_run)
    monkeypatch.setattr(worker.chat_store, "fail_run", fail_run)
    monkeypatch.setattr(worker, "prepare_execution", prepare_execution)
    monkeypatch.setattr(worker, "stream_execution", stream_execution)
    monkeypatch.setattr(worker, "_cancel_previous_attempt", cancel_previous_attempt)
    monkeypatch.setattr(worker, "load_interrupted_tool_completions", no_interrupted)
    monkeypatch.setattr(worker, "_warm_context", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(worker, "_append", noop)
    monkeypatch.setattr(worker, "_update_summary", noop)
    monkeypatch.setattr(worker, "_lease_renewer", wait_until_stopped)
    monkeypatch.setattr(worker, "_cancellation_monitor", wait_until_stopped)
    monkeypatch.setattr(worker, "_steering_monitor", steering_stub)
    monkeypatch.setattr(worker, "cleanup_finished_execution", noop)
    return outcome


@pytest.mark.asyncio
async def test_reclaimed_run_cancels_previous_attempt_before_execute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    run = SimpleNamespace(
        id="run-reclaimed",
        org_id="org-a",
        user_id="user-a",
        project_id="project-a",
        conversation_id="conv-a",
        execution_attempt=2,
        cancellation_requested_at=None,
    )

    async def stream_execution(*_args: Any, **_kwargs: Any):
        calls.append("stream")
        yield {"type": "final", "content": "Resumed answer"}

    outcome = _patch_worker(monkeypatch, run=run, stream_execution=stream_execution, calls=calls)

    await worker._execute_claimed_run("run-reclaimed", "worker-b")

    assert calls == ["cancel:run-reclaimed:re-claimed", "stream"]
    assert outcome == {"completed": ["run-reclaimed"], "failed": []}


@pytest.mark.asyncio
async def test_first_attempt_does_not_cancel_but_reconnect_does(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    run = SimpleNamespace(
        id="run-fresh",
        org_id="org-a",
        user_id="user-a",
        project_id="project-a",
        conversation_id="conv-a",
        execution_attempt=1,
        cancellation_requested_at=None,
    )
    streams = 0

    async def stream_execution(*_args: Any, **_kwargs: Any):
        nonlocal streams
        streams += 1
        calls.append("stream")
        if streams == 1:
            raise httpx.ReadError("connection dropped")
        yield {"type": "final", "content": "Answer after reconnect"}

    outcome = _patch_worker(monkeypatch, run=run, stream_execution=stream_execution, calls=calls)

    await worker._execute_claimed_run("run-fresh", "worker-a")

    assert calls == ["stream", "cancel:run-fresh:reconnect", "stream"]
    assert outcome == {"completed": ["run-fresh"], "failed": []}


@pytest.mark.asyncio
async def test_cancel_previous_attempt_posts_keep_kernels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posted: list[dict[str, Any]] = []

    class FakeResponse:
        status_code = 200
        is_success = True

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            posted.append({"client": kwargs})

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def post(self, url: str, **kwargs: Any) -> FakeResponse:
            posted.append({"url": url, **kwargs})
            return FakeResponse()

    monkeypatch.setattr(worker_events.httpx, "AsyncClient", FakeClient)
    execution = SimpleNamespace(
        url="http://runtime/api/standalone-chat/execute",
        headers={"Authorization": "Bearer t"},
    )

    assert await worker_events._cancel_previous_attempt(execution, run_id="run-x", reason="re-claimed") is True

    assert posted[0]["client"] == {"timeout": worker_events.PREVIOUS_ATTEMPT_CANCEL_TIMEOUT_SECONDS}
    assert posted[1] == {
        "url": "http://runtime/api/standalone-chat/cancel/run-x",
        "headers": {"Authorization": "Bearer t"},
        "params": {"keep_kernels": "1"},
    }


@pytest.mark.asyncio
async def test_cancel_previous_attempt_tolerates_runtime_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingClient:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> FailingClient:
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def post(self, *_args: Any, **_kwargs: Any) -> Any:
            raise httpx.ConnectTimeout("runtime unreachable")

    monkeypatch.setattr(worker_events.httpx, "AsyncClient", FailingClient)
    execution = SimpleNamespace(url="http://runtime/api/standalone-chat/execute", headers={})

    assert await worker_events._cancel_previous_attempt(execution, run_id="run-y", reason="reconnect") is False


@pytest.mark.asyncio
async def test_runtime_public_error_code_reaches_fail_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    events: list[tuple[str, dict[str, Any]]] = []
    failures: list[dict[str, Any]] = []
    run = SimpleNamespace(
        id="run-breaker",
        org_id="org-a",
        user_id="user-a",
        project_id="project-a",
        conversation_id="conv-a",
        execution_attempt=1,
        cancellation_requested_at=None,
    )

    async def stream_execution(*_args: Any, **_kwargs: Any):
        yield {"type": "text_delta", "content": "partial"}
        yield {
            "type": "error",
            "content": "The SignalPilot gateway did not answer three tool calls in a row.",
            "public_error_code": "gateway_unavailable",
            "public_error_message": "The SignalPilot gateway did not answer three tool calls in a row.",
            "is_error": True,
            "diagnostic_context": {"error_type": "GatewayUnavailable"},
        }

    async def append_event(_run_id: str, event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    async def fail_run(*_args: Any, **kwargs: Any) -> None:
        failures.append(kwargs)

    _patch_worker(monkeypatch, run=run, stream_execution=stream_execution, calls=calls)
    monkeypatch.setattr(worker, "_append", append_event)
    monkeypatch.setattr(worker.chat_store, "fail_run", fail_run)

    await worker._execute_claimed_run("run-breaker", "worker-a")

    assert calls == []
    assert len(failures) == 1
    assert failures[0]["code"] == "gateway_unavailable"
    assert failures[0]["message"] == (
        "The SignalPilot gateway did not answer three tool calls in a row."
    )
    error_events = [payload for event_type, payload in events if event_type == "error"]
    assert len(error_events) == 1
    assert error_events[0]["code"] == "gateway_unavailable"
    assert error_events[0]["message"] == failures[0]["message"]
