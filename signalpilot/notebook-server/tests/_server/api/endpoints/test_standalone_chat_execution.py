from __future__ import annotations

import base64
import json
import os
import stat
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Self
from unittest.mock import AsyncMock

import anyio
import httpx
import jwt
import pytest
from mcp.types import CallToolRequest, CallToolRequestParams
from starlette.exceptions import HTTPException
from starlette.requests import Request

from signalpilot._config.settings import GLOBAL_SETTINGS
from signalpilot._server.ai.claude_agent import AgentEvent
from signalpilot._server.api.endpoints import (
    standalone_chat_cancel as chat_cancel,
    standalone_chat_execution as standalone_chat,
    standalone_chat_runtime as chat_runtime,
    standalone_chat_workspace as chat_workspace,
)
from signalpilot._server.errors import handle_error
from signalpilot._utils import requests
from signalpilot._utils.requests import RequestError

# The notebook /execute endpoint HS256-verifies the per-run gateway_session_token
# with this secret (SP_SESSION_JWT_SECRET). Tests mint real signed tokens with it.
_TEST_JWT_SECRET = "test-notebook-session-secret-at-least-32-bytes"


@pytest.fixture(autouse=True)
def _session_jwt_secret(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SP_SESSION_JWT_SECRET", _TEST_JWT_SECRET)
    monkeypatch.setenv(
        "SP_CHAT_CLAUDE_STATE_ROOT",
        str(tmp_path / "claude-sessions"),
    )


def test_seeded_analysis_notebooks_keep_run_tokens_out_of_source_and_isolated(
    tmp_path: Path,
) -> None:
    first_scratch = tmp_path / "run-a"
    second_scratch = tmp_path / "run-b"
    first_scratch.mkdir()
    second_scratch.mkdir()
    first = chat_runtime._seed_analysis_notebook(
        scratch=first_scratch,
        run_id="run-a",
        project_id="project-a",
        connection_name="warehouse-a",
        gateway_url="http://gateway:3300",
        scoped_token="token-a-secret",
    )
    second = chat_runtime._seed_analysis_notebook(
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
    # chmod(0o600) has full meaning only on POSIX; Windows reports 0o666 for
    # any owner-writable file, so assert the strict mode where it exists.
    if os.name == "posix":
        assert (
            stat.S_IMODE((first_scratch / ".gateway-token").stat().st_mode)
            == 0o600
        )


def _scoped_token(
    *,
    run_id: str,
    project_id: str,
    commit_sha: str,
    branch: str = "main",
    connection_name: str = "production",
    scopes: list[str] | None = None,
    secret: str = _TEST_JWT_SECRET,
) -> str:
    now = int(time.time())
    claims = {
        "iss": "signalpilot-notebook-session",
        "aud": "signalpilot-gateway",
        "sub": "test-user",
        "org_id": "test-org",
        "session_id": "test-session",
        "execution_identity": f"chat:{run_id}",
        "project_id": project_id,
        "branch": branch,
        "connection_name": connection_name,
        "commit_sha": commit_sha,
        "scopes": scopes or ["read", "query", "execute"],
        "iat": now,
        "exp": now + 600,
    }
    return jwt.encode(claims, secret, algorithm="HS256")


def _request(body: dict[str, object], *, app: object | None = None) -> Request:
    encoded = json.dumps(body).encode()
    delivered = False

    async def receive() -> dict[str, object]:
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": encoded, "more_body": False}

    from starlette.authentication import AuthCredentials, SimpleUser

    scope: dict[str, Any] = {
        "type": "http",
        "method": "POST",
        "path": "/execute",
        "headers": [(b"content-type", b"application/json")],
        "auth": AuthCredentials(["edit"]),
        "user": SimpleUser("test-user"),
    }
    if app is not None:
        scope["app"] = app
    return Request(scope, receive)


def _error_request(path: str, *, accept: str = "") -> Request:
    headers = [(b"accept", accept.encode())] if accept else []
    return Request(
        {"type": "http", "method": "POST", "path": path, "headers": headers}
    )


def _cancel_request(run_id: str) -> Request:
    from starlette.authentication import AuthCredentials, SimpleUser

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": f"/api/standalone-chat/cancel/{run_id}",
            "path_params": {"run_id": run_id},
            "headers": [],
            "auth": AuthCredentials(["edit"]),
            "user": SimpleUser("test-user"),
        }
    )


def _steer_request(run_id: str, payload: dict[str, Any]) -> Request:
    from starlette.authentication import AuthCredentials, SimpleUser

    body = json.dumps(payload).encode()
    sent = False

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": f"/api/standalone-chat/steer/{run_id}",
            "path_params": {"run_id": run_id},
            "headers": [(b"content-type", b"application/json")],
            "auth": AuthCredentials(["edit"]),
            "user": SimpleUser("test-user"),
        },
        receive,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/api/standalone-chat/execute",
        "/notebook/session-a/api/standalone-chat/execute",
    ],
)
async def test_api_forbidden_response_preserves_status_and_detail(
    path: str,
) -> None:
    response = await handle_error(
        _error_request(path),
        HTTPException(status_code=403, detail="Execution scope mismatch"),
    )

    assert response.status_code == 403
    assert json.loads(response.body) == {"detail": "Execution scope mismatch"}
    assert "www-authenticate" not in response.headers


@pytest.mark.asyncio
async def test_json_api_forbidden_response_preserves_detail() -> None:
    response = await handle_error(
        _error_request("/custom/execute", accept="application/json"),
        HTTPException(status_code=403, detail="Invalid scoped gateway identity"),
    )

    assert response.status_code == 403
    assert json.loads(response.body) == {
        "detail": "Invalid scoped gateway identity"
    }


@pytest.mark.asyncio
async def test_page_forbidden_response_still_requests_basic_auth() -> None:
    response = await handle_error(
        _error_request("/notebook/session-a/"),
        HTTPException(status_code=403, detail="Forbidden"),
    )

    assert response.status_code == 401
    assert json.loads(response.body) == {"detail": "Authorization header required"}
    assert response.headers["www-authenticate"] == "Basic"


@pytest.mark.asyncio
async def test_cancel_accepts_a_later_run_in_the_warm_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SP_CHAT_RUN_ID", "run-11111111")
    monkeypatch.setattr(chat_cancel, "stop_agent", lambda _session: True)

    response = await chat_cancel.cancel(
        request=_cancel_request("run-22222222")
    )

    assert response.status_code == 200
    assert json.loads(response.body) == {"stopped": True, "kernel_stopped": False}


@pytest.mark.asyncio
async def test_steer_queues_on_the_live_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    steer = AsyncMock(return_value=True)
    monkeypatch.setattr(chat_cancel, "steer_agent", steer)

    response = await chat_cancel.steer(
        request=_steer_request(
            "run-22222222",
            {"steering_id": "message-1", "message": "Use weekly data."},
        )
    )

    assert response.status_code == 200
    assert json.loads(response.body) == {"accepted": True}
    steer.assert_awaited_once_with(
        "standalone-run-22222222", "Use weekly data.", "message-1"
    )


def _runtime_session(*, dirty: bool = False) -> Any:
    cell_id = "current"
    notification = SimpleNamespace(
        status="idle",
        output=None,
    )
    session = SimpleNamespace(
        app_file_manager=SimpleNamespace(
            app=SimpleNamespace(
                to_py=lambda: "answer = 1",
                cell_manager=SimpleNamespace(
                    cell_data=lambda: [
                        SimpleNamespace(cell_id=cell_id, code="answer = 1")
                    ]
                ),
            )
        ),
        config_manager=SimpleNamespace(get_config=lambda: {"display": {}}),
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
        chat_runtime,
        "_analysis_session",
        lambda _app, _session_id: session,
    )

    assert chat_runtime._notebook_failure(object(), "session-a") is None


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
        chat_runtime,
        "_analysis_session",
        lambda _app, _session_id: session,
    )

    failure = chat_runtime._notebook_failure(object(), "session-a")

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
    recovery = chat_runtime._recovery_context(failure)
    assert "MultipleDefinitionError" in recovery
    assert '"variable": "segment"' in recovery
    assert '"summary"' in recovery
    assert "underscore-prefixed scratch names" in recovery
    assert "cell-local and cannot be read from another cell" in recovery
    assert "changed SQL requires a new plan_query result" in recovery
    assert "Never replace SDK query evidence" in recovery


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
async def test_execute_materializes_the_frozen_project_before_starting_the_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The execution checkout is pulled from the gateway snapshot endpoint
    (S3 tarball) into disposable scratch â€” no git, disk is never the truth."""
    import io
    import tarfile

    project_id = "1dbf5492-81e6-4683-835f-f1785c9cfe78"
    conversation_id = "22222222-3333-4444-8555-666666666666"
    run_id = "run-12345678"
    commit_sha = "a" * 40
    projects_root = tmp_path / "projects"
    captured: dict[str, str] = {}

    monkeypatch.setattr(chat_runtime, "PROJECTS_ROOT", projects_root)
    monkeypatch.setenv("SP_CHAT_SCRATCH_ROOT", str(tmp_path / "scratch"))
    for name in (
        "SP_CHAT_PROJECT_ID",
        "SP_CHAT_BRANCH",
        "SP_CHAT_CONNECTION_NAME",
        "SP_CHAT_COMMIT_SHA",
    ):
        monkeypatch.delenv(name, raising=False)

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        payload = b"name: test_project\n"
        info = tarfile.TarInfo("dbt_project.yml")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    tarball = buffer.getvalue()

    def gateway_get(url: str, **kwargs: object) -> httpx.Response:
        assert url.endswith(f"/api/workspace-projects/{project_id}/snapshot")
        assert kwargs["params"] == {"branch": "main"}
        captured["snapshot_auth"] = dict(kwargs["headers"])["Authorization"]
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={"revision": 7, "url": "https://s3.test/snap.tgz", "key": "k"},
        )

    class FakeStream:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def raise_for_status(self) -> None:
            return None

        def iter_bytes(self):
            yield tarball

    def gateway_stream(method: str, url: str, **_kwargs: object) -> FakeStream:
        assert (method, url) == ("GET", "https://s3.test/snap.tgz")
        return FakeStream()

    async def run_agent(_prompt: str, _session_id: object, **kwargs: object):
        # Capture while the run is live: the disposable checkout is removed
        # when the stream finishes, so nothing can be read after the fact.
        captured["max_turns"] = str(kwargs["max_turns"])
        captured["chat_session_id"] = str(kwargs["chat_session_id_override"])
        captured["resume_session"] = str(kwargs["resume_session_override"])
        captured["claude_config_dir"] = str(
            kwargs["agent_env_overrides"]["CLAUDE_CONFIG_DIR"]
        )
        cwd = Path(str(kwargs["cwd"]))
        captured["cwd"] = str(cwd)
        captured["dbt_project_yml"] = (cwd / "dbt_project.yml").read_text(encoding="utf-8")
        yield AgentEvent(type="text", content="Done")

    monkeypatch.setattr(httpx, "get", gateway_get)
    monkeypatch.setattr(httpx, "stream", gateway_stream)
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
                "conversation_id": conversation_id,
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
    checkout = Path(captured["cwd"])
    assert checkout.is_relative_to(projects_root / ".standalone-chat" / project_id)
    assert checkout.name == conversation_id
    assert captured["dbt_project_yml"] == "name: test_project\n"
    assert captured["snapshot_auth"] == f"Bearer {token}"
    assert captured["max_turns"] == "200"
    assert captured["chat_session_id"] == conversation_id
    assert captured["resume_session"] == "False"
    assert Path(captured["claude_config_dir"]).name == conversation_id
    # Disposable scratch: the checkout is gone once the stream completes.
    assert not await anyio.Path(checkout).exists()


@pytest.mark.asyncio
async def test_first_turn_complete_artifact_returns_a_proactive_create_proposal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = "1dbf5492-81e6-4683-835f-f1785c9cfe78"
    run_id = "run-first-turn"
    commit_sha = "b" * 40

    monkeypatch.setenv("SP_CHAT_SCRATCH_ROOT", str(tmp_path / "scratch"))

    async def execution_directory(**_kwargs: Any) -> tuple[Path, bool]:
        return tmp_path, False

    class CatalogResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {
                "items": [],
                "next_cursor": None,
                "catalog_revision": "empty-catalog",
                "total_reports": 0,
                "proactive_creation_allowed": True,
            }

    class CatalogClient:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def get(self, url: str, **_kwargs: Any) -> CatalogResponse:
            assert url.endswith(f"/api/chat/runs/{run_id}/report-catalog")
            return CatalogResponse()

    async def run_agent(_prompt: str, _session_id: object, **kwargs: Any):
        server = kwargs["additional_mcp_servers"]["standalone-chat"][
            "instance"
        ]
        published = await server.request_handlers[CallToolRequest](
            CallToolRequest(
                params=CallToolRequestParams(
                    name="publish_report",
                    arguments={
                        "filename": "first-turn-revenue.html",
                        "html": "<html><body>Revenue</body></html>",
                    },
                )
            )
        )
        assert "REQUIRED BEFORE YOUR FINAL ANSWER" in (
            published.root.content[0].text
        )
        await server.request_handlers[CallToolRequest](
            CallToolRequest(
                params=CallToolRequestParams(
                    name="list_saved_report_catalog",
                    arguments={},
                )
            )
        )
        proposed = await server.request_handlers[CallToolRequest](
            CallToolRequest(
                params=CallToolRequestParams(
                    name="propose_report_action",
                    arguments={
                        "action": "create",
                        "artifact_kind": "report",
                        "artifact_filename": "first-turn-revenue.html",
                        "title": "Revenue overview",
                        "reason": "No saved report matches this business question.",
                    },
                )
            )
        )
        assert proposed.root.isError is False
        yield AgentEvent(type="text", content="Revenue is growing.")

    monkeypatch.setattr(
        chat_workspace, "_execution_project_directory", execution_directory
    )
    monkeypatch.setattr(httpx, "AsyncClient", CatalogClient)
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
                "prompt": "Build a revenue overview",
                "new_execution": True,
            }
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
    assert final["content"] == "Revenue is growing."
    assert final["report_proposal"]["action"] == "create"
    assert final["report_proposal"]["catalog_revision"] == "empty-catalog"
    assert final["report_action_outcome"] == final["report_proposal"]
    assert final["artifacts"][0]["filename"] == "first-turn-revenue.html"


@pytest.mark.asyncio
async def test_completion_check_is_non_fatal_when_agent_skips_report_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = "run-missed-decision"
    project_id = "1dbf5492-81e6-4683-835f-f1785c9cfe78"
    commit_sha = "c" * 40
    collectors: list[Any] = []

    async def execution_directory(**_kwargs: Any) -> tuple[Path, bool]:
        return tmp_path, False

    def build_server(collector: Any, **_kwargs: Any) -> object:
        collectors.append(collector)
        return object()

    async def run_agent(_prompt: str, _session_id: object, **_kwargs: Any):
        collectors[-1].artifacts.append(
            {
                "kind": "report",
                "filename": "missed.html",
                "payload": {"html": "<html>Complete</html>"},
                "provenance": {"result_references": []},
            }
        )
        yield AgentEvent(type="text", content="Completed answer")

    monkeypatch.setenv("SP_CHAT_SCRATCH_ROOT", str(tmp_path / "scratch"))
    monkeypatch.setattr(
        chat_workspace, "_execution_project_directory", execution_directory
    )
    monkeypatch.setattr(
        standalone_chat, "build_standalone_chat_mcp_server", build_server
    )
    monkeypatch.setattr(standalone_chat, "run_notebook_agent", run_agent)
    monkeypatch.setattr(
        standalone_chat, "_project_is_unchanged", lambda *_args: True
    )
    monkeypatch.setattr(
        standalone_chat, "clear_chat_session", lambda *_args, **_kwargs: None
    )

    response = await standalone_chat.execute(
        request=_request(
            {
                "run_id": run_id,
                "project_id": project_id,
                "branch": "main",
                "connection_name": "production",
                "commit_sha": commit_sha,
                "gateway_session_token": _scoped_token(
                    run_id=run_id,
                    project_id=project_id,
                    commit_sha=commit_sha,
                ),
                "prompt": "Build a report",
            }
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
    assert final["content"] == "Completed answer"
    assert "report_proposal" not in final
    assert final["report_action_outcome"]["action"] == "no_suggestion"
    assert final["report_action_outcome"]["source"] == "completion_check"
    assert final["report_action_outcome"]["catalog_scan_complete"] is False


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
        assert "session_id `kernel-2`" in prompt
        assert "Plan each database query before executing it" in prompt
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
        "artifacts": [{"filename": "accepted.csv"}],
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


def test_tree_digest_ignores_generated_tooling_artifacts(tmp_path: Path) -> None:
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "orders.sql").write_text("select 1", encoding="utf-8")
    (tmp_path / "dbt_project.yml").write_text("name: demo", encoding="utf-8")
    baseline = chat_runtime._tree_digest(tmp_path)

    # dbt/python tooling side effects during a read-only analysis must not
    # change the digest â€” only project source is frozen.
    (tmp_path / "target").mkdir()
    (tmp_path / "target" / "manifest.json").write_text("{}", encoding="utf-8")
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "dbt.log").write_text("log", encoding="utf-8")
    (tmp_path / ".user.yml").write_text("id: x", encoding="utf-8")
    (tmp_path / "models" / "__pycache__").mkdir()
    (tmp_path / "models" / "__pycache__" / "m.pyc").write_bytes(b"\x00")
    assert chat_runtime._tree_digest(tmp_path) == baseline
    assert chat_runtime._project_is_unchanged(tmp_path, baseline)

    # Real source edits still trip the check.
    (tmp_path / "models" / "orders.sql").write_text("select 2", encoding="utf-8")
    assert not chat_runtime._project_is_unchanged(tmp_path, baseline)
