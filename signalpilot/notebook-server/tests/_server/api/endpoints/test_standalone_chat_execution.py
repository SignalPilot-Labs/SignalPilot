from __future__ import annotations

import base64
import json
import stat
import subprocess
from pathlib import Path

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
    assert (first_scratch / ".gateway-token").read_text(encoding="utf-8") == "token-a-secret"
    assert (second_scratch / ".gateway-token").read_text(encoding="utf-8") == "token-b-secret"
    assert stat.S_IMODE((first_scratch / ".gateway-token").stat().st_mode) == 0o600


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


def _request(body: dict[str, object]) -> Request:
    encoded = json.dumps(body).encode()
    delivered = False

    async def receive() -> dict[str, object]:
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": encoded, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/execute",
            "headers": [(b"content-type", b"application/json")],
        },
        receive,
    )


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
