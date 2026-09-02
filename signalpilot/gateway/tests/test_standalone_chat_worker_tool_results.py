"""Worker contracts for tool_completed projections (worker_tool_results).

Same monkeypatch style as test_standalone_chat_worker.py; split out so both
files stay under the 600-line limit.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.db.models import GatewayBase, GatewayWorkspaceProject
from gateway.models.standalone_chat import ChatRunEventInfo
from gateway.standalone_chat import worker
from gateway.standalone_chat.tool_projection.limits import PAYLOAD_MAX
from gateway.store import standalone_chat as chat_store

_RESULT_ID = "1f0e3f4a-9c1b-4a0e-8d2e-7d0b0f7a1c11"
_QUERY_TEXT = (
    "order_id | total\n----------------\n1 | 10\n2 | 20\n\n"
    f"[2 rows, 312ms, result {_RESULT_ID}, completeness: complete]"
)


class _FakeSession:
    def __init__(self, stored: Any) -> None:
        self._stored = stored

    async def get(self, _model: Any, key: str) -> Any:
        return self._stored if self._stored is not None and self._stored.id == key else None


class _FakeSessionContext:
    def __init__(self, stored: Any = None) -> None:
        self._stored = stored

    async def __aenter__(self) -> object:
        return _FakeSession(self._stored)

    async def __aexit__(self, *_args: object) -> None:
        return None


async def _run_stream(
    monkeypatch: pytest.MonkeyPatch,
    events: list[dict[str, Any]],
    *,
    stored_result: Any = None,
) -> list[tuple[str, dict[str, Any]]]:
    """Drive _execute_claimed_run over ``events`` and return appended events."""
    appended: list[tuple[str, dict[str, Any]]] = []
    run = SimpleNamespace(
        id="run-a",
        org_id="org-a",
        user_id="user-a",
        conversation_id="conv-a",
        execution_attempt=1,
        cancellation_requested_at=None,
    )
    context = {
        "project": SimpleNamespace(connection_name="production", default_branch="main"),
        "conversation": SimpleNamespace(branch="main", commit_sha="a" * 40, internal_summary=None),
        "messages": [SimpleNamespace(role="user", content="Diagnose revenue")],
    }

    async def get_worker_run(*_args: Any, **_kwargs: Any) -> Any:
        return run

    async def worker_context(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return context

    async def stream_execution(*_args: Any, **_kwargs: Any):
        for event in events:
            yield event
        yield {"type": "final", "content": "done"}

    async def prepare_execution(*_args: Any, **_kwargs: Any) -> object:
        return SimpleNamespace(session_id="gw-sess-1")

    async def wait_until_stopped(_run_id: str, _worker_id: str, stop: Any, _worker_task: Any = None) -> None:
        await stop.wait()

    async def noop(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def append_event(_run_id: str, event_type: str, payload: dict[str, Any]) -> None:
        appended.append((event_type, payload))

    monkeypatch.setattr(worker, "get_session_factory", lambda: (lambda: _FakeSessionContext(stored_result)))
    monkeypatch.setattr(worker.chat_store, "get_worker_run", get_worker_run)
    monkeypatch.setattr(worker.chat_store, "worker_context", worker_context)
    monkeypatch.setattr(worker.chat_store, "complete_run", noop)
    monkeypatch.setattr(worker.chat_store, "fail_run", noop)
    monkeypatch.setattr(worker.chat_store, "set_conversation_notebook_for_run", noop)
    monkeypatch.setattr(worker, "prepare_execution", prepare_execution)
    monkeypatch.setattr(worker, "stream_execution", stream_execution)
    monkeypatch.setattr(worker, "_warm_context", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(worker, "_append", append_event)
    monkeypatch.setattr(worker, "_lease_renewer", wait_until_stopped)
    monkeypatch.setattr(worker, "_cancellation_monitor", wait_until_stopped)
    monkeypatch.setattr(worker, "cleanup_finished_execution", noop)

    await worker._execute_claimed_run("run-a", "worker-a")
    return appended


def _completed(appended: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    return [payload for event_type, payload in appended if event_type == "tool_completed"]


def _query_events(*, is_error: bool = False, content: str = _QUERY_TEXT) -> list[dict[str, Any]]:
    return [
        {
            "type": "tool_use",
            "tool_name": "mcp__signalpilot__query_database",
            "tool_call_id": "call-1",
            "tool_input": {"sql": "select 1", "connection_name": "production"},
        },
        {"type": "tool_result", "tool_call_id": "call-1", "content": content, "is_error": is_error},
    ]


@pytest.mark.asyncio
async def test_query_database_result_is_projected_as_parsed_table(monkeypatch: pytest.MonkeyPatch) -> None:
    appended = await _run_stream(monkeypatch, _query_events())

    (payload,) = _completed(appended)
    assert payload["tool"] == "mcp__signalpilot__query_database"
    assert payload["tool_call_id"] == "call-1" and payload["error"] is False
    assert payload["summary"] == "2 rows · 312 ms"
    assert payload["v"] == 1 and payload["truncated"] is False
    table = payload["result"]
    assert table["kind"] == "table" and table["result_id"] == _RESULT_ID
    # No stored row for this id: the parsed preview stays (fallback path).
    assert table["source"] == "parsed" and table["rows"] == [[1, 10], [2, 20]]
    assert payload["result_text"] == _QUERY_TEXT and payload["result_chars"] == len(_QUERY_TEXT)


@pytest.mark.asyncio
async def test_query_database_result_is_enriched_from_structured_result(monkeypatch: pytest.MonkeyPatch) -> None:
    stored = SimpleNamespace(
        id=_RESULT_ID,
        run_id="run-a",
        org_id="org-a",
        execution_id="exec-1",
        columns_json=[{"name": "order_id", "logical_type": "integer"}, {"name": "total", "logical_type": "number"}],
        preview_rows_json=[{"order_id": 1, "total": 10.0}, {"order_id": 2, "total": {"nested": "x" * 300}}],
        saved_row_count=1204,
        query_row_count=1204,
        result_completeness="complete",
        truncation_reason=None,
    )
    appended = await _run_stream(monkeypatch, _query_events(), stored_result=stored)

    (payload,) = _completed(appended)
    table = payload["result"]
    assert table["source"] == "structured" and table["execution_id"] == "exec-1"
    assert table["columns"] == [
        {"name": "order_id", "logical_type": "integer"},
        {"name": "total", "logical_type": "number"},
    ]
    assert table["rows"][0] == [1, 10.0]
    assert isinstance(table["rows"][1][1], str) and len(table["rows"][1][1]) == 201
    assert table["row_count"] == 1204 and table["preview_truncated"] is True
    assert table["completeness"] == "complete"


@pytest.mark.asyncio
async def test_structured_result_from_another_run_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    stored = SimpleNamespace(id=_RESULT_ID, run_id="run-other", org_id="org-a")
    appended = await _run_stream(monkeypatch, _query_events(), stored_result=stored)

    (payload,) = _completed(appended)
    assert payload["result"]["source"] == "parsed"


@pytest.mark.asyncio
async def test_tool_error_summary_is_sanitized_not_the_placeholder(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = "Query error: postgresql://admin:hunter2@db.internal/prod refused"
    appended = await _run_stream(monkeypatch, _query_events(is_error=True, content=raw))

    (payload,) = _completed(appended)
    assert payload["error"] is True
    assert payload["summary"] != "The tool returned an error."
    assert payload["summary"].startswith("Query error:")
    assert "hunter2" not in json.dumps(payload)
    assert payload["result"] == {"kind": "text"}


@pytest.mark.asyncio
async def test_notebook_cell_and_agent_side_effects_are_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    notebook_reply = json.dumps(
        {"session_id": "s_abc", "status": "started", "notebook_path": "/w/analysis.py", "notebook": "analysis"}
    )
    events = [
        {
            "type": "tool_use",
            "tool_name": "mcp__signalpilot-notebook__start_analysis_notebook",
            "tool_call_id": "nb-1",
            "tool_input": {},
        },
        {"type": "tool_result", "tool_call_id": "nb-1", "content": notebook_reply},
        {
            "type": "tool_use",
            "tool_name": "mcp__signalpilot-notebook__run_cells",
            "tool_call_id": "cells-1",
            "tool_input": {"cell_ids": ["c1"]},
        },
        {"type": "tool_result", "tool_call_id": "cells-1", "content": "", "is_error": True},
        {"type": "tool_use", "tool_name": "Agent", "tool_call_id": "agent-1", "tool_input": {"prompt": "x"}},
        {"type": "tool_result", "tool_call_id": "agent-1", "content": "final report " + "z" * 5000},
    ]
    appended = await _run_stream(monkeypatch, events)

    types = [event_type for event_type, _ in appended]
    assert types.count("notebook_started") == 1
    notebook_started = next(payload for event_type, payload in appended if event_type == "notebook_started")
    assert notebook_started == {
        "status": "running",
        "gateway_session_id": "gw-sess-1",
        "kernel_session_id": "s_abc",
        "notebook_path": "/w/analysis.py",
        "notebook": "analysis",
    }
    assert ("cell_executed", {"status": "failed"}) in appended
    completed = _completed(appended)
    assert completed[0]["summary"] == "Notebook started" and completed[0]["result"]["kind"] == "artifact"
    assert completed[1]["error"] is True
    agent = completed[2]
    assert agent["report"].startswith("final report") and len(agent["report"]) == 4000


@pytest.mark.asyncio
async def test_subagent_results_keep_parent_tool_call_id(monkeypatch: pytest.MonkeyPatch) -> None:
    events = [
        {
            "type": "tool_use",
            "tool_name": "mcp__signalpilot__validate_sql",
            "tool_call_id": "child-1",
            "tool_input": {"sql": "select 1"},
            "parent_tool_call_id": "agent-1",
        },
        {
            "type": "tool_result",
            "tool_call_id": "child-1",
            "content": "VALID ✓\nEstimated rows: 12,000",
            "parent_tool_call_id": "agent-1",
        },
    ]
    appended = await _run_stream(monkeypatch, events)

    (payload,) = _completed(appended)
    assert payload["parent_tool_call_id"] == "agent-1"
    assert payload["summary"] == "Valid · ~12,000 rows"
    assert payload["result"]["kind"] == "validation" and payload["result"]["valid"] is True


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_replayed_tool_completed_is_redacted_and_valid(db_session: AsyncSession) -> None:
    project = GatewayWorkspaceProject(
        id="project-a",
        org_id="org-a",
        name="revenue",
        display_name="Revenue",
        description="Revenue analytics",
        connection_name="production",
        source="managed",
        status="active",
        settings={},
        file_count=0,
        total_bytes=0,
        default_branch="main",
        created_at=1.0,
        updated_at=1.0,
    )
    db_session.add(project)
    await db_session.commit()
    _, run = await chat_store.create_conversation_with_run(
        db_session,
        org_id="org-a",
        user_id="user-a",
        project=project,
        branch="main",
        message="What changed?",
        commit_sha="a" * 40,
    )
    from gateway.standalone_chat.tool_projection import finalize_payload, project_tool_result

    leaked = "dsn | n\n-------\npostgres://u:p@h/db | 1\n\n" f"[1 rows, 5ms, result {_RESULT_ID}, completeness: complete]"
    projected = project_tool_result("mcp__signalpilot__query_database", leaked)
    payload = finalize_payload(
        {
            "tool_call_id": "call-1",
            "tool": "mcp__signalpilot__query_database",
            "error": False,
            "summary": projected.summary,
            "result": projected.result,
            "result_text": projected.result_text,
            "result_chars": projected.result_chars,
            "truncated": projected.truncated,
            "v": 1,
        }
    )
    assert payload["result"]["rows"][0][0] == "postgres://u:p@h/db"

    await chat_store.append_event(db_session, run_id=run.id, event_type="tool_completed", payload=payload)
    replayed = await chat_store.list_run_events(db_session, org_id="org-a", user_id="user-a", run_id=run.id)

    assert replayed is not None and len(replayed) == 1
    event = ChatRunEventInfo.model_validate(replayed[0].model_dump())
    assert event.type == "tool_completed"
    assert event.payload["result"]["rows"][0][0] == "[REDACTED_CONNECTION]"
    assert "postgres://" not in json.dumps(event.payload)
    assert len(json.dumps(event.payload, separators=(",", ":")).encode()) <= PAYLOAD_MAX
