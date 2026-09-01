"""Multi-notebook contracts for the standalone chat runtime."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from mcp.types import CallToolRequest, CallToolRequestParams, TextContent
from starlette.requests import Request

from signalpilot._server.ai.claude_agent import AgentEvent
from signalpilot._server.ai.standalone_chat_tools import (
    StandaloneArtifactCollector,
    StandaloneNotebookLifecycle,
    build_standalone_chat_mcp_server,
)
from signalpilot._server.api.endpoints import (
    standalone_chat_cancel as chat_cancel,
    standalone_chat_execution as standalone_chat,
    standalone_chat_runtime as chat_runtime,
    standalone_chat_workspace as chat_workspace,
)
from tests._server.api.endpoints.test_standalone_chat_execution import (
    _TEST_JWT_SECRET,
    _request,
    _runtime_session,
    _scoped_token,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _session_jwt_secret(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SP_SESSION_JWT_SECRET", _TEST_JWT_SECRET)
    monkeypatch.setenv(
        "SP_CHAT_CLAUDE_STATE_ROOT",
        str(tmp_path / "claude-sessions"),
    )


def test_named_seed_writes_minimal_template_in_the_shared_scratch(
    tmp_path: Path,
) -> None:
    analysis = chat_runtime._seed_analysis_notebook(
        scratch=tmp_path,
        run_id="run-a",
        project_id="project-a",
        connection_name="warehouse-a",
        gateway_url="http://gateway:3300",
        scoped_token="token-a-secret",
    )
    report = chat_runtime._seed_notebook_file(
        scratch=tmp_path,
        name="report",
        run_id="run-a",
        project_id="project-a",
        connection_name="warehouse-a",
        gateway_url="http://gateway:3300",
    )

    assert analysis == tmp_path / "analysis.py"
    assert report == tmp_path / "report.py"
    report_source = report.read_text(encoding="utf-8")
    analysis_source = analysis.read_text(encoding="utf-8")
    # Both share the context and sp.init setup cells and the run token file.
    for source in (report_source, analysis_source):
        assert "sp.init(gateway_url=" in source
        assert ".gateway-token" in source
        assert "token-a-secret" not in source
    # The named notebook path points at its own file.
    assert repr(str(tmp_path / "report.py")) in report_source
    # Only analysis gets the scaffold; the named notebook gets one visible
    # empty cell.
    assert "analysis_summary" in analysis_source
    assert "analysis_summary" not in report_source
    assert "analysis_checks" not in report_source
    assert "@app.cell\ndef _():\n    return" in report_source


@pytest.mark.asyncio
async def test_start_tool_named_notebook_starts_a_distinct_lazy_session(
    tmp_path: Path,
) -> None:
    seeded = tmp_path / "analysis.py"
    seeded.write_text("import marimo\n", encoding="utf-8")
    session_ids = iter(["session-analysis", "session-report"])
    started_paths: list[str] = []

    def start_notebook(
        _context: Any, arguments: dict[str, Any]
    ) -> list[TextContent]:
        started_paths.append(arguments["file_path"])
        return [
            TextContent(
                type="text",
                text=json.dumps({"session_id": next(session_ids)}),
            )
        ]

    seeds: list[str] = []

    def seeder(name: str) -> Path:
        path = tmp_path / f"{name}.py"
        path.write_text("import marimo\n", encoding="utf-8")
        seeds.append(name)
        return path

    lifecycle = StandaloneNotebookLifecycle()
    server = build_standalone_chat_mcp_server(
        StandaloneArtifactCollector(),
        notebook_mcp_app=object(),
        analysis_notebook_path=seeded,
        notebook_lifecycle=lifecycle,
        notebook_starter=start_notebook,
        notebook_session_resolver=lambda _session_id: SimpleNamespace(),
        notebook_seeder=seeder,
    )["instance"]

    async def call(arguments: dict[str, Any]) -> Any:
        return await server.request_handlers[CallToolRequest](
            CallToolRequest(
                params=CallToolRequestParams(
                    name="start_analysis_notebook",
                    arguments=arguments,
                )
            )
        )

    first = json.loads((await call({})).root.content[0].text)
    assert first["notebook"] == "analysis"
    assert first["session_id"] == "session-analysis"

    second_response = await call({"notebook": "report"})
    assert second_response.root.isError is False
    second = json.loads(second_response.root.content[0].text)
    assert second["notebook"] == "report"
    assert second["session_id"] == "session-report"
    assert second["notebook_path"] == str(tmp_path / "report.py")
    # The report file was seeded lazily in the SAME scratch.
    assert seeds == ["report"]
    assert started_paths == [str(seeded), str(tmp_path / "report.py")]
    assert lifecycle.sessions == {
        "analysis": "session-analysis",
        "report": "session-report",
    }

    # The execution route authorizes by set membership over the run's
    # kernels; both live sessions pass, a foreign one does not.
    def authorize(candidate: str) -> bool:
        return candidate in lifecycle.sessions.values()

    assert authorize("session-analysis")
    assert authorize("session-report")
    assert not authorize("session-other")

    # already_running is per notebook name.
    again = json.loads((await call({"notebook": "report"})).root.content[0].text)
    assert again["status"] == "already_running"
    assert again["notebook"] == "report"
    assert again["session_id"] == "session-report"

    invalid = await call({"notebook": "Bad Name"})
    assert invalid.root.isError is True


def test_partial_adoption_drops_only_the_dead_kernel_without_rmtree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scratch = tmp_path / "conversation"
    scratch.mkdir()
    (scratch / "analysis.py").write_text("a", encoding="utf-8")
    (scratch / "report.py").write_text("b", encoding="utf-8")
    closed: list[str] = []

    def analysis_session(_app: Any, session_id: str) -> Any:
        if session_id == "kernel-report":
            raise KeyError(session_id)
        return SimpleNamespace()

    monkeypatch.setattr(chat_runtime, "_analysis_session", analysis_session)
    monkeypatch.setattr(
        chat_runtime,
        "_close_analysis_kernel",
        lambda _app, session_id: closed.append(session_id) or True,
    )

    chat_runtime.register_keepalive_analysis_session(
        conversation_id="conversation-1",
        sessions={"analysis": "kernel-analysis", "report": "kernel-report"},
        scratch=scratch,
    )
    assert not (scratch / ".gateway-token").exists()

    adopted = chat_runtime.adopt_keepalive_analysis_session(
        object(), "conversation-1", scoped_token="fresh-token"
    )
    assert adopted is not None
    adopted_scratch, alive = adopted
    assert adopted_scratch == scratch
    assert alive == {"analysis": "kernel-analysis"}
    assert closed == ["kernel-report"]
    # The scratch survives while any kernel is alive; the token is rewritten
    # once for the adopting run.
    assert scratch.is_dir()
    assert (scratch / ".gateway-token").read_text(
        encoding="utf-8"
    ) == "fresh-token"

    # When every kernel is dead the whole keepalive is cleaned up.
    monkeypatch.setattr(
        chat_runtime,
        "_analysis_session",
        lambda _app, session_id: (_ for _ in ()).throw(KeyError(session_id)),
    )
    chat_runtime.register_keepalive_analysis_session(
        conversation_id="conversation-1",
        sessions={"analysis": "kernel-analysis"},
        scratch=scratch,
    )
    assert (
        chat_runtime.adopt_keepalive_analysis_session(
            object(), "conversation-1", scoped_token="fresh-token"
        )
        is None
    )
    assert not scratch.exists()
    assert "conversation-1" not in chat_runtime._KEEPALIVE_BY_CONVERSATION


@pytest.mark.asyncio
async def test_cancel_closes_every_kernel_of_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from starlette.authentication import AuthCredentials, SimpleUser

    run_id = "run-33333333"
    closed: list[str] = []
    monkeypatch.setattr(chat_cancel, "stop_agent", lambda _session: True)
    monkeypatch.setattr(
        chat_cancel,
        "_close_analysis_kernel",
        lambda _app, session_id: closed.append(session_id) or True,
    )
    chat_runtime._ANALYSIS_SESSIONS_BY_RUN[run_id] = {
        "kernel-analysis",
        "kernel-report",
    }

    response = await chat_cancel.cancel(
        request=Request(
            {
                "type": "http",
                "method": "POST",
                "path": f"/api/standalone-chat/cancel/{run_id}",
                "path_params": {"run_id": run_id},
                "headers": [],
                "app": object(),
                "auth": AuthCredentials(["edit"]),
                "user": SimpleUser("test-user"),
            }
        )
    )

    assert json.loads(response.body) == {
        "stopped": True,
        "kernel_stopped": True,
    }
    assert set(closed) == {"kernel-analysis", "kernel-report"}
    assert run_id not in chat_runtime._ANALYSIS_SESSIONS_BY_RUN


@pytest.mark.asyncio
async def test_run_archives_each_notebook_and_gates_only_the_analysis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dirty, edited-but-never-run report notebook must not reject the run,
    its archive failure must not fail the run, and it stays kept alive."""
    run_id = "run-multi-0001"
    project_id = "1dbf5492-81e6-4683-835f-f1785c9cfe78"
    commit_sha = "d" * 40
    sessions: dict[str, Any] = {
        "kernel-analysis": _runtime_session(),
        "kernel-report": _runtime_session(dirty=True),
    }
    lifecycles: list[Any] = []
    event_sinks: list[Any] = []
    archives: list[tuple[str, str]] = []
    registered: dict[str, Any] = {}

    async def execution_directory(**_kwargs: Any) -> tuple[Path, bool]:
        return tmp_path, False

    def build_server(_collector: Any, **kwargs: Any) -> object:
        lifecycles.append(kwargs["notebook_lifecycle"])
        event_sinks.append(kwargs["event_sink"])
        return object()

    async def run_agent(_prompt: str, _session_id: object, **kwargs: Any):
        lifecycle = lifecycles[-1]
        lifecycle.sessions["analysis"] = "kernel-analysis"
        await event_sinks[-1](
            "notebook_started",
            {"notebook": "analysis", "session_id": "kernel-analysis"},
        )
        lifecycle.sessions["report"] = "kernel-report"
        await event_sinks[-1](
            "notebook_started",
            {"notebook": "report", "session_id": "kernel-report"},
        )
        authorize = kwargs["notebook_session_authorizer"]
        assert authorize("kernel-analysis")
        assert authorize("kernel-report")
        assert not authorize("kernel-other")
        # Edit ONLY the report notebook and never run cells. The analysis
        # evidence gate must not trip on another notebook's edits.
        yield AgentEvent(
            type="tool_use",
            tool_name="mcp__signalpilot-notebook__edit_notebook",
            tool_call_id="edit-report-1",
            tool_input={"session_id": "kernel-report"},
        )
        yield AgentEvent(
            type="tool_result",
            tool_call_id="edit-report-1",
            is_error=False,
        )
        yield AgentEvent(type="text", content="Multi-notebook answer")

    async def archive(**kwargs: Any) -> str:
        archives.append((kwargs["notebook_name"], kwargs["session_id"]))
        if kwargs["notebook_name"] != "analysis":
            raise RuntimeError("report archive offline")
        return "archive-analysis"

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
    monkeypatch.setattr(standalone_chat, "_archive_analysis_notebook", archive)
    monkeypatch.setattr(
        standalone_chat,
        "register_keepalive_analysis_session",
        lambda **kwargs: registered.update(kwargs),
    )
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

    final = events[-1]
    assert final["type"] == "final"
    assert final["content"] == "Multi-notebook answer"
    assert final["archive_id"] == "archive-analysis"
    assert final["kernel_stopped"] is False
    # Analysis archives first; the report archive failure logs and continues.
    assert archives == [
        ("analysis", "kernel-analysis"),
        ("report", "kernel-report"),
    ]
    # Both kernels register for keepalive despite the report archive failure.
    assert registered["sessions"] == {
        "analysis": "kernel-analysis",
        "report": "kernel-report",
    }
    assert run_id not in chat_runtime._ANALYSIS_SESSIONS_BY_RUN


def _patch_execution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    resolver: Any,
    closed: list[str],
    captured: dict[str, Any],
    run_agent: Any,
) -> None:
    async def execution_directory(**_kwargs: Any) -> tuple[Path, bool]:
        return tmp_path, False

    def build_server(_collector: Any, **kwargs: Any) -> object:
        captured["lifecycle"] = kwargs["notebook_lifecycle"]
        captured["event_sink"] = kwargs["event_sink"]
        return object()

    def close_kernel(_app: Any, session_id: str) -> bool:
        return bool(closed.append(session_id)) or True

    monkeypatch.setenv("SP_CHAT_SCRATCH_ROOT", str(tmp_path / "scratch"))
    sa = monkeypatch.setattr
    sa(chat_workspace, "_execution_project_directory", execution_directory)
    sa(standalone_chat, "build_standalone_chat_mcp_server", build_server)
    sa(standalone_chat, "run_notebook_agent", run_agent)
    sa(chat_runtime, "_analysis_session", resolver)
    sa(standalone_chat, "_analysis_session", resolver)
    sa(standalone_chat, "_close_analysis_kernel", close_kernel)
    sa(standalone_chat, "_project_is_unchanged", lambda *_args: True)
    sa(standalone_chat, "clear_chat_session", lambda *_a, **_k: None)


def _execute_body(run_id: str, **extra: Any) -> dict[str, Any]:
    project_id = "1dbf5492-81e6-4683-835f-f1785c9cfe78"
    commit_sha = extra.pop("commit_sha", "e" * 40)
    return {
        "run_id": run_id,
        "project_id": project_id,
        "branch": "main",
        "connection_name": "production",
        "commit_sha": commit_sha,
        "gateway_session_token": _scoped_token(
            run_id=run_id, project_id=project_id, commit_sha=commit_sha
        ),
        "prompt": "Analyze revenue",
        **extra,
    }


@pytest.mark.asyncio
async def test_start_tool_rejects_traversal_and_bad_slugs(
    tmp_path: Path,
) -> None:
    """The server-side slug gate is the only defense for scratch/<name>.py."""
    seeded = tmp_path / "analysis.py"
    seeded.write_text("import marimo\n", encoding="utf-8")
    seeds: list[str] = []
    server = build_standalone_chat_mcp_server(
        StandaloneArtifactCollector(),
        notebook_mcp_app=object(),
        analysis_notebook_path=seeded,
        notebook_lifecycle=StandaloneNotebookLifecycle(),
        notebook_starter=lambda _c, _a: [
            TextContent(type="text", text=json.dumps({"session_id": "s-x"}))
        ],
        notebook_session_resolver=lambda _s: SimpleNamespace(),
        notebook_seeder=lambda name: seeds.append(name)
        or tmp_path / f"{name}.py",
    )["instance"]

    for hostile in ("..", "../evil", "a/../b", "a\\b", "Report", "-x",
                    "_x", "a" * 42, "", "a b", ".hidden"):
        response = await server.request_handlers[CallToolRequest](
            CallToolRequest(
                params=CallToolRequestParams(
                    name="start_analysis_notebook",
                    arguments={"notebook": hostile},
                )
            )
        )
        assert response.root.isError is True, hostile
    assert seeds == []  # The seeder never runs for a hostile name.


@pytest.mark.asyncio
async def test_stream_error_after_second_kernel_closes_every_kernel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An agent crash after multiple kernels started must leak none of them."""
    run_id = "run-leak-00001"
    closed: list[str] = []
    captured: dict[str, Any] = {}

    async def run_agent(_prompt: str, _session_id: object, **_kwargs: Any):
        for name, kernel in (
            ("analysis", "kernel-analysis"),
            ("report", "kernel-report"),
        ):
            captured["lifecycle"].sessions[name] = kernel
            await captured["event_sink"](
                "notebook_started", {"notebook": name, "session_id": kernel}
            )
        raise RuntimeError("agent transport died")
        yield  # pragma: no cover

    _patch_execution(
        monkeypatch,
        tmp_path,
        resolver=lambda _app, _session_id: SimpleNamespace(),
        closed=closed,
        captured=captured,
        run_agent=run_agent,
    )
    response = await standalone_chat.execute(
        request=_request(_execute_body(run_id), app=SimpleNamespace())
    )
    with pytest.raises(RuntimeError, match="agent transport died"):
        async for _chunk in response.body_iterator:
            pass
    assert set(closed) == {"kernel-analysis", "kernel-report"}
    assert run_id not in chat_runtime._ANALYSIS_SESSIONS_BY_RUN
    assert not (tmp_path / "scratch" / run_id).exists()


@pytest.mark.asyncio
async def test_adopted_turn_recovery_reseeds_with_the_adopted_scratch_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recovery in an adopted scratch must reseed analysis against the
    adopted scratch's token path, per the keepalive/adoption contract."""
    run_id = "run-adopt-0001"
    conversation_id = "conversation-adopt-1"
    adopted_scratch = tmp_path / "adopted"
    adopted_scratch.mkdir()
    (adopted_scratch / "analysis.py").write_text("previous", encoding="utf-8")
    (adopted_scratch / "report.py").write_text("previous", encoding="utf-8")
    sessions: dict[str, Any] = {
        "kernel-a1": _runtime_session(dirty=True),
        "kernel-r1": _runtime_session(),
        "kernel-a2": _runtime_session(dirty=True),
    }
    closed: list[str] = []
    captured: dict[str, Any] = {}
    prompts: list[str] = []
    chat_runtime._KEEPALIVE_BY_CONVERSATION[conversation_id] = (
        adopted_scratch,
        {"analysis": "kernel-a1", "report": "kernel-r1"},
    )

    async def run_agent(prompt: str, _session_id: object, **_kwargs: Any):
        prompts.append(prompt)
        yield AgentEvent(type="text", content="answer")

    _patch_execution(
        monkeypatch,
        tmp_path,
        resolver=lambda _app, session_id: sessions[session_id],
        closed=closed,
        captured=captured,
        run_agent=run_agent,
    )
    monkeypatch.setattr(
        standalone_chat, "_start_analysis_kernel", lambda _a, _p: "kernel-a2"
    )
    response = await standalone_chat.execute(
        request=_request(
            _execute_body(run_id, conversation_id=conversation_id),
            app=SimpleNamespace(),
        )
    )
    body = b"".join([chunk async for chunk in response.body_iterator])
    events = [json.loads(line) for line in body.splitlines()]
    assert closed[0] == "kernel-a1"
    assert events[-1]["type"] == "error"
    assert len(prompts) == 2
    assert "session_id `kernel-a2`" in prompts[1]
    assert "- report: `kernel-r1`" in prompts[1]
    reseeded = (adopted_scratch / "analysis.py").read_text(encoding="utf-8")
    assert repr(str(adopted_scratch / ".gateway-token")) in reseeded
    assert str(tmp_path / "scratch" / run_id) not in reseeded
