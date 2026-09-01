"""Focused worker lifecycle contracts for standalone data chat."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from gateway.standalone_chat import worker, worker_context


def test_public_error_message_preserves_root_cause_and_removes_traceback() -> None:
    error = RuntimeError(
        "CLIConnectionError: OAuth token expired\n"
        "stderr: authentication failed\n"
        "Traceback (most recent call last):\n"
        '  File "/opt/runtime/agent.py", line 42, in run\n'
        "RuntimeError: hidden implementation detail"
    )

    message = worker._public_error_message(error)

    assert message == ("CLIConnectionError: OAuth token expired\nstderr: authentication failed")
    assert "Traceback" not in message
    assert "/opt/runtime" not in message


def test_public_error_message_redacts_credentials() -> None:
    message = worker._public_error_message(RuntimeError("Database failed: postgresql://admin:hunter2@db.internal/prod"))

    assert message == "Database failed: [REDACTED_CONNECTION]"
    assert "hunter2" not in message


def test_public_full_trace_is_expandable_safe_diagnostic_content() -> None:
    error = worker._AnalysisRuntimeError(
        "CLIConnectionError: auth failed",
        full_trace=(
            "CLIConnectionError: auth failed\n"
            "Authorization: Bearer oauth-secret\n"
            "SDK token sk-ant-oat01-very-secret-token\n"
            '  File "/opt/runtime/agent.py", line 42, in run'
        ),
        diagnostic_context={
            "model": "claude-sonnet-test",
            "auth_mode": "oauth",
            "credential_present": True,
            "environment": {
                "CLAUDE_CONFIG_DIR": "configured",
                "SECRET_TOKEN": "must-not-pass",
            },
        },
    )

    trace = worker._public_full_trace(error)
    context = worker._public_diagnostic_context(error)

    assert "oauth-secret" not in trace
    assert "very-secret-token" not in trace
    assert "Authorization: Bearer [REDACTED]" in trace
    assert "/opt/runtime" not in trace
    assert context["auth_mode"] == "oauth"
    assert context["error_type"] == "CLIConnectionError"
    assert context["credential_present"] is True
    assert context["environment"] == {"CLAUDE_CONFIG_DIR": "configured"}


def test_dashboard_chart_reference_is_preloaded_into_existing_chat_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = {
        "dashboard_id": "dashboard-a",
        "dashboard_version_id": "version-a",
        "dashboard_result_id": "result-a",
        "execution_id": "execution-a",
    }
    context = {
        "conversation": SimpleNamespace(
            branch="main",
            commit_sha="a" * 40,
            internal_summary=None,
        ),
        "project": SimpleNamespace(
            id="project-a",
            name="pilot",
            display_name="Pilot",
            description=None,
            connection_name="production",
        ),
        "messages": [
            SimpleNamespace(
                role="user",
                metadata_json={"dashboard_chart_reference": reference},
            )
        ],
        "artifacts": [],
        "query_approvals": [],
        "query_proposals": [],
        "query_executions": [],
        "query_results": [],
    }
    monkeypatch.setattr(worker_context, "project_metadata_context", lambda *_args: {"models": []})

    warm = worker._warm_context(context)

    assert warm["dashboard_chart_reference"] == reference
    assert warm["project"]["commit_sha"] == "a" * 40


def test_dashboard_authoring_session_is_preloaded_for_chat_refinement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = {
        "conversation": SimpleNamespace(branch="main", commit_sha="a" * 40, internal_summary=None),
        "project": SimpleNamespace(
            id="project-a",
            name="pilot",
            display_name="Pilot",
            description=None,
            connection_name="production",
        ),
        "messages": [],
        "artifacts": [],
        "query_approvals": [],
        "query_proposals": [],
        "query_executions": [],
        "query_results": [],
        "dashboard_authoring_session": SimpleNamespace(
            id="session-a",
            dashboard_id="dashboard-a",
            definition_json={"name": "Executive dashboard"},
            draft_revision=3,
            status="preview",
        ),
    }
    monkeypatch.setattr(worker_context, "project_metadata_context", lambda *_args: {"models": []})

    warm = worker._warm_context(context)

    assert warm["dashboard_authoring"] == {
        "authoring_session_id": "session-a",
        "dashboard_id": "dashboard-a",
        "dashboard_name": "Executive dashboard",
        "draft_revision": 3,
        "status": "preview",
        "instruction": "Refine this dashboard session when the user asks for dashboard changes.",
    }


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
    completion_payloads: list[dict[str, Any]] = []
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
        yield {
            "type": "final",
            "content": "Analysis complete",
            "artifacts": [],
            "dashboard_preview": {
                "authoring_session_id": "authoring-session-1",
                "preview_url": "/dashboards/new?authoring=authoring-session-1",
                "dashboard_name": "Executive Revenue",
                "chart_count": 2,
            },
            "report_action_outcome": {
                "action": "no_suggestion",
                "artifact_kind": "report",
                "artifact_filename": "diagnostic.html",
                "reason": "One-off diagnostic.",
                "catalog_scan_complete": True,
            },
        }

    async def prepare_execution(*_args: Any, **_kwargs: Any) -> object:
        return object()

    async def complete_run(*_args: Any, **kwargs: Any) -> None:
        completed_runs.append(kwargs["run_id"])
        completion_payloads.append(kwargs)

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
    assert completion_payloads[0]["report_action_outcome"] == {
        "action": "no_suggestion",
        "artifact_kind": "report",
        "artifact_filename": "diagnostic.html",
        "reason": "One-off diagnostic.",
        "catalog_scan_complete": True,
    }
    assert completion_payloads[0]["dashboard_preview"] == {
        "authoring_session_id": "authoring-session-1",
        "preview_url": "/dashboards/new?authoring=authoring-session-1",
        "dashboard_name": "Executive Revenue",
        "chart_count": 2,
    }
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


class TestNotebookStartedPayload:
    """worker.py: notebook_started carries the ids the live panel attaches with."""

    def test_enriches_from_tool_result_and_runtime(self):
        import json

        from gateway.standalone_chat.worker import _notebook_started_payload

        payload = _notebook_started_payload(
            tool_result_content=json.dumps(
                {
                    "session_id": "s_abc123",
                    "status": "started",
                    "plan_id": "plan-1",
                    "notebook_path": "/tmp/signalpilot-chat-runs/run-1/analysis.py",
                }
            ),
            gateway_session_id="gw-sess-1",
        )
        assert payload == {
            "status": "running",
            "gateway_session_id": "gw-sess-1",
            "kernel_session_id": "s_abc123",
            "notebook_path": "/tmp/signalpilot-chat-runs/run-1/analysis.py",
        }

    def test_tolerates_non_json_tool_result(self):
        from gateway.standalone_chat.worker import _notebook_started_payload

        payload = _notebook_started_payload(
            tool_result_content="kernel started",
            gateway_session_id="gw-sess-1",
        )
        assert payload == {"status": "running", "gateway_session_id": "gw-sess-1"}

    def test_tolerates_missing_everything(self):
        from gateway.standalone_chat.worker import _notebook_started_payload

        payload = _notebook_started_payload(
            tool_result_content="",
            gateway_session_id=None,
        )
        assert payload == {"status": "running"}

    def test_extracts_ids_from_content_block_repr(self):
        """The agent SDK forwards MCP tool results as str(content_blocks) —
        a Python repr of a block list wrapping the JSON — not raw JSON."""
        from gateway.standalone_chat.worker import _notebook_started_payload

        wrapped = (
            '[TextContent(type=\'text\', text=\'{"session_id": "s_abc123", '
            '"status": "started", "plan_id": "plan-1", "cell_ids": [], '
            '"notebook_path": "/tmp/signalpilot-chat-runs/run-1/analysis.py"}\')]'
        )
        payload = _notebook_started_payload(
            tool_result_content=wrapped,
            gateway_session_id="gw-sess-1",
        )
        assert payload["kernel_session_id"] == "s_abc123"
        assert payload["notebook_path"] == "/tmp/signalpilot-chat-runs/run-1/analysis.py"

    def test_extracts_ids_from_dict_block_repr(self):
        from gateway.standalone_chat.worker import _notebook_started_payload

        wrapped = (
            "[{'type': 'text', 'text': '{\"session_id\": \"s_def456\", "
            '"notebook_path": "/tmp/signalpilot-chat-runs/run-2/analysis.py"}\'}]'
        )
        payload = _notebook_started_payload(
            tool_result_content=wrapped,
            gateway_session_id=None,
        )
        assert payload["kernel_session_id"] == "s_def456"
        assert payload["notebook_path"] == "/tmp/signalpilot-chat-runs/run-2/analysis.py"
