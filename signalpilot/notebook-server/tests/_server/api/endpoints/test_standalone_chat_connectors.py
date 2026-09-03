"""External MCP connector injection into standalone chat execution."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

import pytest
from starlette.exceptions import HTTPException

from signalpilot._server.ai.claude_agent import AgentEvent
from signalpilot._server.api.endpoints import (
    standalone_chat_execution as standalone_chat,
    standalone_chat_workspace as chat_workspace,
)
from signalpilot._server.api.endpoints.standalone_chat_prompt import (
    STANDALONE_ALLOWED_TOOLS,
)
from signalpilot._server.auth.standalone_chat_connectors import (
    ChatConnector,
    connector_allowed_tools,
    connector_secret_values,
    parse_mcp_connectors,
)
from tests._server.api.endpoints.test_standalone_chat_execution import (
    _TEST_JWT_SECRET,
    _request,
    _scoped_token,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _session_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SP_SESSION_JWT_SECRET", _TEST_JWT_SECRET)
    monkeypatch.setenv(
        "SP_CHAT_CLAUDE_STATE_ROOT", str(tmp_path / "claude-sessions")
    )


REMOTE = {
    "slug": "linear",
    "kind": "remote",
    "url": "http://gateway:3300/api/mcp/proxy/conn-1/mcp",
    "allowed_tools": ["list_issues", "get_issue"],
}
SANDBOX = {
    "slug": "local_fs",
    "kind": "sandbox",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
    "env": {"FS_TOKEN": "fs-secret-value"},
    "allowed_tools": ["read_file"],
}


def test_parse_accepts_remote_and_sandbox_entries() -> None:
    remote, sandbox = parse_mcp_connectors(
        {"mcp_connectors": [REMOTE, SANDBOX]}
    )

    assert remote == ChatConnector(
        slug="linear",
        kind="remote",
        url=REMOTE["url"],
        allowed_tools=("list_issues", "get_issue"),
    )
    assert sandbox.kind == "sandbox"
    assert sandbox.command == "npx"
    assert sandbox.args == tuple(SANDBOX["args"])
    assert sandbox.env == {"FS_TOKEN": "fs-secret-value"}
    assert connector_allowed_tools([remote, sandbox]) == [
        "mcp__linear__list_issues",
        "mcp__linear__get_issue",
        "mcp__local_fs__read_file",
    ]
    assert connector_secret_values([remote, sandbox]) == ("fs-secret-value",)


def test_parse_is_a_no_op_without_connectors() -> None:
    assert parse_mcp_connectors({}) == []
    assert parse_mcp_connectors({"mcp_connectors": []}) == []
    with pytest.raises(HTTPException, match="Invalid mcp_connectors"):
        parse_mcp_connectors({"mcp_connectors": {"slug": "x"}})


@pytest.mark.parametrize(
    "slug", ["signalpilot", "standalone-chat", "signalpilot-notebook"]
)
def test_parse_rejects_reserved_slugs_and_logs(
    slug: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        parsed = parse_mcp_connectors(
            {
                "mcp_connectors": [
                    {**REMOTE, "slug": slug},
                    REMOTE,
                ]
            }
        )

    assert [connector.slug for connector in parsed] == ["linear"]
    assert any(
        "reserved server name" in record.getMessage()
        or "invalid slug" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.parametrize(
    "entry",
    [
        {**REMOTE, "slug": "Bad Slug"},
        {**REMOTE, "url": "ftp://x"},
        {**REMOTE, "kind": "unknown"},
        {**REMOTE, "allowed_tools": []},
        {**SANDBOX, "command": ""},
        {**SANDBOX, "env": {"1bad": "x"}},
        {**SANDBOX, "args": "not-a-list"},
        "not-an-object",
    ],
)
def test_parse_skips_malformed_entries(entry: Any) -> None:
    assert parse_mcp_connectors({"mcp_connectors": [entry]}) == []


def test_parse_never_emits_a_wildcard_and_dedupes() -> None:
    parsed = parse_mcp_connectors(
        {
            "mcp_connectors": [
                {
                    **REMOTE,
                    "allowed_tools": ["*", "a*", "list_issues", "list_issues"],
                },
                REMOTE,
            ]
        }
    )

    assert len(parsed) == 1
    assert connector_allowed_tools(parsed) == ["mcp__linear__list_issues"]
    assert all("*" not in name for name in connector_allowed_tools(parsed))


def test_sandbox_env_is_hidden_from_repr_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        (sandbox,) = parse_mcp_connectors({"mcp_connectors": [SANDBOX]})

    assert "fs-secret-value" not in repr(sandbox)
    assert "fs-secret-value" not in str(sandbox)
    assert all(
        "fs-secret-value" not in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_execute_injects_connectors_into_the_agent_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    run_id = "run-connectors-1"
    project_id = "1dbf5492-81e6-4683-835f-f1785c9cfe78"
    commit_sha = "d" * 40
    captured: dict[str, Any] = {}
    server_kwargs: dict[str, Any] = {}

    async def execution_directory(**_kwargs: Any) -> tuple[Path, bool]:
        return tmp_path, False

    def build_server(_collector: Any, **kwargs: Any) -> object:
        server_kwargs.update(kwargs)
        return object()

    async def run_agent(_prompt: str, _session_id: object, **kwargs: Any):
        captured.update(kwargs)
        yield AgentEvent(type="text", content="Done")

    monkeypatch.setenv("SP_GATEWAY_INTERNAL_URL", "http://gateway:3300")
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

    token = _scoped_token(
        run_id=run_id, project_id=project_id, commit_sha=commit_sha
    )
    with caplog.at_level(logging.DEBUG):
        response = await standalone_chat.execute(
            request=_request(
                {
                    "run_id": run_id,
                    "project_id": project_id,
                    "branch": "main",
                    "connection_name": "production",
                    "commit_sha": commit_sha,
                    "gateway_session_token": token,
                    "prompt": "List my open issues",
                    "mcp_connectors": [
                        REMOTE,
                        SANDBOX,
                        {**REMOTE, "slug": "signalpilot"},
                    ],
                }
            )
        )
        events = [
            json.loads(line)
            for line in (
                b"".join([chunk async for chunk in response.body_iterator])
            ).splitlines()
        ]

    assert events[-1]["type"] == "final"

    servers = captured["mcp_config"]["mcpServers"]
    assert set(servers) == {"signalpilot", "linear", "local_fs"}
    assert servers["signalpilot"]["url"] == "http://gateway:3300/mcp"
    assert servers["linear"] == {
        "type": "http",
        "url": REMOTE["url"],
        "headers": {"Authorization": f"Bearer {token}"},
    }
    assert servers["local_fs"] == {
        "type": "stdio",
        "command": "npx",
        "args": SANDBOX["args"],
        "env": {"FS_TOKEN": "fs-secret-value"},
    }

    allowed = captured["allowed_tools"]
    assert allowed[: len(STANDALONE_ALLOWED_TOOLS)] == list(
        STANDALONE_ALLOWED_TOOLS
    )
    assert allowed[len(STANDALONE_ALLOWED_TOOLS) :] == [
        "mcp__linear__list_issues",
        "mcp__linear__get_issue",
        "mcp__local_fs__read_file",
    ]
    assert "mcp__linear" not in allowed
    assert not any(name.endswith("__*") or name == "*" for name in allowed)
    assert all("*" not in name for name in allowed)

    # The R11 prompt section and the trailer line name the injected slugs.
    system_prompt = captured["system_prompt_override"]
    assert "Connectors: linear, local_fs" in system_prompt
    assert "needs you to sign in" in system_prompt

    # Secrets: redacted from notebook output, absent from the process env and
    # the agent env overrides, and never logged.
    assert "fs-secret-value" in server_kwargs["runtime_redactions"]
    assert token in server_kwargs["runtime_redactions"]
    assert "fs-secret-value" not in json.dumps(captured["agent_env_overrides"])
    assert "FS_TOKEN" not in captured["agent_env_overrides"]
    assert all(
        "fs-secret-value" not in record.getMessage()
        for record in caplog.records
    )
    assert any(
        "reserved server name" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_execute_without_connectors_keeps_the_default_surface(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = "run-connectors-0"
    project_id = "1dbf5492-81e6-4683-835f-f1785c9cfe78"
    commit_sha = "e" * 40
    captured: dict[str, Any] = {}

    async def execution_directory(**_kwargs: Any) -> tuple[Path, bool]:
        return tmp_path, False

    async def run_agent(_prompt: str, _session_id: object, **kwargs: Any):
        captured.update(kwargs)
        yield AgentEvent(type="text", content="Done")

    monkeypatch.setenv("SP_CHAT_SCRATCH_ROOT", str(tmp_path / "scratch"))
    monkeypatch.setattr(
        chat_workspace, "_execution_project_directory", execution_directory
    )
    monkeypatch.setattr(
        standalone_chat,
        "build_standalone_chat_mcp_server",
        lambda *_args, **_kwargs: object(),
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
                    run_id=run_id, project_id=project_id, commit_sha=commit_sha
                ),
                "prompt": "Summarize revenue",
            }
        )
    )
    async for _chunk in response.body_iterator:
        pass

    assert set(captured["mcp_config"]["mcpServers"]) == {"signalpilot"}
    assert captured["allowed_tools"] == list(STANDALONE_ALLOWED_TOOLS)
    assert "Connectors: none" in captured["system_prompt_override"]
    assert (
        "Connector tools come from outside"
        not in (captured["system_prompt_override"])
    )
