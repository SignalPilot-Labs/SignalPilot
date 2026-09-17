"""Keyword options for `run_notebook_agent` in one standalone chat attempt."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from signalpilot._server.ai.claude_agent_options import resolve_agent_cwd
from signalpilot._server.api.endpoints.standalone_chat_prompt import (
    STANDALONE_DISALLOWED_MCP_TOOLS,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from signalpilot._server.ai.standalone_chat_lifecycle import (
        StandaloneNotebookLifecycle,
    )


def agent_env_overrides(
    *, config_dir: Path, scratch: Path, project_dir: Path | None = None
) -> dict[str, str]:
    """Environment the agent shell and every tool subprocess inherit.

    The system prompt directs every scratch file to `SP_CHAT_SCRATCH_DIRECTORY`
    and every user-facing file to `SP_CHAT_ARTIFACTS_DIRECTORY`. Without
    these the agent's shell resolves the paths to an empty string and files
    land outside the swept scratch, invisible to the artifacts panel.
    `SP_PROJECT_DIR` names the dbt project directory the agent starts in.
    """
    overrides = {
        "CLAUDE_CONFIG_DIR": str(config_dir),
        "SP_CHAT_SCRATCH_DIRECTORY": str(scratch),
        "SP_CHAT_ARTIFACTS_DIRECTORY": str(scratch / "artifacts"),
    }
    if project_dir is not None:
        overrides["SP_PROJECT_DIR"] = str(project_dir)
    return overrides


def build_agent_options(
    *,
    agent_model: str,
    agent_effort: str,
    max_turns: int,
    history: list[dict[str, str]],
    system_prompt: str,
    mcp_config: Any,
    run_id: str,
    runtime_app: Any,
    project_directory: Path,
    allowed_tools: Sequence[str],
    artifact_server: Any,
    auth_config_override: dict[str, str] | None,
    agent_session: Any,
    resume_agent_session: bool,
    scratch: Path,
    lifecycle: StandaloneNotebookLifecycle,
) -> dict[str, Any]:
    """Assemble the keyword arguments for one `run_notebook_agent` call."""
    agent_cwd, project_dir = resolve_agent_cwd(str(project_directory))
    return {
        "model": agent_model,
        "effort": agent_effort,
        "max_turns": max_turns,
        "new_chat": False,
        "message_history": history,
        "system_prompt_override": system_prompt,
        "mcp_config": mcp_config,
        "thread_id": f"standalone:{run_id}",
        "notebook_mcp_app": runtime_app,
        # The dbt project directory when the workspace holds exactly one,
        # so relative paths survive the CLI's per-call cwd reset.
        "cwd": agent_cwd,
        # Expose the normal SignalPilot workflow. Xata branch control stays
        # denied because this run is already pinned to a frozen project
        # branch and database connection.
        "disallow_file_edits": False,
        "additional_disallowed_tools": STANDALONE_DISALLOWED_MCP_TOOLS,
        "allowed_tools": list(allowed_tools),
        "additional_mcp_servers": {"standalone-chat": artifact_server},
        "persist_session_mapping": False,
        "auth_config_override": auth_config_override,
        "chat_session_id_override": agent_session.session_id,
        "resume_session_override": resume_agent_session,
        "agent_env_overrides": agent_env_overrides(
            config_dir=agent_session.config_dir,
            scratch=scratch,
            project_dir=Path(project_dir),
        ),
        "notebook_session_authorizer": (
            lambda candidate, lifecycle=lifecycle: (
                candidate in lifecycle.sessions.values()
            )
        ),
    }
