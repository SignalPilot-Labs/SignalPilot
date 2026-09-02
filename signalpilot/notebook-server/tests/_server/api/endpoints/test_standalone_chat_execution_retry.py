"""Recovery, retry, and archive fallback paths of the execute stream.

Split from test_standalone_chat_execution.py to keep each file under
600 lines. Shared helpers and the JWT fixture are imported from there.
"""

from __future__ import annotations

import base64
import json
import sys
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Self

import httpx
import pytest

from signalpilot._config.settings import GLOBAL_SETTINGS
from signalpilot._server.ai.claude_agent import AgentEvent
from signalpilot._server.api.endpoints import (
    standalone_chat_execution as standalone_chat,
    standalone_chat_runtime as chat_runtime,
    standalone_chat_workspace as chat_workspace,
)
from signalpilot._utils import requests
from signalpilot._utils.requests import RequestError

# The autouse JWT fixture must be in this module's namespace to apply here.
from tests._server.api.endpoints.test_standalone_chat_execution import (
    _request,
    _runtime_session,
    _scoped_token,
    _session_jwt_secret,  # noqa: F401
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "export_error",
    [
        FileNotFoundError("frontend index missing"),
        RequestError("network unavailable"),
    ],
    ids=["missing-assets", "http-failure"],
)
async def test_archive_uses_safe_fallback_when_frontend_export_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    export_error: Exception,
) -> None:
    scoped_token = "runtime-secret-token"
    cell_id = "cell-a"
    app = SimpleNamespace(
        to_py=lambda: "answer = 1",
        cell_manager=SimpleNamespace(
            cell_data=lambda: [
                SimpleNamespace(cell_id=cell_id, code="answer = 1")
            ]
        ),
    )
    session = SimpleNamespace(
        app_file_manager=SimpleNamespace(app=app),
        config_manager=SimpleNamespace(get_config=lambda: {"display": {}}),
        session_view=SimpleNamespace(
            cell_notifications={
                cell_id: SimpleNamespace(
                    status="idle",
                    output=SimpleNamespace(
                        mimetype="text/html",
                        data=f"<script>{scoped_token}</script><b>safe result</b>",
                    ),
                )
            }
        ),
    )
    captured: dict[str, Any] = {}

    class MissingAssetsExporter:
        def export_as_html(self, **_kwargs: Any) -> tuple[str, str]:
            raise export_error

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"archive_id": "archive-fallback"}

    class FakeClient:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def post(self, _url: str, **kwargs: Any) -> FakeResponse:
            captured.update(kwargs["json"])
            return FakeResponse()

    monkeypatch.setattr(
        chat_runtime,
        "_analysis_session",
        lambda _app, _session_id: session,
    )
    monkeypatch.setitem(
        sys.modules,
        "signalpilot._server.export.exporter",
        SimpleNamespace(Exporter=MissingAssetsExporter),
    )
    monkeypatch.setitem(
        sys.modules,
        "signalpilot._server.models.export",
        SimpleNamespace(ExportAsHTMLRequest=lambda **kwargs: kwargs),
    )
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    archive_id = await chat_runtime._archive_analysis_notebook(
        app=object(),
        session_id="session-a",
        run_id="run-fallback",
        gateway_api_url="http://gateway:3300",
        scoped_token=scoped_token,
    )
    archived_html = base64.b64decode(captured["html_base64"]).decode()
    archived_source = base64.b64decode(captured["source_base64"]).decode()

    assert archive_id == "archive-fallback"
    assert "Validated analysis notebook" in archived_html
    assert "&lt;script&gt;[REDACTED]&lt;/script&gt;" in archived_html
    assert scoped_token not in archived_html
    assert "answer = 1" not in archived_html
    assert archived_source == "answer = 1"


@pytest.mark.asyncio
async def test_validated_retry_survives_offline_development_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = "run-retry-1234"
    project_id = "1dbf5492-81e6-4683-835f-f1785c9cfe78"
    commit_sha = "a" * 40
    app = SimpleNamespace()
    sessions: dict[str, Any] = {}
    lifecycles: list[Any] = []
    collectors: list[Any] = []
    seeded_paths: list[Path] = []
    event_sinks: list[Any] = []
    closed: list[str] = []
    cleared: list[str] = []
    archived: dict[str, Any] = {}
    clean_starts: list[Path] = []
    agent_attempts = 0

    async def execution_directory(**_kwargs: Any) -> tuple[Path, bool]:
        return tmp_path, False

    def build_server(collector: Any, **kwargs: Any) -> object:
        collectors.append(collector)
        lifecycles.append(kwargs["notebook_lifecycle"])
        seeded_paths.append(kwargs["analysis_notebook_path"])
        event_sinks.append(kwargs["event_sink"])
        return object()

    async def run_agent(prompt: str, _session_id: object, **_kwargs: Any):
        nonlocal agent_attempts
        agent_attempts += 1
        attempt = agent_attempts
        lifecycle = lifecycles[-1]
        if attempt == 1:
            lifecycle.session_id = "kernel-1"
            sessions[lifecycle.session_id] = _runtime_session(dirty=True)
            sessions[lifecycle.session_id]._signalpilot_notebook_failures = [
                {
                    "error": {
                        "type": "MultipleDefinitionError",
                        "variable": "segment",
                        "cell_ids": ["summary", "chart"],
                    }
                },
                {
                    "error": {
                        "type": "SpExceptionRaisedError",
                        "variable": None,
                        "cell_ids": ["output"],
                    }
                },
            ]
        else:
            assert lifecycle.session_id == "kernel-2"
        await event_sinks[-1]("notebook_started", {})
        if attempt == 1:
            seeded_paths[-1].write_text("corrupted notebook", encoding="utf-8")
            yield AgentEvent(type="text_delta", content="REJECTED LEAK")
            yield AgentEvent(type="text", content="Rejected answer")
            return
        assert "corrupted notebook" not in seeded_paths[-1].read_text(
            encoding="utf-8"
        )
        assert "notebook_recovery" in prompt
        assert "MultipleDefinitionError" in prompt
        assert '"variable": "segment"' in prompt
        assert "SpExceptionRaisedError" in prompt
        assert "session_id `kernel-2`" in prompt
        assert "Plan each database query before executing it" in prompt
        yield AgentEvent(
            type="tool_use",
            tool_name="mcp__signalpilot-notebook__run_cells",
            tool_call_id="run-cells-2",
        )
        yield AgentEvent(
            type="tool_result",
            tool_call_id="run-cells-2",
            is_error=False,
        )
        yield AgentEvent(type="text_delta", content="Accepted streamed text")
        yield AgentEvent(type="text", content="Accepted answer")

    class FakeArchiveResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"archive_id": "archive-clean"}

    class FakeArchiveClient:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def post(self, _url: str, **kwargs: Any) -> FakeArchiveResponse:
            archived.update(kwargs["json"])
            return FakeArchiveResponse()

    class OfflineExporter:
        def export_as_html(self, **_kwargs: Any) -> tuple[str, str]:
            raise RequestError("network unavailable")

    monkeypatch.setenv("SP_CHAT_SCRATCH_ROOT", str(tmp_path / "scratch"))
    monkeypatch.setattr(GLOBAL_SETTINGS, "DEVELOPMENT_MODE", True)
    monkeypatch.setattr(
        requests,
        "get",
        lambda *_args, **_kwargs: pytest.fail(
            "development archive attempted a network request"
        ),
    )
    monkeypatch.setattr(httpx, "AsyncClient", FakeArchiveClient)
    monkeypatch.setitem(
        sys.modules,
        "signalpilot._server.export.exporter",
        SimpleNamespace(Exporter=OfflineExporter),
    )
    monkeypatch.setitem(
        sys.modules,
        "signalpilot._server.models.export",
        SimpleNamespace(ExportAsHTMLRequest=lambda **kwargs: kwargs),
    )
    monkeypatch.setattr(
        chat_workspace, "_execution_project_directory", execution_directory
    )
    monkeypatch.setattr(
        standalone_chat, "build_standalone_chat_mcp_server", build_server
    )
    monkeypatch.setattr(standalone_chat, "run_notebook_agent", run_agent)
    monkeypatch.setattr(
        chat_runtime,
        "_analysis_session",
        lambda _app, session_id: sessions[session_id],
    )
    monkeypatch.setattr(
        standalone_chat,
        "_analysis_session",
        lambda _app, session_id: sessions[session_id],
    )
    monkeypatch.setattr(
        standalone_chat,
        "_close_analysis_kernel",
        lambda _app, session_id: closed.append(session_id) or True,
    )
    monkeypatch.setattr(
        standalone_chat,
        "_start_analysis_kernel",
        lambda _app, notebook_path: (
            clean_starts.append(notebook_path),
            sessions.setdefault("kernel-2", _runtime_session()),
            "kernel-2",
        )[-1],
    )
    monkeypatch.setattr(
        standalone_chat, "_project_is_unchanged", lambda *_args: True
    )
    monkeypatch.setattr(
        standalone_chat,
        "clear_chat_session",
        lambda session_id, **_kwargs: cleared.append(session_id),
    )

    token = _scoped_token(
        run_id=run_id,
        project_id=project_id,
        commit_sha=commit_sha,
    )
    response = await standalone_chat.execute(
        request=_request(
            {
                "run_id": run_id,
                "project_id": project_id,
                "branch": "main",
                "connection_name": "production",
                "commit_sha": commit_sha,
                "gateway_session_token": token,
                "prompt": "Analyze revenue",
            },
            app=app,
        )
    )
    events = [
        json.loads(line)
        for line in (
            b"".join([chunk async for chunk in response.body_iterator])
        ).splitlines()
    ]

    assert [event["type"] for event in events] == [
        "text_delta",
        "progress",
        "notebook_started",
        "tool_use",
        "tool_result",
        "text_delta",
        "final",
    ]
    assert events[1]["content"] == "Restarting analysis in a clean notebook"
    assert events[-1] == {
        "archive_id": "archive-clean",
        "content": "Accepted answer",
        # The validated kernel is kept ALIVE after the run for the chat
        # page's live notebook panel; only the rejected attempt's kernel
        # closes.
        "kernel_stopped": False,
        "type": "final",
    }
    # Narration streams live (including from the rejected attempt), but the
    # accepted answer is built only from the validated attempt's text blocks.
    assert events[0]["content"] == "REJECTED LEAK"
    assert "REJECTED LEAK" not in events[-1]["content"]
    assert closed == ["kernel-1"]
    assert clean_starts == [seeded_paths[0]]
    archived_html = base64.b64decode(archived["html_base64"]).decode()
    assert "Validated analysis notebook" in archived_html
    assert "answer = 1" not in archived_html
    assert cleared.count(f"standalone:{run_id}") >= 2


@pytest.mark.asyncio
async def test_two_dirty_attempts_emit_one_validation_error_and_no_final(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = "run-dirty-1234"
    project_id = "1dbf5492-81e6-4683-835f-f1785c9cfe78"
    commit_sha = "b" * 40
    sessions: dict[str, Any] = {}
    lifecycles: list[Any] = []
    event_sinks: list[Any] = []
    archive_calls: list[bool] = []
    agent_attempts = 0

    async def execution_directory(**_kwargs: Any) -> tuple[Path, bool]:
        return tmp_path, False

    def build_server(_collector: Any, **kwargs: Any) -> object:
        lifecycles.append(kwargs["notebook_lifecycle"])
        event_sinks.append(kwargs["event_sink"])
        return object()

    async def run_agent(_prompt: str, _session_id: object, **_kwargs: Any):
        nonlocal agent_attempts
        agent_attempts += 1
        attempt = agent_attempts
        lifecycle = lifecycles[-1]
        if attempt == 1:
            lifecycle.session_id = "dirty-kernel-1"
            sessions[lifecycle.session_id] = _runtime_session(dirty=True)
        else:
            assert lifecycle.session_id == "dirty-kernel-2"
        await event_sinks[-1]("notebook_started", {})
        if attempt == 2:
            yield AgentEvent(
                type="tool_use",
                tool_name="mcp__signalpilot-notebook__run_cells",
                tool_call_id="run-cells-2",
            )
            yield AgentEvent(
                type="tool_result",
                tool_call_id="run-cells-2",
                is_error=False,
            )
        yield AgentEvent(type="text_delta", content=f"dirty answer {attempt}")
        yield AgentEvent(type="text", content=f"Dirty answer {attempt}")

    async def archive(**_kwargs: Any) -> str:
        archive_calls.append(True)
        return "unexpected"

    monkeypatch.setenv("SP_CHAT_SCRATCH_ROOT", str(tmp_path / "scratch"))
    monkeypatch.setattr(
        chat_workspace, "_execution_project_directory", execution_directory
    )
    monkeypatch.setattr(
        standalone_chat, "build_standalone_chat_mcp_server", build_server
    )
    monkeypatch.setattr(standalone_chat, "run_notebook_agent", run_agent)
    monkeypatch.setattr(
        chat_runtime,
        "_analysis_session",
        lambda _app, session_id: sessions[session_id],
    )
    monkeypatch.setattr(
        standalone_chat,
        "_analysis_session",
        lambda _app, session_id: sessions[session_id],
    )
    monkeypatch.setattr(
        standalone_chat,
        "_close_analysis_kernel",
        lambda _app, _session_id: True,
    )
    monkeypatch.setattr(
        standalone_chat,
        "_start_analysis_kernel",
        lambda _app, _notebook_path: (
            sessions.setdefault(
                "dirty-kernel-2", _runtime_session(dirty=True)
            ),
            "dirty-kernel-2",
        )[-1],
    )
    monkeypatch.setattr(standalone_chat, "_archive_analysis_notebook", archive)
    monkeypatch.setattr(
        standalone_chat, "_project_is_unchanged", lambda *_args: True
    )
    monkeypatch.setattr(
        standalone_chat, "clear_chat_session", lambda *_args, **_kwargs: None
    )

    token = _scoped_token(
        run_id=run_id,
        project_id=project_id,
        commit_sha=commit_sha,
    )
    response = await standalone_chat.execute(
        request=_request(
            {
                "run_id": run_id,
                "project_id": project_id,
                "branch": "main",
                "connection_name": "production",
                "commit_sha": commit_sha,
                "gateway_session_token": token,
                "prompt": "Analyze revenue",
            },
            app=SimpleNamespace(),
        )
    )
    events = [
        json.loads(line)
        for line in (
            b"".join([chunk async for chunk in response.body_iterator])
        ).splitlines()
    ]

    assert [event["type"] for event in events] == [
        "text_delta",
        "progress",
        "notebook_started",
        "tool_use",
        "tool_result",
        "text_delta",
        "error",
    ]
    assert events[-1] == {
        "content": "Notebook validation failed after one clean retry; the answer was rejected.",
        "is_error": True,
        "type": "error",
    }
    # Narration may stream, but a rejected run never emits an accepted answer.
    assert all(event["type"] not in {"final", "text"} for event in events)
    assert archive_calls == []
