from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Self
from unittest.mock import AsyncMock

import anyio
import httpx
import jwt
import pytest
from starlette.exceptions import HTTPException
from starlette.requests import Request

from signalpilot._server.ai.claude_agent import AgentEvent
from signalpilot._server.api.endpoints import (
    standalone_chat_cancel as chat_cancel,
    standalone_chat_execution as standalone_chat,
    standalone_chat_runtime as chat_runtime,
)
from signalpilot._server.errors import handle_error

# The notebook /execute endpoint HS256-verifies the per-run gateway_session_token
# with this secret (SP_SESSION_JWT_SECRET). Tests mint real signed tokens with it.
_TEST_JWT_SECRET = "test-notebook-session-secret-at-least-32-bytes"


@pytest.mark.parametrize(
    ("notebook_cells_edited", "successful_run_cells", "expected"),
    [
        (False, False, False),
        (True, False, True),
        (True, True, False),
    ],
)
def test_notebook_evidence_is_required_only_after_a_cell_edit(
    notebook_cells_edited: bool,
    successful_run_cells: bool,
    expected: bool,
) -> None:
    assert (
        standalone_chat._notebook_edit_requires_successful_run(
            notebook_cells_edited=notebook_cells_edited,
            successful_run_cells=successful_run_cells,
        )
        is expected
    )


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
    assert "Re-run changed SQL through the SDK" in recovery
    assert "Never replace SDK query evidence" in recovery


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
