"""A chat run keeps its notebook session out of the idle snapshot path.

Only the browser pings a notebook session. A chat conversation whose sandbox
outlived the idle window was therefore snapshotted by the lifecycle loop in
the middle of a run, which ended the run with "The analysis runtime returned
no answer" (staging, 2026-09-22). Three guards now hold:

1. the lifecycle loop treats a session with a non-terminal chat run as active;
2. the worker pings the session at boot and on every lease renewal;
3. an empty answer names the runtime's state instead of a bare "no answer".
"""

from __future__ import annotations

import asyncio
import types
from typing import Any

import pytest

from gateway.background import loops as loops_module
from gateway.standalone_chat import worker, worker_events
from gateway.store import notebook_sessions as ns


class _Settings:
    idle_snapshot_seconds = 60
    session_grant_seconds = 900

    def resolved_backend(self) -> str:
        return "vercel"


class _Backend:
    name = "vercel"

    def __init__(self) -> None:
        self.extended: list[str] = []

    async def extend(self, handle: str, seconds: int) -> None:
        self.extended.append(handle)


class _SessionFactory:
    def __call__(self):
        return self

    async def __aenter__(self):
        return object()

    async def __aexit__(self, *exc):
        return False


def _internal(session_id: str, last_ping: float) -> Any:
    return types.SimpleNamespace(
        session_id=session_id, org_id="org", runtime_handle=f"sbx-{session_id}",
        last_ping=last_ping, project_id=None, branch="main",
    )


@pytest.mark.asyncio
async def test_lifecycle_loop_extends_instead_of_snapshotting_a_session_with_a_live_run(monkeypatch):
    import gateway.notebooks.backends as backends
    import gateway.notebooks.session_service as session_service

    backend = _Backend()
    snapshotted: list[str] = []
    now = 1_000_000.0
    stale = now - 3_600  # far past the 60 s idle window

    async def sleep(_seconds):
        if calls:
            raise asyncio.CancelledError
        calls.append(1)

    calls: list[int] = []
    monkeypatch.setattr(loops_module.asyncio, "sleep", sleep)
    monkeypatch.setattr(loops_module.time, "time", lambda: now)
    monkeypatch.setattr(backends, "get_notebook_backend", lambda settings: backend)

    async def snapshot_idle_session(session, *, internal, backend):
        snapshotted.append(internal.session_id)

    monkeypatch.setattr(session_service, "snapshot_idle_session", snapshot_idle_session)

    async def list_running_internal(session):
        return [_internal("busy", stale), _internal("quiet", stale)]

    async def session_ids_with_active_chat_runs(session):
        return {"busy"}

    async def update_session_runtime(session, **kw):
        return None

    async def live_runtime_handles(session):
        return set()

    monkeypatch.setattr(ns, "list_running_internal", list_running_internal)
    monkeypatch.setattr(ns, "session_ids_with_active_chat_runs", session_ids_with_active_chat_runs)
    monkeypatch.setattr(ns, "update_session_runtime", update_session_runtime)
    monkeypatch.setattr(ns, "live_runtime_handles", live_runtime_handles)

    with pytest.raises(asyncio.CancelledError):
        await loops_module.notebook_lifecycle_loop(_SessionFactory(), get_settings=lambda: _Settings())

    # The session with a live chat run was extended; the truly idle one was
    # snapshotted as before.
    assert backend.extended == ["sbx-busy"]
    assert snapshotted == ["quiet"]


@pytest.mark.asyncio
async def test_touch_run_session_pings_the_runs_notebook_session(monkeypatch):
    pinged: list[tuple[str, str]] = []

    async def get_worker_run(db, *, run_id, worker_id):
        return types.SimpleNamespace(execution_session_id="sess-1", org_id="org-1")

    async def ping_session_by_id(db, *, session_id, org_id):
        pinged.append((session_id, org_id))
        return object()

    monkeypatch.setattr(worker, "get_session_factory", lambda: _SessionFactory())
    monkeypatch.setattr(worker.chat_store, "get_worker_run", get_worker_run)
    monkeypatch.setattr(worker_events.notebook_session_store, "ping_session_by_id", ping_session_by_id)

    assert await worker_events.touch_run_session("run-1", "worker-1") is True
    assert pinged == [("sess-1", "org-1")]


@pytest.mark.asyncio
async def test_touch_run_session_is_a_noop_before_the_session_is_bound(monkeypatch):
    async def get_worker_run(db, *, run_id, worker_id):
        return types.SimpleNamespace(execution_session_id=None, org_id="org-1")

    async def ping_session_by_id(db, **kw):
        raise AssertionError("must not ping without a session")

    monkeypatch.setattr(worker, "get_session_factory", lambda: _SessionFactory())
    monkeypatch.setattr(worker.chat_store, "get_worker_run", get_worker_run)
    monkeypatch.setattr(worker_events.notebook_session_store, "ping_session_by_id", ping_session_by_id)

    assert await worker_events.touch_run_session("run-1", "worker-1") is False


@pytest.mark.asyncio
async def test_empty_answer_names_a_stopped_runtime(monkeypatch):
    async def get_worker_run(db, *, run_id, worker_id):
        return types.SimpleNamespace(execution_session_id="sess-1", org_id="org-1")

    async def get_session_internal(db, *, session_id, org_id=None):
        return types.SimpleNamespace(status="snapshotted")

    monkeypatch.setattr(worker, "get_session_factory", lambda: _SessionFactory())
    monkeypatch.setattr(worker.chat_store, "get_worker_run", get_worker_run)
    monkeypatch.setattr(worker_events.notebook_session_store, "get_session_internal", get_session_internal)

    exc = await worker_events.empty_answer_error(
        run_id="run-1", worker_id="worker-1",
        execution=types.SimpleNamespace(session_id="sess-1"),
        final_result={"result_subtype": "success", "num_turns": 0},
    )
    assert exc.public_error_code == "runtime_stopped"
    assert "stopped while the run was in progress" in str(exc)
    assert exc.diagnostic_context["notebook_session_status"] == "snapshotted"
    assert exc.diagnostic_context["num_turns"] == 0
    # The persisted (allowlisted) diagnostic keeps the explanation.
    from gateway.standalone_chat.worker_errors import public_diagnostic_context

    public = public_diagnostic_context(exc)
    assert public["notebook_session_status"] == "snapshotted"
    assert public["num_turns"] == 0


@pytest.mark.asyncio
async def test_empty_answer_with_a_running_runtime_keeps_the_generic_message(monkeypatch):
    async def get_worker_run(db, *, run_id, worker_id):
        return types.SimpleNamespace(execution_session_id="sess-1", org_id="org-1")

    async def get_session_internal(db, *, session_id, org_id=None):
        return types.SimpleNamespace(status="running")

    monkeypatch.setattr(worker, "get_session_factory", lambda: _SessionFactory())
    monkeypatch.setattr(worker.chat_store, "get_worker_run", get_worker_run)
    monkeypatch.setattr(worker_events.notebook_session_store, "get_session_internal", get_session_internal)

    exc = await worker_events.empty_answer_error(
        run_id="run-1", worker_id="worker-1",
        execution=types.SimpleNamespace(session_id="sess-1"),
        final_result={"result_subtype": "success", "stop_reason": "end_turn"},
    )
    assert exc.public_error_code is None
    assert str(exc) == "The analysis runtime returned no answer"
    assert exc.diagnostic_context["stop_reason"] == "end_turn"
