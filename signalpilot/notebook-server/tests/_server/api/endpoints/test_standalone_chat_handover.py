"""Idempotent /execute per run id and archive-failure tolerance.

A re-claimed gateway run POSTs /execute again with the same run id while
the previous attempt is still alive. The newer attempt must take over the
kernels and scratch; the superseded attempt's cleanup must leave them
alone. An archive upload failure must never replace the accepted answer.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from signalpilot._server.ai.claude_agent import AgentEvent
from signalpilot._server.api.endpoints import (
    standalone_chat_cancel as chat_cancel,
    standalone_chat_execution as standalone_chat,
    standalone_chat_handover as handover,
    standalone_chat_runtime as chat_runtime,
    standalone_chat_workspace as chat_workspace,
)
from signalpilot._server.api.endpoints.standalone_chat_finalize import (
    ARCHIVE_FAILED_WARNING,
)

# The autouse JWT fixture must be in this module's namespace to apply here.
from tests._server.api.endpoints.test_standalone_chat_execution import (
    _request,
    _runtime_session,
    _scoped_token,
    _session_jwt_secret,  # noqa: F401
)

if TYPE_CHECKING:
    from pathlib import Path

PROJECT_ID = "1dbf5492-81e6-4683-835f-f1785c9cfe78"
COMMIT_SHA = "a" * 40


def _execute_body(run_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "project_id": PROJECT_ID,
        "branch": "main",
        "connection_name": "production",
        "commit_sha": COMMIT_SHA,
        "gateway_session_token": _scoped_token(
            run_id=run_id, project_id=PROJECT_ID, commit_sha=COMMIT_SHA
        ),
        "prompt": "Analyze revenue",
    }


async def _collect(response: Any) -> list[dict[str, Any]]:
    raw = b"".join([chunk async for chunk in response.body_iterator])
    return [json.loads(line) for line in raw.splitlines()]


def _patch_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tmp_path: Path,
    sessions: dict[str, Any],
    closed: list[str],
    lifecycles: list[Any],
    event_sinks: list[Any],
    archive: Any,
) -> None:
    async def execution_directory(**_kwargs: Any) -> tuple[Path, bool]:
        return tmp_path / "project", False

    def build_server(**kwargs: Any) -> object:
        lifecycles.append(kwargs["notebook_lifecycle"])
        event_sinks.append(kwargs["event_sink"])
        return object()

    (tmp_path / "project").mkdir(exist_ok=True)
    monkeypatch.setenv("SP_CHAT_SCRATCH_ROOT", str(tmp_path / "scratch"))
    monkeypatch.setattr(
        chat_workspace, "_execution_project_directory", execution_directory
    )
    monkeypatch.setattr(
        standalone_chat, "build_standalone_chat_mcp_server", build_server
    )
    for module in (chat_runtime, standalone_chat):
        monkeypatch.setattr(
            module,
            "_analysis_session",
            lambda _app, session_id: sessions[session_id],
        )
        monkeypatch.setattr(
            module,
            "_close_analysis_kernel",
            lambda _app, session_id: closed.append(session_id) or True,
        )
    monkeypatch.setattr(
        standalone_chat, "_project_is_unchanged", lambda *_args: True
    )
    monkeypatch.setattr(
        standalone_chat, "clear_chat_session", lambda *_a, **_k: None
    )
    monkeypatch.setattr(standalone_chat, "_archive_analysis_notebook", archive)


@pytest.fixture(autouse=True)
def _clean_registry() -> Any:
    handover._RUN_EXECUTIONS.clear()
    handover._RUN_LOCKS.clear()
    chat_runtime._ANALYSIS_SESSIONS_BY_RUN.clear()
    yield
    handover._RUN_EXECUTIONS.clear()
    handover._RUN_LOCKS.clear()
    chat_runtime._ANALYSIS_SESSIONS_BY_RUN.clear()


@pytest.mark.asyncio
async def test_second_execute_for_one_run_id_supersedes_the_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "run-handover-1"
    app = SimpleNamespace()
    sessions: dict[str, Any] = {"kernel-1": _runtime_session()}
    closed: list[str] = []
    lifecycles: list[Any] = []
    event_sinks: list[Any] = []
    stopped: list[str] = []
    prompts: list[str] = []
    first_started = asyncio.Event()
    first_stop = asyncio.Event()

    async def archive(**_kwargs: Any) -> str:
        return "archive-2"

    async def run_agent(prompt: str, _session_id: object, **_kwargs: Any):
        prompts.append(prompt)
        attempt = len(prompts)
        lifecycle = lifecycles[-1]
        if attempt == 1:
            lifecycle.session_id = "kernel-1"
            await event_sinks[-1]("notebook_started", {})
            yield AgentEvent(type="text_delta", content="first attempt")
            first_started.set()
            # Blocks like a live SDK client until the handover stops it.
            await first_stop.wait()
            return
        # The second attempt inherits the first attempt's kernel.
        assert lifecycle.sessions == {"analysis": "kernel-1"}
        yield AgentEvent(
            type="tool_use",
            tool_name="mcp__signalpilot-notebook__run_cells",
            tool_call_id="run-2",
            tool_input={"session_id": "kernel-1"},
        )
        yield AgentEvent(
            type="tool_result", tool_call_id="run-2", is_error=False
        )
        yield AgentEvent(type="text", content="Second attempt answer")

    def stop_agent(session_id: str) -> bool:
        stopped.append(session_id)
        first_stop.set()
        return True

    _patch_runtime(
        monkeypatch,
        tmp_path=tmp_path,
        sessions=sessions,
        closed=closed,
        lifecycles=lifecycles,
        event_sinks=event_sinks,
        archive=archive,
    )
    monkeypatch.setattr(standalone_chat, "run_notebook_agent", run_agent)
    monkeypatch.setattr(standalone_chat, "stop_agent", stop_agent)

    first = await standalone_chat.execute(
        request=_request(_execute_body(run_id), app=app)
    )
    first_task = asyncio.create_task(_collect(first))
    await asyncio.wait_for(first_started.wait(), timeout=5)
    scratch = tmp_path / "scratch" / run_id
    notebook = scratch / "analysis.py"
    notebook.write_text("# edited by the live kernel", encoding="utf-8")
    assert chat_runtime._ANALYSIS_SESSIONS_BY_RUN[run_id] == {"kernel-1"}

    second = await standalone_chat.execute(
        request=_request(_execute_body(run_id), app=app)
    )
    assert stopped == [f"standalone-{run_id}"]
    first_events = await asyncio.wait_for(first_task, timeout=5)
    second_events = await _collect(second)

    # The superseded attempt streamed nothing final and cleaned nothing up.
    assert [event["type"] for event in first_events] == ["text_delta"]
    assert closed == []
    assert scratch.is_dir()
    assert notebook.read_text(encoding="utf-8") == "# edited by the live kernel"
    # The new attempt re-announced the inherited kernel, was told to keep
    # using it, and finished with a validated answer.
    assert second_events[0] == {
        "type": "notebook_started",
        "session_id": "kernel-1",
        "notebook_path": str(scratch / "analysis.py"),
        "notebook": "analysis",
    }
    assert "session_id `kernel-1`" in prompts[1]
    assert second_events[-1]["type"] == "final"
    assert second_events[-1]["content"] == "Second attempt answer"
    assert second_events[-1]["archive_id"] == "archive-2"
    assert handover._RUN_EXECUTIONS == {}


@pytest.mark.asyncio
async def test_archive_failure_keeps_the_answer_and_the_kernel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "run-archive-warn"
    app = SimpleNamespace()
    sessions: dict[str, Any] = {"kernel-1": _runtime_session()}
    closed: list[str] = []
    lifecycles: list[Any] = []
    event_sinks: list[Any] = []

    async def archive(**_kwargs: Any) -> str:
        raise httpx.ReadTimeout("")

    async def run_agent(_prompt: str, _session_id: object, **_kwargs: Any):
        lifecycle = lifecycles[-1]
        lifecycle.session_id = "kernel-1"
        await event_sinks[-1]("notebook_started", {})
        yield AgentEvent(
            type="tool_use",
            tool_name="mcp__signalpilot-notebook__run_cells",
            tool_call_id="run-1",
        )
        yield AgentEvent(
            type="tool_result", tool_call_id="run-1", is_error=False
        )
        yield AgentEvent(type="text", content="The composed answer")

    _patch_runtime(
        monkeypatch,
        tmp_path=tmp_path,
        sessions=sessions,
        closed=closed,
        lifecycles=lifecycles,
        event_sinks=event_sinks,
        archive=archive,
    )
    monkeypatch.setattr(standalone_chat, "run_notebook_agent", run_agent)

    response = await standalone_chat.execute(
        request=_request(_execute_body(run_id), app=app)
    )
    events = await _collect(response)

    assert [event["type"] for event in events] == [
        "tool_use",
        "tool_result",
        "progress",
        "final",
    ]
    warning = events[2]
    assert warning["content"] == ARCHIVE_FAILED_WARNING
    assert warning["is_error"] is False
    assert warning["diagnostic_context"]["error_type"] == "ReadTimeout"
    assert "ReadTimeout('')" not in json.dumps(events)
    assert events[-1] == {"type": "final", "content": "The composed answer"}
    # The kernel stays alive for the live notebook panel.
    assert closed == []


@pytest.mark.asyncio
async def test_cancel_with_keep_kernels_supersedes_without_closing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from starlette.authentication import AuthCredentials, SimpleUser
    from starlette.requests import Request

    run_id = "run-keep-kernels"
    stopped: list[str] = []
    closed: list[str] = []
    record, _ = handover.take_over_run(
        run_id, stop_agent_fn=lambda _session: False
    )
    record.lifecycle = SimpleNamespace(sessions={"analysis": "kernel-9"})
    chat_runtime._ANALYSIS_SESSIONS_BY_RUN[run_id] = {"kernel-9"}
    monkeypatch.setattr(
        chat_cancel, "stop_agent", lambda s: stopped.append(s) or True
    )
    monkeypatch.setattr(
        chat_cancel,
        "_close_analysis_kernel",
        lambda _app, s: closed.append(s) or True,
    )
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": f"/api/standalone-chat/cancel/{run_id}",
            "path_params": {"run_id": run_id},
            "query_string": b"keep_kernels=1",
            "headers": [],
            "auth": AuthCredentials(["edit"]),
            "user": SimpleUser("test-user"),
            "app": SimpleNamespace(),
        }
    )

    response = await chat_cancel.cancel(request=request)

    assert json.loads(response.body) == {
        "stopped": True,
        "kernel_stopped": False,
        "superseded": True,
    }
    assert stopped == [f"standalone-{run_id}"]
    assert closed == []
    assert record.superseded is True
    assert record.sessions_snapshot == {"analysis": "kernel-9"}
    assert chat_runtime._ANALYSIS_SESSIONS_BY_RUN[run_id] == {"kernel-9"}
    # The next /execute inherits the frozen sessions.
    newer, inherited = handover.take_over_run(
        run_id, stop_agent_fn=lambda _session: False
    )
    assert newer.sequence == 2
    assert inherited is None  # no working scratch was recorded
    assert handover.release_run(record) is False
    assert handover.release_run(newer) is True


@pytest.mark.asyncio
async def test_tripped_transport_breaker_ends_run_with_gateway_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import uuid

    from signalpilot._server.ai import transport_breaker

    run_id = "run-breaker-trip"
    # The breaker run key is the agent chat session id: for a body without
    # conversation_id that is the uuid5 the execute route derives.
    run_key = str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"signalpilot:standalone:{run_id}")
    )
    app = SimpleNamespace()
    sessions: dict[str, Any] = {"kernel-1": _runtime_session()}
    closed: list[str] = []
    lifecycles: list[Any] = []
    event_sinks: list[Any] = []
    archived: list[str] = []

    async def archive(**_kwargs: Any) -> str:
        archived.append("archive")
        return "archive-x"

    async def run_agent(_prompt: str, _session_id: object, **_kwargs: Any):
        lifecycle = lifecycles[-1]
        lifecycle.session_id = "kernel-1"
        await event_sinks[-1]("notebook_started", {})
        yield AgentEvent(type="text_delta", content="partial narration")
        breaker = transport_breaker.breaker_for_run(run_key, reset=True)
        for _ in range(transport_breaker.MAX_CONSECUTIVE_FAILURES):
            breaker.record_failure("Streamable HTTP error")
        # The hook stopped the agent: the SDK reports a clean end of turn.
        yield AgentEvent(type="done")

    _patch_runtime(
        monkeypatch,
        tmp_path=tmp_path,
        sessions=sessions,
        closed=closed,
        lifecycles=lifecycles,
        event_sinks=event_sinks,
        archive=archive,
    )
    monkeypatch.setattr(standalone_chat, "run_notebook_agent", run_agent)

    response = await standalone_chat.execute(
        request=_request(_execute_body(run_id), app=app)
    )
    events = await _collect(response)

    assert [event["type"] for event in events] == [
        "text_delta",
        "done",
        "error",
    ]
    terminal = events[-1]
    assert terminal["public_error_code"] == "gateway_unavailable"
    assert terminal["public_error_message"] == (
        transport_breaker.GATEWAY_UNAVAILABLE_MESSAGE
    )
    assert terminal["content"] == terminal["public_error_message"]
    assert terminal["is_error"] is True
    assert terminal["diagnostic_context"]["consecutive_failures"] == 3
    # No final, no archive; the owning attempt's cleanup closed the kernel
    # and cleared the breaker so the next run starts with a fresh count.
    assert archived == []
    assert closed == ["kernel-1"]
    assert transport_breaker.transport_unavailable(run_key) is False
    assert run_key not in transport_breaker._BREAKERS
    assert handover._RUN_EXECUTIONS == {}
