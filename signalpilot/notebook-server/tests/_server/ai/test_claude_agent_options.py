"""Agent working directory, SP_PROJECT_DIR and the transport breaker hooks."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from signalpilot._server.ai.claude_agent_options import (
    DEFERRED_WORK_TOOLS,
    _build_agent_env,
    _build_agent_options_kwargs,
    _build_disallowed_tools,
    resolve_agent_cwd,
)
from signalpilot._server.api.endpoints.standalone_chat_agent_options import (
    agent_env_overrides,
    build_agent_options,
)
from signalpilot._server.api.endpoints.standalone_chat_prompt import (
    STANDALONE_DISALLOWED_MCP_TOOLS,
)

if TYPE_CHECKING:
    from pathlib import Path


def _workspace(tmp_path: Path, projects: list[str], *, root: bool = False) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("x", encoding="utf-8")
    for name in projects:
        (workspace / name).mkdir()
        (workspace / name / "dbt_project.yml").write_text("name: x\n", encoding="utf-8")
    (workspace / "notes").mkdir(exist_ok=True)
    if root:
        (workspace / "dbt_project.yml").write_text("name: root\n", encoding="utf-8")
    return workspace


def test_single_project_subdirectory_becomes_the_cwd(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, ["dumpsters_dbt"])
    cwd, project = resolve_agent_cwd(str(workspace))
    assert cwd == project == str(workspace / "dumpsters_dbt")


@pytest.mark.parametrize("projects", [[], ["a", "b"]])
def test_none_or_several_projects_keep_the_workspace_root(
    tmp_path: Path, projects: list[str]
) -> None:
    workspace = _workspace(tmp_path, projects)
    assert resolve_agent_cwd(str(workspace)) == (str(workspace), str(workspace))


def test_root_project_keeps_the_root(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, ["nested"], root=True)
    assert resolve_agent_cwd(str(workspace)) == (str(workspace), str(workspace))


def test_missing_workspace_falls_back_to_the_path_itself(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    assert resolve_agent_cwd(str(missing)) == (str(missing), str(missing))


def _kwargs(workspace: Path) -> dict:
    env = {"PATH": "/bin"}
    return _build_agent_options_kwargs(
        model="m",
        effort="medium",
        max_turns=5,
        system_prompt="p",
        cwd=str(workspace),
        agent_env=env,
        disallowed_tools=None,
        allowed_tools=None,
        mcp_servers={},
        app=None,
        notebook_session_authorizer=None,
        chat_session_id="session-1",
        is_resume=False,
    )


def test_agent_options_use_project_cwd_and_export_sp_project_dir(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path, ["proj"])
    kwargs = _kwargs(workspace)
    assert kwargs["cwd"] == str(workspace / "proj")
    assert kwargs["env"]["SP_PROJECT_DIR"] == str(workspace / "proj")


def test_agent_options_export_sp_project_dir_for_the_root(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, [])
    kwargs = _kwargs(workspace)
    assert kwargs["cwd"] == str(workspace)
    assert kwargs["env"]["SP_PROJECT_DIR"] == str(workspace)


def test_agent_options_attach_transport_breaker_hooks(tmp_path: Path) -> None:
    from claude_agent_sdk import HookMatcher

    hooks = _kwargs(_workspace(tmp_path, []))["hooks"]
    assert set(hooks) == {"PreToolUse", "PostToolUse", "PostToolUseFailure"}
    for matchers in hooks.values():
        (matcher,) = matchers
        assert isinstance(matcher, HookMatcher)
        assert matcher.matcher == "mcp__signalpilot__.*|mcp__standalone-chat__.*"
        assert len(matcher.hooks) == 1


def test_standalone_options_point_at_the_dbt_project(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, ["dumpsters_dbt"])
    scratch = tmp_path / "scratch"
    options = build_agent_options(
        agent_model="m",
        agent_effort="medium",
        max_turns=5,
        history=[],
        system_prompt="p",
        mcp_config=None,
        run_id="run-1",
        runtime_app=None,
        project_directory=workspace,
        allowed_tools=["Bash"],
        artifact_server=object(),
        auth_config_override=None,
        agent_session=SimpleNamespace(
            session_id="agent-1", config_dir=tmp_path / "cfg"
        ),
        resume_agent_session=False,
        scratch=scratch,
        lifecycle=SimpleNamespace(sessions={}),
    )
    project = str(workspace / "dumpsters_dbt")
    assert options["cwd"] == project
    assert options["agent_env_overrides"]["SP_PROJECT_DIR"] == project
    assert options["agent_env_overrides"]["SP_CHAT_SCRATCH_DIRECTORY"] == str(scratch)
    assert options["additional_disallowed_tools"] == STANDALONE_DISALLOWED_MCP_TOOLS


def test_agent_env_overrides_without_project_dir_is_unchanged(tmp_path: Path) -> None:
    overrides = agent_env_overrides(config_dir=tmp_path, scratch=tmp_path / "s")
    assert set(overrides) == {
        "CLAUDE_CONFIG_DIR",
        "SP_CHAT_SCRATCH_DIRECTORY",
        "SP_CHAT_ARTIFACTS_DIRECTORY",
    }


def test_pinned_claude_code_cli_is_passed_to_the_sdk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A new model can need a newer Claude Code than the SDK bundles, so the
    image's pinned CLI (SP_CLAUDE_CODE_CLI) must reach ClaudeAgentOptions."""
    cli = tmp_path / "claude"
    cli.write_text("", encoding="utf-8")
    monkeypatch.setenv("SP_CLAUDE_CODE_CLI", str(cli))
    assert _kwargs(_workspace(tmp_path, []))["cli_path"] == str(cli)


def test_missing_or_unset_cli_keeps_the_bundled_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SP_CLAUDE_CODE_CLI", raising=False)
    assert "cli_path" not in _kwargs(_workspace(tmp_path, []))
    monkeypatch.setenv("SP_CLAUDE_CODE_CLI", str(tmp_path / "absent"))
    workspace = tmp_path / "second"
    workspace.mkdir()
    assert "cli_path" not in _kwargs(workspace)


def test_agent_runs_background_work_in_the_foreground() -> None:
    # A run ends at its result; a background subagent would never report.
    assert _build_agent_env(None, None)["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"] == "1"


def test_deferred_work_tools_are_always_disallowed() -> None:
    assert _build_disallowed_tools(disallow_file_edits=False) == DEFERRED_WORK_TOOLS
    disallowed = _build_disallowed_tools(
        disallow_file_edits=False, additional_disallowed_tools=["Agent", "Monitor"]
    )
    assert "ScheduleWakeup" in disallowed
    assert "Agent" in disallowed
    assert len(disallowed) == len(set(disallowed))
