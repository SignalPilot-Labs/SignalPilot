"""
Claude Agent SDK integration for the notebook AI chat.

Uses ClaudeSDKClient with session resume for multi-turn conversations.
Each notebook session gets a persistent chat session ID. Follow-up
messages resume the conversation via the SDK's `resume` option.

On Windows, the SDK spawns subprocesses which requires a ProactorEventLoop.
We run the agent in a separate thread with its own event loop.

This module is the public entry point and the thread/event-loop
orchestrator. The pieces live in sibling modules:

- ``claude_agent_options``: ClaudeAgentOptions kwargs, env, tool policy
- ``claude_agent_events``: SDK message -> AgentEvent translation
- ``claude_agent_context``: system-prompt context injection
- ``claude_agent_state``: session/agent registries and event buffers
- ``claude_agent_config``: auth, MCP and system-prompt configuration
"""

from __future__ import annotations

import asyncio
import os
import queue
import sys
import threading
import traceback
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
from signalpilot._server.ai.claude_agent_context import (
    _build_context_file_block,
    _extend_system_prompt,
)
from signalpilot._server.ai.claude_agent_events import (
    _rate_limit_diagnostic,
    _relay_sdk_messages,
    _result_message_content,
    _SdkStreamState,
)
from signalpilot._server.ai.claude_agent_options import (
    _EFFORT_LEVELS,
    FILE_EDIT_TOOLS,
    _agent_effort,
    _build_agent_env,
    _build_agent_options_kwargs,
    _build_disallowed_tools,
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
    clip_tool_result_for_event,
    get_buffered_events,
    tool_result_text,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable

    from signalpilot._types.ids import SessionId

LOGGER = _loggers.sp_logger()

__all__ = [
    "FILE_EDIT_TOOLS",
    "_EFFORT_LEVELS",
    "AgentEvent",
    "_agent_effort",
    "_apply_auth_config",
    "_build_context_file_block",
    "_build_disallowed_tools",
    "_chat_sessions",
    "_extend_system_prompt",
    "_get_auth_config",
    "_get_dbt_project_context",
    "_get_mcp_servers_config",
    "_get_or_create_chat_session",
    "_get_system_prompt",
    "_normalized_sp_api_key",
    "_rate_limit_diagnostic",
    "_result_message_content",
    "_save_chat_sessions",
    "buffer_event",
    "clear_chat_session",
    "clear_event_buffer",
    "clip_tool_result_for_event",
    "get_buffered_events",
    "run_notebook_agent",
    "steer_agent",
    "stop_agent",
    "tool_result_text",
]

_DONE = object()


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
    agent_env_overrides: dict[str, str] | None = None,
) -> None:
    """Run the agent SDK in a separate thread with session resume support."""
    event_queue = agent_state.event_queue

    try:
        # Import every SDK symbol the relay loop needs up front so a missing
        # or incompatible SDK is reported as a single install error rather
        # than surfacing mid-run inside claude_agent_events.
        from claude_agent_sdk import (  # noqa: F401
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
        from claude_agent_sdk.types import RateLimitEvent  # noqa: F401
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
        stream = _SdkStreamState()

        agent_env = _build_agent_env(auth_config, agent_env_overrides)
        agent_options_kwargs = _build_agent_options_kwargs(
            model=model,
            max_turns=max_turns,
            system_prompt=system_prompt,
            cwd=cwd,
            agent_env=agent_env,
            disallowed_tools=disallowed_tools,
            allowed_tools=allowed_tools,
            mcp_servers=mcp_servers,
            app=app,
            notebook_session_authorizer=notebook_session_authorizer,
            chat_session_id=chat_session_id,
            is_resume=is_resume,
        )
        options = ClaudeAgentOptions(**agent_options_kwargs)

        try:
            async with ClaudeSDKClient(options=options) as client:
                agent_state.client = client
                await client.query(message)
                await _relay_sdk_messages(
                    client, agent_state, event_queue, stream
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
                    content=str(e) if str(e) else repr(e),
                    full_trace=full_error,
                    diagnostic_context={"error_type": type(e).__name__},
                    is_error=True,
                    turn=stream.turn_count,
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
                content=str(e) if str(e) else repr(e),
                full_trace=tb,
                diagnostic_context={"error_type": type(e).__name__},
                is_error=True,
            )
        )
    finally:
        agent_state.client = None
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


async def steer_agent(session_id: str, message: str, steering_id: str) -> bool:
    """Queue a user message on a live SDK client without interrupting it."""
    agent = _active_agents.get(session_id)
    if (
        agent is None
        or agent.client is None
        or agent.loop is None
        or agent.loop.is_closed()
        or agent.task is None
        or agent.task.done()
    ):
        return False
    if steering_id in agent.accepted_steering_ids:
        return True
    agent.accepted_steering_ids.add(steering_id)
    future = asyncio.run_coroutine_threadsafe(
        agent.client.query(message),
        agent.loop,
    )
    try:
        await asyncio.wrap_future(future)
        agent.pending_steering_turns += 1
    except Exception:
        agent.accepted_steering_ids.discard(steering_id)
        raise
    LOGGER.info("Queued steering message for session %s", session_id)
    return True


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
    chat_session_id_override: str | None = None,
    resume_session_override: bool | None = None,
    agent_env_overrides: dict[str, str] | None = None,
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

    if chat_session_id_override is not None:
        chat_session_id = chat_session_id_override
        is_resume = bool(resume_session_override)
    else:
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

    system_prompt = _extend_system_prompt(
        system_prompt,
        is_resume=is_resume,
        message_history=message_history,
        effective_cwd=effective_cwd,
        context_file=context_file,
        effective_app=effective_app,
    )

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
            agent_env_overrides,
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
