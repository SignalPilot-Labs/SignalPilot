"""
System-prompt context injection for the notebook AI chat.

Appends the pieces of context that only make sense on a fresh (non-resumed)
session or for the file the user is viewing: reconstructed conversation
history, dbt project context, and the active-file block (notebook session
id or raw file contents).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from signalpilot import _loggers
from signalpilot._server.ai.claude_agent_config import _get_dbt_project_context

LOGGER = _loggers.sp_logger()

__all__ = [
    "_build_context_file_block",
    "_extend_system_prompt",
]


def _extend_system_prompt(
    system_prompt: str,
    *,
    is_resume: bool,
    message_history: list[dict[str, str]] | None,
    effective_cwd: str,
    context_file: str | None,
    effective_app: Any | None,
) -> str:
    """Return ``system_prompt`` with history, dbt and file context appended."""
    # Reconstruct context from message history if session was lost
    if not is_resume and message_history and len(message_history) > 1:
        history_lines = []
        for msg in message_history[:-1]:
            role = msg.get("role", "user").upper()
            content = msg.get("content", "")
            if content.strip():
                history_lines.append(f"[{role}]: {content}")
        if history_lines:
            history_text = "\n\n".join(history_lines)
            system_prompt += f"\n\n<previous_conversation>\n{history_text}\n</previous_conversation>\n"

    # Add dbt project context on first message
    if not is_resume:
        dbt_context = _get_dbt_project_context(effective_cwd)
        if dbt_context:
            system_prompt += f"\n\n{dbt_context}\n"

    # Inject active file context so the agent knows what the user is viewing
    if context_file:
        system_prompt += _build_context_file_block(
            context_file, effective_app, effective_cwd
        )

    return system_prompt


def _build_context_file_block(
    context_file: str,
    effective_app: Any | None,
    effective_cwd: str,
) -> str:
    """Describe the file the user is viewing: notebook session id or contents."""
    context_block = f"\n\n## Current File Context\nThe user is currently viewing: `{context_file}`\n"
    matched_session = False
    if effective_app is not None:
        try:
            from signalpilot._server.ai.tools.base import ToolContext

            tc = ToolContext(app=effective_app)
            cf_normalized = context_file.replace("\\", "/").strip("/")
            LOGGER.info(
                f"[Agent Context] Looking for file: {cf_normalized}"
            )
            for sid, sess in tc.session_manager.sessions.items():
                file_path = sess.app_file_manager.path
                if not file_path:
                    continue
                fp_str = str(file_path).replace("\\", "/")
                LOGGER.info(f"[Agent Context] Session {sid} -> {fp_str}")
                if (
                    fp_str == cf_normalized
                    or fp_str.endswith(
                        ("/" + cf_normalized, cf_normalized)
                    )
                    or os.path.basename(fp_str)
                    == os.path.basename(cf_normalized)
                ):
                    context_block += (
                        f"This notebook's session_id is: `{sid}`\n"
                    )
                    context_block += "Use this session_id with notebook tools (edit_notebook, run_cells, get_cell_runtime_data, etc.) to modify this notebook directly.\n"
                    LOGGER.info(
                        f"[Agent Context] Matched session {sid} for {context_file}"
                    )
                    matched_session = True
                    break
        except Exception as e:
            LOGGER.warning(
                f"Could not resolve session for context file: {e}"
            )

    # For non-notebook files (.sql, .yml, etc.), include the file contents
    if not matched_session:
        try:
            resolved = Path(context_file)
            if not resolved.is_absolute() and effective_app is not None:
                from signalpilot._server.ai.tools.base import ToolContext

                tc = ToolContext(app=effective_app)
                workspace_dir = getattr(
                    tc.session_manager.workspace, "directory", None
                )
                if workspace_dir:
                    resolved = Path(workspace_dir) / context_file
            if not resolved.is_absolute():
                resolved = Path(effective_cwd) / context_file
            if resolved.is_file():
                contents = resolved.read_text(
                    encoding="utf-8", errors="replace"
                )
                if len(contents) > 20000:
                    contents = contents[:20000] + "\n... (truncated)"
                ext = resolved.suffix.lower()
                lang = {
                    "sql": "sql",
                    "yml": "yaml",
                    "yaml": "yaml",
                    "json": "json",
                    "toml": "toml",
                }.get(ext.lstrip("."), "")
                context_block += f"\n```{lang}\n{contents}\n```\n"
        except Exception as e:
            LOGGER.debug(f"Could not read context file contents: {e}")

    return context_block
