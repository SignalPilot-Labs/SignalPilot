"""
Claude Agent SDK integration for the notebook AI chat.

Uses ClaudeSDKClient with session resume for multi-turn conversations.
Each notebook session gets a persistent chat session ID. Follow-up
messages resume the conversation via the SDK's `resume` option.

On Windows, the SDK spawns subprocesses which requires a ProactorEventLoop.
We run the agent in a separate thread with its own event loop.
"""

from __future__ import annotations

import asyncio
import os
import queue
import sys
import threading
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Any

from signalpilot import _loggers
from signalpilot._server.ai.claude_agent_config import (
    _apply_auth_config,
    _get_auth_config,
    _get_dbt_project_context,
    _get_mcp_servers_config,
    _get_system_prompt,
    _normalized_sp_api_key,
)
from signalpilot._server.ai.claude_agent_state import (
    AgentEvent,
    _active_agents,
    _ActiveAgent,
    _chat_sessions,
    _get_or_create_chat_session,
    _save_chat_sessions,
    buffer_event,
    clear_chat_session,
    clear_event_buffer,
    get_buffered_events,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable

    from signalpilot._types.ids import SessionId

LOGGER = _loggers.sp_logger()

__all__ = [
    "AgentEvent",
    "_apply_auth_config",
    "_chat_sessions",
    "_get_auth_config",
    "_get_or_create_chat_session",
    "_save_chat_sessions",
    "buffer_event",
    "clear_chat_session",
    "clear_event_buffer",
    "get_buffered_events",
    "run_notebook_agent",
    "stop_agent",
]

_DONE = object()
FILE_EDIT_TOOLS = ["Write", "Edit", "MultiEdit", "NotebookEdit", "Bash"]


def _run_agent_in_thread(
    agent_state: _ActiveAgent,
    message: str,
    model: str,
    max_turns: int,
    mcp_servers: dict[str, Any],
    system_prompt: str,
    chat_session_id: str,
    is_resume: bool,
    disallowed_tools: list[str] | None = None,
    allowed_tools: list[str] | None = None,
    app: Any | None = None,
    cwd: str | None = None,
    auth_config: dict[str, str] | None = None,
    notebook_session_authorizer: Callable[[str], bool] | None = None,
) -> None:
    """Run the agent SDK in a separate thread with session resume support."""
    event_queue = agent_state.event_queue

    try:
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            ClaudeSDKClient,
            ResultMessage,
            StreamEvent,
            TextBlock,
            ThinkingBlock,
            ToolResultBlock,
            ToolUseBlock,
            UserMessage,
        )
        from claude_agent_sdk.types import RateLimitEvent
    except ImportError:
        event_queue.put(
            AgentEvent(
                type="error",
                content="claude-agent-sdk not installed. Run: pip install claude-agent-sdk",
                is_error=True,
            )
        )
        event_queue.put(_DONE)
        return

    async def _run() -> None:
        agent_state.task = asyncio.current_task()
        turn_count = 0

        agent_env = dict(os.environ)
        _apply_auth_config(agent_env, auth_config)
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
        }
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

        options = ClaudeAgentOptions(**agent_options_kwargs)

        try:
            async with ClaudeSDKClient(options=options) as client:
                await client.query(message)
                async for msg in client.receive_messages():
                    if isinstance(msg, AssistantMessage):
                        turn_count += 1
                        for block in msg.content:
                            if isinstance(block, ThinkingBlock):
                                # Final authoritative thinking — replaces accumulated deltas
                                event_queue.put(
                                    AgentEvent(
                                        type="thinking",
                                        content=block.thinking,
                                        turn=turn_count,
                                    )
                                )
                            elif isinstance(block, TextBlock):
                                # Final authoritative text — replaces accumulated deltas
                                event_queue.put(
                                    AgentEvent(
                                        type="text",
                                        content=block.text,
                                        turn=turn_count,
                                    )
                                )
                            elif isinstance(block, ToolUseBlock):
                                event_queue.put(
                                    AgentEvent(
                                        type="tool_use",
                                        tool_name=block.name,
                                        tool_input=block.input,
                                        tool_call_id=getattr(block, "id", ""),
                                        turn=turn_count,
                                    )
                                )

                    elif isinstance(msg, UserMessage):
                        content = msg.content
                        if isinstance(content, list):
                            for block in content:
                                if isinstance(block, ToolResultBlock):
                                    result_str = (
                                        str(block.content)
                                        if hasattr(block, "content")
                                        else str(block)
                                    )
                                    event_queue.put(
                                        AgentEvent(
                                            type="tool_result",
                                            content=result_str[:5000],
                                            tool_call_id=getattr(
                                                block, "tool_use_id", ""
                                            ),
                                            is_error=getattr(
                                                block, "is_error", False
                                            ),
                                            turn=turn_count,
                                        )
                                    )

                    elif isinstance(msg, ResultMessage):
                        cost = getattr(msg, "total_cost_usd", None)
                        event_queue.put(
                            AgentEvent(
                                type="done",
                                content="",
                                cost_usd=cost,
                                turn=turn_count,
                            )
                        )
                        break  # Session complete for this query

                    elif isinstance(msg, RateLimitEvent):
                        info = msg.rate_limit_info
                        status = getattr(info, "status", None)
                        if status != "allowed":
                            event_queue.put(
                                AgentEvent(
                                    type="error",
                                    content="Rate limited. Try again shortly.",
                                    is_error=True,
                                    turn=turn_count,
                                )
                            )

                    elif isinstance(msg, StreamEvent):
                        event = msg.event
                        event_type = event.get("type", "")
                        delta = event.get("delta", {})
                        text = delta.get("text", "")
                        thinking = delta.get("thinking", "")

                        if text:
                            event_queue.put(
                                AgentEvent(
                                    type="text_delta",
                                    content=text,
                                    turn=turn_count,
                                )
                            )
                        elif thinking:
                            event_queue.put(
                                AgentEvent(
                                    type="thinking_delta",
                                    content=thinking,
                                    turn=turn_count,
                                )
                            )
                        elif event_type == "content_block_start":
                            block = event.get("content_block", {})
                            event_queue.put(
                                AgentEvent(
                                    type="block_start",
                                    content=block.get("type", ""),
                                    turn=turn_count,
                                )
                            )

        except asyncio.CancelledError:
            LOGGER.info("Agent task cancelled by user")
            raise
        except Exception as e:
            tb = traceback.format_exc()
            stderr = getattr(e, "stderr", None) or ""
            full_error = f"{type(e).__name__}: {e}\nstderr: {stderr}\n{tb}"
            LOGGER.error(f"Agent error: {full_error}")
            event_queue.put(
                AgentEvent(
                    type="error",
                    content=full_error,
                    is_error=True,
                    turn=turn_count,
                )
            )

    if sys.platform == "win32":
        loop = asyncio.ProactorEventLoop()
    else:
        loop = asyncio.new_event_loop()

    agent_state.loop = loop

    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_run())
    except asyncio.CancelledError:
        LOGGER.info("Agent thread: task was cancelled")
    except Exception as e:
        tb = traceback.format_exc()
        event_queue.put(
            AgentEvent(
                type="error",
                content=f"Thread error: {e}\n{tb}",
                is_error=True,
            )
        )
    finally:
        try:
            loop.close()
        except Exception:
            pass
        event_queue.put(_DONE)


def stop_agent(session_id: str) -> bool:
    """Stop a running agent for the given session. Returns True if found."""
    agent = _active_agents.get(session_id)
    if agent is None:
        return False

    # Cancel the async task in the agent's event loop
    if agent.task and agent.loop and not agent.loop.is_closed():
        try:
            agent.loop.call_soon_threadsafe(agent.task.cancel)
        except RuntimeError:
            pass

    # Signal the SSE loop to exit
    agent.event_queue.put(_DONE)

    LOGGER.info(f"Agent stopped for session {session_id}")
    return True


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


async def run_notebook_agent(
    message: str,
    session_id: SessionId,
    model: str = "claude-opus-4-6",
    max_turns: int = 50,
    new_chat: bool = False,
    message_history: list[dict[str, str]] | None = None,
    system_prompt_override: str | None = None,
    mcp_config: dict[str, Any] | None = None,
    thread_id: str | None = None,
    notebook_mcp_app: Any | None = None,
    app: Any | None = None,
    context_file: str | None = None,
    cwd: str | None = None,
    disallow_file_edits: bool = False,
    additional_disallowed_tools: list[str] | None = None,
    allowed_tools: list[str] | None = None,
    additional_mcp_servers: dict[str, Any] | None = None,
    persist_session_mapping: bool = True,
    auth_config_override: dict[str, str] | None = None,
    notebook_session_authorizer: Callable[[str], bool] | None = None,
) -> AsyncGenerator[AgentEvent, None]:
    """
    Run the Claude Agent SDK for a chat message.

    The agent uses Claude Code's built-in tools (Write, Bash, Read, Edit)
    plus notebook MCP tools (edit_notebook, run_cells, get_cell_runtime_data, etc.)
    when a Starlette app reference is available.

    Uses session resume for multi-turn conversations.
    """
    auth = auth_config_override or _get_auth_config()

    effective_app = notebook_mcp_app or app
    chat_session_key = thread_id or str(session_id)

    if new_chat:
        clear_chat_session(chat_session_key, persist=persist_session_mapping)

    chat_session_id, is_resume = _get_or_create_chat_session(
        chat_session_key,
        persist=persist_session_mapping,
    )

    effective_cwd = cwd or os.getcwd()
    mcp_servers = _get_mcp_servers_config(mcp_config)
    if additional_mcp_servers:
        mcp_servers.update(additional_mcp_servers)
    system_prompt = system_prompt_override or _get_system_prompt()
    disallowed_tools = _build_disallowed_tools(
        disallow_file_edits=disallow_file_edits,
        additional_disallowed_tools=additional_disallowed_tools,
    )

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

        system_prompt += context_block

    agent = _ActiveAgent()
    _active_agents[str(session_id)] = agent

    thread = threading.Thread(
        target=_run_agent_in_thread,
        args=(
            agent,
            message,
            model,
            max_turns,
            mcp_servers,
            system_prompt,
            chat_session_id,
            is_resume,
            disallowed_tools,
            allowed_tools,
            effective_app,
            effective_cwd,
            auth,
            notebook_session_authorizer,
        ),
        daemon=True,
    )
    agent.thread = thread
    thread.start()

    try:
        while True:
            try:
                event = agent.event_queue.get(timeout=0.1)
            except queue.Empty:
                await asyncio.sleep(0.05)
                continue

            if event is _DONE:
                break
            if isinstance(event, AgentEvent):
                yield event
    finally:
        _active_agents.pop(str(session_id), None)
