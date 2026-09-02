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
]

FILE_EDIT_TOOLS = ["Write", "Edit", "MultiEdit", "NotebookEdit", "Bash"]
_EFFORT_LEVELS = {"low", "medium", "high", "xhigh", "max"}


def _agent_effort() -> str:
    """Reasoning effort for the agent CLI. Defaults to medium."""
    effort = os.getenv("SP_AGENT_EFFORT", "medium").strip().lower()
    return effort if effort in _EFFORT_LEVELS else "medium"


def _build_agent_env(
    auth_config: dict[str, str] | None,
    agent_env_overrides: dict[str, str] | None,
) -> dict[str, str]:
    """Environment for the agent subprocess: os.environ + auth + overrides."""
    agent_env = dict(os.environ)
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


def _build_agent_options_kwargs(
    *,
    model: str,
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
        "cwd": cwd or os.getcwd(),
        "env": agent_env,
        # Reasoning effort. Medium keeps extended thinking useful without
        # long stalls before the first tool call. Override with
        # SP_AGENT_EFFORT (low|medium|high|xhigh|max).
        "effort": _agent_effort(),
    }
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
    return agent_options_kwargs


def _build_disallowed_tools(
    *,
    disallow_file_edits: bool,
    additional_disallowed_tools: list[str] | None = None,
) -> list[str] | None:
    disallowed = [
        *(FILE_EDIT_TOOLS if disallow_file_edits else []),
        *(additional_disallowed_tools or []),
    ]
    if not disallowed:
        return None
    return list(dict.fromkeys(disallowed))
