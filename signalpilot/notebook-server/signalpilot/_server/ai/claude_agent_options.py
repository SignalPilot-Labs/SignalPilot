"""
ClaudeAgentOptions assembly for the notebook AI chat.

Builds the subprocess environment, the option kwargs (model, plugin,
tool policy, MCP servers, session continuity) and the disallowed-tool
list. No SDK calls happen here; ``claude_agent.py`` turns the returned
kwargs into ``ClaudeAgentOptions``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from signalpilot import _loggers
from signalpilot._server.ai.claude_agent_config import (
    _apply_auth_config,
    _normalized_sp_api_key,
)

if TYPE_CHECKING:
    from collections.abc import Callable

LOGGER = _loggers.sp_logger()

__all__ = [
    "FILE_EDIT_TOOLS",
    "_EFFORT_LEVELS",
    "_agent_effort",
    "_build_agent_env",
    "_build_agent_options_kwargs",
    "_build_disallowed_tools",
    "resolve_agent_cwd",
]

FILE_EDIT_TOOLS = ["Write", "Edit", "MultiEdit", "NotebookEdit", "Bash"]
# Tools that defer work past the end of the turn. A run ends at its result
# and the CLI process exits, so nothing ever wakes the agent back up; the
# deferred work is lost and poisons the next resume (see _build_agent_env).
DEFERRED_WORK_TOOLS = ["ScheduleWakeup", "CronCreate", "CronDelete", "CronList", "Monitor"]
_EFFORT_LEVELS = {"low", "medium", "high", "xhigh", "max"}


def _agent_effort(override: str | None = None) -> str:
    """Reasoning effort for the agent CLI. Defaults to medium."""
    effort = (override or os.getenv("SP_AGENT_EFFORT", "medium")).strip().lower()
    return effort if effort in _EFFORT_LEVELS else "medium"


def resolve_agent_cwd(workspace: str | None) -> tuple[str, str]:
    """The agent working directory and the dbt project directory.

    When the workspace holds exactly one ``dbt_project.yml`` in a direct
    subdirectory, both are that subdirectory, so ``cd models`` and every
    later relative path resolve after the CLI resets the shell directory.
    A ``dbt_project.yml`` at the root, none, or several keep the root.
    """
    root = Path(workspace or os.getcwd())
    try:
        if (root / "dbt_project.yml").is_file():
            return str(root), str(root)
        candidates = [
            child
            for child in root.iterdir()
            if child.is_dir() and (child / "dbt_project.yml").is_file()
        ]
    except OSError:
        return str(root), str(root)
    if len(candidates) == 1:
        project = str(candidates[0])
        return project, project
    return str(root), str(root)


def _build_agent_env(
    auth_config: dict[str, str] | None,
    agent_env_overrides: dict[str, str] | None,
) -> dict[str, str]:
    """Environment for the agent subprocess: os.environ + auth + overrides."""
    agent_env = dict(os.environ)
    # Run subagents and shell commands in the foreground. Since Claude Code
    # 2.1.280 the Agent tool launches subagents in the background by default.
    # The run ends at the main agent's result, so the agent reports without
    # the subagents' results, and the next resume finds the unfinished task,
    # injects its own turn and ends the run before the user's message.
    agent_env["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"] = "1"
    _apply_auth_config(agent_env, auth_config)
    if agent_env_overrides:
        agent_env.update(agent_env_overrides)
    if _normalized_sp_api_key(agent_env.get("SP_API_KEY", "")) == "":
        agent_env.pop("SP_API_KEY", None)
    # On Windows, python3 doesn't exist — create a shim so skills work
    if sys.platform == "win32":
        python_dir = os.path.dirname(sys.executable)
        agent_env["PATH"] = (
            python_dir + os.pathsep + agent_env.get("PATH", "")
        )
        # Set PYENV_VERSION so pyenv doesn't complain
        if "PYENV_VERSION" not in agent_env:
            agent_env["PYENV_VERSION"] = (
                f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
            )
    return agent_env


def claude_code_cli_path() -> str | None:
    """The pinned Claude Code CLI to run, or None for the SDK's bundled one.

    The SDK always prefers the CLI bundled in its wheel, which can lag the
    newest Claude Code; a new model can require a newer CLI than the SDK
    ships. The notebook image installs a pinned CLI and names it in
    SP_CLAUDE_CODE_CLI; a missing file falls back to the bundled CLI.
    """
    configured = os.getenv("SP_CLAUDE_CODE_CLI", "").strip()
    if not configured:
        return None
    if not Path(configured).is_file():
        LOGGER.warning(
            "SP_CLAUDE_CODE_CLI does not exist: %s; using the SDK's bundled CLI",
            configured,
        )
        return None
    return configured


def _build_agent_options_kwargs(
    *,
    model: str,
    effort: str | None,
    max_turns: int,
    system_prompt: str,
    cwd: str | None,
    agent_env: dict[str, str],
    disallowed_tools: list[str] | None,
    allowed_tools: list[str] | None,
    mcp_servers: dict[str, Any],
    app: Any | None,
    notebook_session_authorizer: Callable[[str], bool] | None,
    chat_session_id: str,
    is_resume: bool,
) -> dict[str, Any]:
    """Assemble the kwargs passed to ``ClaudeAgentOptions``."""
    from signalpilot._server.ai.transport_breaker import (
        build_transport_breaker_hooks,
    )

    effective_cwd, project_dir = resolve_agent_cwd(cwd)
    agent_env["SP_PROJECT_DIR"] = project_dir
    agent_options_kwargs: dict[str, Any] = {
        "model": model,
        "max_turns": max_turns,
        "permission_mode": "bypassPermissions",
        # Load ONLY user-scope settings. Without this the SDK defaults to
        # user+project+local; because cwd is the user's project directory,
        # the CLI reads that repo's .claude/settings*.json. If such a file
        # defines `apiKeyHelper` (or a settings `env` ANTHROPIC_API_KEY), the
        # CLI silently switches OAuth-subscription billing to x-api-key
        # billing and fails with "Credit balance is too low" (and would run
        # an arbitrary key-helper command from the user's repo). NOTE: an
        # empty list emits `--setting-sources=` which the CLI treats as
        # "default/all", so it does NOT isolate — use ["user"], matching the
        # benchmark's working SDK usage (benchmark/agent/sdk_runner.py).
        "setting_sources": ["user"],
        # Keep the Claude Code preset and APPEND our instructions, rather than
        # replacing the system prompt with a plain string. A plain string
        # drops the Claude Code identity, which is what OAuth-token billing
        # (Claude subscription) requires — without it the request bills to the
        # token's API credits and fails with "credit balance too low". This
        # mirrors the benchmark's SDK usage (claude_code preset, never a bare
        # string). See benchmark/agent/sdk_runner_baseline.py.
        "system_prompt": {
            "type": "preset",
            "preset": "claude_code",
            "append": system_prompt,
        },
        "cwd": effective_cwd,
        "env": agent_env,
        # Transport breaker: deny gateway tool calls with a concrete wait
        # after a transport failure; stop the run after three in a row.
        "hooks": build_transport_breaker_hooks(chat_session_id),
        # Reasoning effort. Medium keeps extended thinking useful without
        # long stalls before the first tool call. Override with
        # SP_AGENT_EFFORT (low|medium|high|xhigh|max).
        "effort": _agent_effort(effort),
    }
    cli_path = claude_code_cli_path()
    if cli_path:
        agent_options_kwargs["cli_path"] = cli_path
    plugin_path = os.getenv("SP_AGENT_PLUGIN_PATH", "").strip()
    if plugin_path:
        if Path(plugin_path).is_dir():
            # MCP servers provide tools; the local plugin independently
            # provides SignalPilot's workflow skills and verifier agents.
            # The SDK's skills option also enables the Skill tool without
            # weakening the explicit allowed-tool policy below.
            agent_options_kwargs["plugins"] = [
                {"type": "local", "path": plugin_path}
            ]
            agent_options_kwargs["skills"] = "all"
        else:
            LOGGER.warning(
                "SignalPilot agent plugin path does not exist: %s", plugin_path
            )
    if disallowed_tools:
        agent_options_kwargs["disallowed_tools"] = disallowed_tools
    if allowed_tools:
        agent_options_kwargs["allowed_tools"] = allowed_tools

    # MCP servers: external (SignalPilot gateway) + notebook tools
    all_mcp = dict(mcp_servers) if mcp_servers else {}

    if app is not None:
        try:
            from signalpilot._server.ai.notebook_mcp import (
                build_notebook_mcp_server,
            )
            from signalpilot._server.ai.tools.base import ToolContext

            tool_context = ToolContext(app=app)
            notebook_mcp = build_notebook_mcp_server(
                tool_context,
                session_authorizer=notebook_session_authorizer,
            )
            all_mcp["signalpilot-notebook"] = notebook_mcp
            LOGGER.info("Notebook MCP server attached to agent")
        except Exception as e:
            LOGGER.warning(f"Could not build notebook MCP server: {e}")

    if all_mcp:
        agent_options_kwargs["mcp_servers"] = all_mcp

    # Session continuity: resume existing session or start new with known ID
    if is_resume:
        agent_options_kwargs["resume"] = chat_session_id
    else:
        agent_options_kwargs["session_id"] = chat_session_id

    agent_options_kwargs["include_partial_messages"] = True
    # Echo each queued user message back into the stream at the point the
    # model takes it in (not when it was queued). The relay turns the echo
    # of a steering message into a steering_delivered event, so the chat
    # places the follow-up exactly where the agent read it.
    agent_options_kwargs["extra_args"] = {"replay-user-messages": None}
    return agent_options_kwargs


def _build_disallowed_tools(
    *,
    disallow_file_edits: bool,
    additional_disallowed_tools: list[str] | None = None,
) -> list[str]:
    disallowed = [
        *DEFERRED_WORK_TOOLS,
        *(FILE_EDIT_TOOLS if disallow_file_edits else []),
        *(additional_disallowed_tools or []),
    ]
    return list(dict.fromkeys(disallowed))
