from __future__ import annotations

import base64
import json
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from starlette.requests import Request

from signalpilot._server.ai.claude_agent import AgentEvent
from signalpilot._server.api.endpoints import standalone_chat
from signalpilot._server.files import project_sync


def test_seeded_analysis_notebooks_keep_run_tokens_out_of_source_and_isolated(
    tmp_path: Path,
) -> None:
    first_scratch = tmp_path / "run-a"
    second_scratch = tmp_path / "run-b"
    first_scratch.mkdir()
    second_scratch.mkdir()
    first = standalone_chat._seed_analysis_notebook(
        scratch=first_scratch,
        run_id="run-a",
        project_id="project-a",
        connection_name="warehouse-a",
        gateway_url="http://gateway:3300",
        scoped_token="token-a-secret",
    )
    second = standalone_chat._seed_analysis_notebook(
        scratch=second_scratch,
        run_id="run-b",
        project_id="project-b",
        connection_name="warehouse-b",
        gateway_url="http://gateway:3300",
        scoped_token="token-b-secret",
    )

    assert "token-a-secret" not in first.read_text(encoding="utf-8")
    assert "token-b-secret" not in second.read_text(encoding="utf-8")
    assert (first_scratch / ".gateway-token").read_text(
        encoding="utf-8"
    ) == "token-a-secret"
    assert (second_scratch / ".gateway-token").read_text(
        encoding="utf-8"
    ) == "token-b-secret"
    assert (
        stat.S_IMODE((first_scratch / ".gateway-token").stat().st_mode)
        == 0o600
    )


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=repo,
        text=True,
    ).strip()


def _bare_project(tmp_path: Path) -> tuple[Path, str]:
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init", "-b", "main")
    _git(source, "config", "user.email", "test@signalpilot.dev")
    _git(source, "config", "user.name", "SignalPilot Test")
    (source / "dbt_project.yml").write_text(
        "name: test_project\n", encoding="utf-8"
    )
    _git(source, "add", "dbt_project.yml")
    _git(source, "commit", "-m", "initial")
    commit_sha = _git(source, "rev-parse", "HEAD")
    bare = tmp_path / "project.git"
    subprocess.run(
        ["git", "clone", "--bare", str(source), str(bare)],
        check=True,
        capture_output=True,
        text=True,
    )
    return bare, commit_sha


def _scoped_token(*, run_id: str, project_id: str, commit_sha: str) -> str:
    claims = {
        "execution_identity": f"chat:{run_id}",
        "project_id": project_id,
        "branch": "main",
        "connection_name": "production",
        "commit_sha": commit_sha,
        "scopes": ["read", "query", "execute"],
    }
    payload = (
        base64.urlsafe_b64encode(json.dumps(claims).encode())
        .decode()
        .rstrip("=")
    )
    return f"header.{payload}.signature"


def _request(body: dict[str, object], *, app: object | None = None) -> Request:
    encoded = json.dumps(body).encode()
    delivered = False

    async def receive() -> dict[str, object]:
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": encoded, "more_body": False}

    scope: dict[str, Any] = {
        "type": "http",
        "method": "POST",
        "path": "/execute",
        "headers": [(b"content-type", b"application/json")],
    }
    if app is not None:
        scope["app"] = app
    return Request(scope, receive)


def _runtime_session(*, dirty: bool = False) -> Any:
    cell_id = "current"
    notification = SimpleNamespace(
        status="idle",
        output=None,
    )
    session = SimpleNamespace(
        app_file_manager=SimpleNamespace(
            app=SimpleNamespace(
                cell_manager=SimpleNamespace(
                    cell_data=lambda: [
                        SimpleNamespace(cell_id=cell_id, code="answer = 1")
                    ]
                )
            )
        ),
        session_view=SimpleNamespace(
            cell_notifications={cell_id: notification}
        ),
    )
    if dirty:
        session._signalpilot_notebook_dirty = True
        session._signalpilot_last_notebook_failure = {
            "error": {
                "type": "MultipleDefinitionError",
                "variable": "df",
                "cell_ids": ["old", "new"],
            }
        }
    return session


def test_terminal_validation_ignores_deleted_cell_notifications(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _runtime_session()
    session.session_view.cell_notifications["deleted"] = SimpleNamespace(
        status="idle",
        output=SimpleNamespace(
            channel=SimpleNamespace(value="sp-error"),
            data=[SimpleNamespace()],
        ),
    )
    monkeypatch.setattr(
        standalone_chat,
        "_analysis_session",
        lambda _app, _session_id: session,
    )

    assert standalone_chat._notebook_failure(object(), "session-a") is None


def test_recovery_context_keeps_prior_graph_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _runtime_session()
    session._signalpilot_notebook_failures = [
        {
            "error": {
                "type": "MultipleDefinitionError",
                "variable": "segment",
                "cell_ids": ["summary", "chart"],
            }
        }
    ]
    session.session_view.cell_notifications[
        "current"
    ].output = SimpleNamespace(
        channel=SimpleNamespace(value="sp-error"),
        data=[SimpleNamespace()],
    )
    monkeypatch.setattr(
        standalone_chat,
        "_analysis_session",
        lambda _app, _session_id: session,
    )

    failure = standalone_chat._notebook_failure(object(), "session-a")

    assert failure is not None
    assert failure["errors"] == [
        {
            "type": "MultipleDefinitionError",
            "variable": "segment",
            "cell_ids": ["summary", "chart"],
        },
        {
            "type": "SimpleNamespace",
            "variable": None,
            "cell_ids": ["current"],
        },
    ]
    recovery = standalone_chat._recovery_context(failure)
    assert "MultipleDefinitionError" in recovery
    assert '"variable": "segment"' in recovery
    assert '"summary"' in recovery
    assert "underscore-prefixed scratch names" in recovery


@pytest.mark.asyncio
async def test_execute_materializes_the_frozen_project_before_starting_the_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = "1dbf5492-81e6-4683-835f-f1785c9cfe78"
    run_id = "run-12345678"
    bare, commit_sha = _bare_project(tmp_path)
    projects_root = tmp_path / "projects"
    captured: dict[str, str] = {}

    monkeypatch.setattr(project_sync, "PROJECTS_ROOT", projects_root)
    monkeypatch.setenv("SP_CHAT_SCRATCH_ROOT", str(tmp_path / "scratch"))
    for name in (
        "SP_CHAT_RUN_ID",
        "SP_CHAT_PROJECT_ID",
        "SP_CHAT_BRANCH",
        "SP_CHAT_CONNECTION_NAME",
        "SP_CHAT_COMMIT_SHA",
    ):
        monkeypatch.delenv(name, raising=False)

    def gateway_get(url: str, **_kwargs: object) -> httpx.Response:
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={
                "clone_url": str(bare),
                "auth_token": "",
                "auth_username": "x-access-token",
                "default_branch": "main",
            },
        )

    async def run_agent(_prompt: str, _session_id: object, **kwargs: object):
        cwd = Path(str(kwargs["cwd"]))
        captured["cwd"] = str(cwd)
        captured["head"] = _git(cwd, "rev-parse", "HEAD")
        yield AgentEvent(type="text", content="Done")

    monkeypatch.setattr(project_sync.httpx, "get", gateway_get)
    monkeypatch.setattr(standalone_chat, "run_notebook_agent", run_agent)

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
                "prompt": "Yo",
            }
        )
    )
    body = b"".join([chunk async for chunk in response.body_iterator])

    assert json.loads(body.splitlines()[-1]) == {
        "type": "final",
        "content": "Done",
        "artifacts": [],
    }
    assert captured["head"] == commit_sha
    assert Path(captured["cwd"]).is_relative_to(projects_root)


@pytest.mark.asyncio
async def test_dirty_notebook_is_reset_and_only_clean_retry_answer_is_emitted(
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
    archived: list[str] = []

    async def execution_directory(**_kwargs: Any) -> tuple[Path, bool]:
        return tmp_path, False

    def build_server(collector: Any, **kwargs: Any) -> object:
        collectors.append(collector)
        lifecycles.append(kwargs["notebook_lifecycle"])
        seeded_paths.append(kwargs["analysis_notebook_path"])
        event_sinks.append(kwargs["event_sink"])
        return object()

    async def run_agent(prompt: str, _session_id: object, **_kwargs: Any):
        attempt = len(sessions) + 1
        lifecycle = lifecycles[-1]
        lifecycle.session_id = f"kernel-{attempt}"
        sessions[lifecycle.session_id] = _runtime_session(dirty=attempt == 1)
        if attempt == 1:
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
        await event_sinks[-1]("notebook_started", {})
        if attempt == 1:
            collectors[-1].artifacts.append({"filename": "rejected.csv"})
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
        collectors[-1].artifacts.append({"filename": "accepted.csv"})
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

    async def archive(**kwargs: Any) -> str:
        archived.append(kwargs["session_id"])
        return "archive-clean"

    monkeypatch.setenv("SP_CHAT_SCRATCH_ROOT", str(tmp_path / "scratch"))
    monkeypatch.setattr(
        standalone_chat, "_execution_project_directory", execution_directory
    )
    monkeypatch.setattr(
        standalone_chat, "build_standalone_chat_mcp_server", build_server
    )
    monkeypatch.setattr(standalone_chat, "run_notebook_agent", run_agent)
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
    monkeypatch.setattr(standalone_chat, "_archive_analysis_notebook", archive)
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
                "features": {"notebook_analysis": True},
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
        "progress",
        "tool_use",
        "tool_result",
        "final",
    ]
    assert events[0]["content"] == "Restarting analysis in a clean notebook"
    assert events[-1] == {
        "archive_id": "archive-clean",
        "artifacts": [{"filename": "accepted.csv"}],
        "content": "Accepted answer",
        "kernel_stopped": True,
        "type": "final",
    }
    assert "REJECTED LEAK" not in json.dumps(events)
    assert closed == ["kernel-1", "kernel-2"]
    assert archived == ["kernel-2"]
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

    async def execution_directory(**_kwargs: Any) -> tuple[Path, bool]:
        return tmp_path, False

    def build_server(_collector: Any, **kwargs: Any) -> object:
        lifecycles.append(kwargs["notebook_lifecycle"])
        event_sinks.append(kwargs["event_sink"])
        return object()

    async def run_agent(_prompt: str, _session_id: object, **_kwargs: Any):
        attempt = len(sessions) + 1
        lifecycle = lifecycles[-1]
        lifecycle.session_id = f"dirty-kernel-{attempt}"
        sessions[lifecycle.session_id] = _runtime_session(dirty=True)
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
        standalone_chat, "_execution_project_directory", execution_directory
    )
    monkeypatch.setattr(
        standalone_chat, "build_standalone_chat_mcp_server", build_server
    )
    monkeypatch.setattr(standalone_chat, "run_notebook_agent", run_agent)
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
                "features": {"notebook_analysis": True},
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
        "progress",
        "tool_use",
        "tool_result",
        "error",
    ]
    assert events[-1] == {
        "content": "Notebook validation failed after one clean retry; the answer was rejected.",
        "is_error": True,
        "type": "error",
    }
    assert all(
        event["type"] not in {"final", "text", "text_delta"}
        for event in events
    )
    assert archive_calls == []
