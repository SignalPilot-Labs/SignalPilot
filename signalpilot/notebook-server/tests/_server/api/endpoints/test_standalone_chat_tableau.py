"""Tableau gating in standalone chat execution: prompt, allowlist, server."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from signalpilot._server.ai.claude_agent import AgentEvent
from signalpilot._server.ai.tableau_tools import TABLEAU_ALLOWED_TOOLS
from signalpilot._server.api.endpoints import (
    standalone_chat_execution as standalone_chat,
    standalone_chat_workspace as chat_workspace,
)
from signalpilot._server.api.endpoints.standalone_chat_prompt import (
    STANDALONE_ALLOWED_TOOLS,
    _execution_prompt_values,
    execution_allowed_tools,
    tableau_enabled,
)
from tests._server.api.endpoints.test_standalone_chat_execution import (
    _TEST_JWT_SECRET,
    _request,
    _scoped_token,
)

if TYPE_CHECKING:
    from pathlib import Path

HEADING = "## Tableau"


@pytest.fixture(autouse=True)
def _session_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SP_SESSION_JWT_SECRET", _TEST_JWT_SECRET)
    monkeypatch.setenv(
        "SP_CHAT_CLAUDE_STATE_ROOT", str(tmp_path / "claude-sessions")
    )


def _prompt(body: dict[str, Any]) -> str:
    *_, system_prompt = _execution_prompt_values(
        {"prompt": "Find the sales workbook", **body},
        project_id="project-a",
        branch="main",
        commit_sha="a" * 40,
        connection_name="warehouse",
    )
    return system_prompt


def test_tableau_prompt_section_only_when_enabled() -> None:
    assert HEADING not in _prompt({})
    assert HEADING not in _prompt({"features": {"tableau": False}})
    assert HEADING not in _prompt({"features": {"tableau": "true"}})

    enabled = _prompt({"features": {"tableau": True}})
    assert HEADING in enabled
    assert "signalpilot-dbt:tableau" in enabled
    assert "Do not ask the user for Tableau credentials" in enabled
    assert "<!-- @if" not in enabled
    assert enabled.index(HEADING) < enabled.index("Selected project:")


def test_tableau_tools_join_the_allowlist_only_when_enabled() -> None:
    assert not any(
        name in STANDALONE_ALLOWED_TOOLS for name in TABLEAU_ALLOWED_TOOLS
    )
    assert tableau_enabled({"features": {"tableau": True}}) is True
    assert tableau_enabled({"features": {"tableau": 1}}) is False
    assert tableau_enabled({"features": "tableau"}) is False

    assert execution_allowed_tools({}, ["mcp__x__y"]) == [
        *STANDALONE_ALLOWED_TOOLS,
        "mcp__x__y",
    ]
    assert execution_allowed_tools(
        {"features": {"tableau": True}}, ["mcp__x__y"]
    ) == [*STANDALONE_ALLOWED_TOOLS, *TABLEAU_ALLOWED_TOOLS, "mcp__x__y"]
    assert len(TABLEAU_ALLOWED_TOOLS) == 10
    assert all(
        name.startswith("mcp__standalone-chat__tableau_")
        for name in TABLEAU_ALLOWED_TOOLS
    )


async def _execute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    run_id: str,
    features: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    project_id = "1dbf5492-81e6-4683-835f-f1785c9cfe78"
    commit_sha = "f" * 40
    captured: dict[str, Any] = {}
    server_kwargs: dict[str, Any] = {}

    async def execution_directory(**_kwargs: Any) -> tuple[Path, bool]:
        return tmp_path, False

    def build_server(**kwargs: Any) -> object:
        server_kwargs.update(kwargs)
        return object()

    async def run_agent(_prompt: str, _session_id: object, **kwargs: Any):
        captured.update(kwargs)
        yield AgentEvent(type="text", content="Done")

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
    body: dict[str, Any] = {
        "run_id": run_id,
        "project_id": project_id,
        "branch": "main",
        "connection_name": "production",
        "commit_sha": commit_sha,
        "gateway_session_token": _scoped_token(
            run_id=run_id, project_id=project_id, commit_sha=commit_sha
        ),
        "prompt": "Rebuild the sales dashboard in Tableau",
    }
    if features is not None:
        body["features"] = features
    response = await standalone_chat.execute(request=_request(body))
    events = [
        json.loads(line)
        for line in (
            b"".join([chunk async for chunk in response.body_iterator])
        ).splitlines()
    ]
    assert events[-1]["type"] == "final"
    return captured, server_kwargs


@pytest.mark.asyncio
async def test_execute_enables_tableau_from_the_feature_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured, server_kwargs = await _execute(
        tmp_path,
        monkeypatch,
        run_id="run-tableau-1",
        features={"tableau": True},
    )
    assert server_kwargs["tableau_enabled"] is True
    assert server_kwargs["workspace_directory"] is not None
    allowed = captured["allowed_tools"]
    assert all(name in allowed for name in TABLEAU_ALLOWED_TOOLS)
    assert HEADING in captured["system_prompt_override"]


@pytest.mark.asyncio
async def test_execute_keeps_tableau_off_without_the_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured, server_kwargs = await _execute(
        tmp_path, monkeypatch, run_id="run-tableau-0", features=None
    )
    assert server_kwargs["tableau_enabled"] is False
    allowed = captured["allowed_tools"]
    assert not any(name in allowed for name in TABLEAU_ALLOWED_TOOLS)
    assert HEADING not in captured["system_prompt_override"]
