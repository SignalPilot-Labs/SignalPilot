# Copyright 2026 SignalPilot. All rights reserved.
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
import json
import os
import queue
import sys
import threading
import traceback
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from signalpilot import _loggers

if TYPE_CHECKING:
    from signalpilot._server.ai.tools.base import ToolContext
    from signalpilot._types.ids import SessionId

LOGGER = _loggers.sp_logger()

INSTRUCTIONS_PATH = Path(__file__).parent / "instructions.md"


def _get_dbt_project_context(search_dir: str | None = None) -> str:
    from signalpilot._dbt.runner import (
        discover_dbt_projects,
        find_dbt_project,
        parse_dbt_project_yml,
    )

    project_dir = None
    for d in [d for d in [search_dir, os.getcwd()] if d]:
        project_dir = find_dbt_project(d)
        if project_dir:
            break

    if not project_dir and search_dir:
        projects = discover_dbt_projects(search_dir, max_depth=2)
        if projects:
            project_dir = projects[0].project_dir

    if not project_dir:
        projects = discover_dbt_projects(os.getcwd(), max_depth=2)
        if projects:
            project_dir = projects[0].project_dir

    if not project_dir:
        return ""

    info = parse_dbt_project_yml(project_dir)
    return (
        f"# Active dbt project\n"
        f"path: {project_dir}\n"
        f"name: {info.project_name or 'unknown'}\n"
        f"profile: {info.profile or 'default'}\n"
        f"model_paths: {', '.join(info.model_paths)}\n\n"
        f"IMPORTANT: Only work within this project directory. Do NOT search for "
        f"or access dbt projects elsewhere on the machine. All file reads, writes, "
        f"and dbt commands must be scoped to {project_dir}."
    )

_DONE = object()

# ── Persistent chat session mapping ──────────────────────────────
# Survives server restarts by saving to disk.

_SESSIONS_FILE = Path(__file__).parent / ".chat_sessions.json"

def _load_chat_sessions() -> dict[str, str]:
    try:
        if _SESSIONS_FILE.exists():
            return json.loads(_SESSIONS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _save_chat_sessions() -> None:
    try:
        _SESSIONS_FILE.write_text(
            json.dumps(_chat_sessions, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass

_chat_sessions: dict[str, str] = _load_chat_sessions()


@dataclass
class _ActiveAgent:
    """Tracks a running agent thread so it can be cancelled."""

    event_queue: queue.Queue[AgentEvent | object] = field(
        default_factory=queue.Queue
    )
    thread: threading.Thread | None = None
    loop: asyncio.AbstractEventLoop | None = None
    task: asyncio.Task[None] | None = None


_active_agents: dict[str, _ActiveAgent] = {}

# ── Event buffer for tab-away recovery ─────────────────────────
# Stores all agent events per session so the frontend can catch up
# when the tab comes back into focus.
_event_buffers: dict[str, list[dict[str, Any]]] = {}
MAX_BUFFER_EVENTS = 500


def buffer_event(session_id: str, event_data: dict[str, Any]) -> int:
    """Add an event to the buffer. Returns the event index."""
    if session_id not in _event_buffers:
        _event_buffers[session_id] = []
    buf = _event_buffers[session_id]
    buf.append(event_data)
    # Trim old events
    if len(buf) > MAX_BUFFER_EVENTS:
        _event_buffers[session_id] = buf[-MAX_BUFFER_EVENTS:]
    return len(buf) - 1


def get_buffered_events(session_id: str, after_index: int = -1) -> list[dict[str, Any]]:
    """Get events after the given index."""
    buf = _event_buffers.get(session_id, [])
    return buf[after_index + 1:]


def clear_event_buffer(session_id: str) -> None:
    """Clear the event buffer for a session."""
    _event_buffers.pop(session_id, None)


def _get_or_create_chat_session(notebook_session_id: str) -> tuple[str, bool]:
    """Get existing chat session ID or create a new one. Returns (id, is_resume)."""
    if notebook_session_id in _chat_sessions:
        return _chat_sessions[notebook_session_id], True
    chat_id = str(uuid.uuid4())
    _chat_sessions[notebook_session_id] = chat_id
    _save_chat_sessions()
    return chat_id, False


def clear_chat_session(notebook_session_id: str) -> None:
    """Clear the chat session (for 'new chat' button)."""
    _chat_sessions.pop(notebook_session_id, None)
    _save_chat_sessions()


@dataclass
class AgentEvent:
    """A streaming event from the Claude Agent."""

    type: str  # "text", "thinking", "tool_use", "tool_result", "error", "done"
    content: str = ""
    tool_name: str = ""
    tool_input: dict[str, Any] | None = None
    tool_call_id: str = ""
    is_error: bool = False
    cost_usd: float | None = None
    turn: int = 0


def _get_auth_config() -> dict[str, str]:
    """Get agent auth config. Supports OAuth token or Anthropic API key."""
    oauth = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "") or os.environ.get("OAUTH_TOKEN", "")
    if oauth:
        return {"type": "oauth", "token": oauth}

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key:
        return {"type": "api_key", "token": api_key}

    # Try fetching from gateway user secrets
    try:
        from signalpilot._server.files.project_sync import _gateway_url, _gateway_headers
        import httpx
        resp = httpx.get(
            f"{_gateway_url()}/api/user/secrets",
            headers=_gateway_headers(),
            timeout=5.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("has_anthropic_key"):
                # The full key isn't returned via GET for security.
                # It should be injected as env var by the gateway.
                pass
    except Exception:
        pass

    raise ValueError(
        "No AI credentials configured. Set CLAUDE_CODE_OAUTH_TOKEN or "
        "ANTHROPIC_API_KEY, or add your Anthropic API key in Settings."
    )


def _get_oauth_token() -> str:
    """Backward compat wrapper."""
    auth = _get_auth_config()
    return auth["token"]


def _get_mcp_servers_config() -> dict[str, Any]:
    from signalpilot._utils.localhost import fix_localhost_url
    servers: dict[str, Any] = {}
    sp_gateway_url = fix_localhost_url(os.environ.get("SP_GATEWAY_URL", "http://localhost:3300/mcp"))
    sp_session_jwt = os.environ.get("SP_SESSION_JWT", "")
    sp_api_key = os.environ.get("SP_API_KEY", "")
    auth_token = sp_session_jwt or sp_api_key
    if auth_token:
        servers["signalpilot"] = {
            "type": "http",
            "url": sp_gateway_url,
            "headers": {"Authorization": f"Bearer {auth_token}"},
        }
    return servers


def _get_system_prompt() -> str:
    if INSTRUCTIONS_PATH.exists():
        return INSTRUCTIONS_PATH.read_text(encoding="utf-8")
    return "You are an AI assistant helping with a reactive Python notebook."


def _run_agent_in_thread(
    agent_state: _ActiveAgent,
    message: str,
    model: str,
    max_turns: int,
    mcp_servers: dict[str, Any],
    system_prompt: str,
    chat_session_id: str,
    is_resume: bool,
    app: Any | None = None,
    cwd: str | None = None,
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
        event_queue.put(AgentEvent(
            type="error",
            content="claude-agent-sdk not installed. Run: pip install claude-agent-sdk",
            is_error=True,
        ))
        event_queue.put(_DONE)
        return

    async def _run() -> None:
        agent_state.task = asyncio.current_task()
        turn_count = 0

        agent_env = dict(os.environ)
        # On Windows, python3 doesn't exist — create a shim so skills work
        if sys.platform == "win32":
            python_dir = os.path.dirname(sys.executable)
            agent_env["PATH"] = python_dir + os.pathsep + agent_env.get("PATH", "")
            # Set PYENV_VERSION so pyenv doesn't complain
            if "PYENV_VERSION" not in agent_env:
                agent_env["PYENV_VERSION"] = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

        agent_options_kwargs: dict[str, Any] = {
            "model": model,
            "max_turns": max_turns,
            "permission_mode": "bypassPermissions",
            "system_prompt": system_prompt,
            "cwd": cwd or os.getcwd(),
            "env": agent_env,
        }

        # MCP servers: external (SignalPilot gateway) + notebook tools
        all_mcp = dict(mcp_servers) if mcp_servers else {}

        if app is not None:
            try:
                from signalpilot._server.ai.tools.base import ToolContext
                from signalpilot._server.ai.notebook_mcp import (
                    build_notebook_mcp_server,
                )

                tool_context = ToolContext(app=app)
                notebook_mcp = build_notebook_mcp_server(tool_context)
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
                                event_queue.put(AgentEvent(
                                    type="thinking",
                                    content=block.thinking,
                                    turn=turn_count,
                                ))
                            elif isinstance(block, TextBlock):
                                # Final authoritative text — replaces accumulated deltas
                                event_queue.put(AgentEvent(
                                    type="text",
                                    content=block.text,
                                    turn=turn_count,
                                ))
                            elif isinstance(block, ToolUseBlock):
                                event_queue.put(AgentEvent(
                                    type="tool_use",
                                    tool_name=block.name,
                                    tool_input=block.input,
                                    tool_call_id=getattr(block, "id", ""),
                                    turn=turn_count,
                                ))

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
                                    event_queue.put(AgentEvent(
                                        type="tool_result",
                                        content=result_str[:5000],
                                        tool_call_id=getattr(block, "tool_use_id", ""),
                                        is_error=getattr(block, "is_error", False),
                                        turn=turn_count,
                                    ))

                    elif isinstance(msg, ResultMessage):
                        cost = getattr(msg, "total_cost_usd", None)
                        event_queue.put(AgentEvent(
                            type="done",
                            content="",
                            cost_usd=cost,
                            turn=turn_count,
                        ))
                        break  # Session complete for this query

                    elif isinstance(msg, RateLimitEvent):
                        info = msg.rate_limit_info
                        status = getattr(info, "status", None)
                        if status != "allowed":
                            event_queue.put(AgentEvent(
                                type="error",
                                content="Rate limited. Try again shortly.",
                                is_error=True,
                                turn=turn_count,
                            ))

                    elif isinstance(msg, StreamEvent):
                        event = msg.event
                        event_type = event.get("type", "")
                        delta = event.get("delta", {})
                        text = delta.get("text", "")
                        thinking = delta.get("thinking", "")

                        if text:
                            event_queue.put(AgentEvent(
                                type="text_delta",
                                content=text,
                                turn=turn_count,
                            ))
                        elif thinking:
                            event_queue.put(AgentEvent(
                                type="thinking_delta",
                                content=thinking,
                                turn=turn_count,
                            ))
                        elif event_type == "content_block_start":
                            block = event.get("content_block", {})
                            event_queue.put(AgentEvent(
                                type="block_start",
                                content=block.get("type", ""),
                                turn=turn_count,
                            ))

        except asyncio.CancelledError:
            LOGGER.info("Agent task cancelled by user")
            raise
        except Exception as e:
            tb = traceback.format_exc()
            stderr = getattr(e, "stderr", None) or ""
            full_error = f"{type(e).__name__}: {e}\nstderr: {stderr}\n{tb}"
            LOGGER.error(f"Agent error: {full_error}")
            event_queue.put(AgentEvent(
                type="error",
                content=full_error,
                is_error=True,
                turn=turn_count,
            ))

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
        event_queue.put(AgentEvent(
            type="error",
            content=f"Thread error: {e}\n{tb}",
            is_error=True,
        ))
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


async def run_notebook_agent(
    message: str,
    session_id: SessionId,
    model: str = "claude-opus-4-6",
    max_turns: int = 50,
    new_chat: bool = False,
    message_history: list[dict[str, str]] | None = None,
    system_prompt_override: str | None = None,
    app: Any | None = None,
    context_file: str | None = None,
    cwd: str | None = None,
) -> AsyncGenerator[AgentEvent, None]:
    """
    Run the Claude Agent SDK for a chat message.

    The agent uses Claude Code's built-in tools (Write, Bash, Read, Edit)
    plus notebook MCP tools (edit_notebook, run_cells, get_cell_runtime_data, etc.)
    when a Starlette app reference is available.

    Uses session resume for multi-turn conversations.
    """
    auth = _get_auth_config()
    if auth["type"] == "oauth":
        os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = auth["token"]
    else:
        os.environ["ANTHROPIC_API_KEY"] = auth["token"]

    if new_chat:
        clear_chat_session(str(session_id))

    chat_session_id, is_resume = _get_or_create_chat_session(str(session_id))

    mcp_servers = _get_mcp_servers_config()
    system_prompt = system_prompt_override or _get_system_prompt()

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
        dbt_context = _get_dbt_project_context()
        if dbt_context:
            system_prompt += f"\n\n{dbt_context}\n"

    # Inject active file context so the agent knows what the user is viewing
    if context_file:
        context_block = f"\n\n## Current File Context\nThe user is currently viewing: `{context_file}`\n"
        matched_session = False
        if app is not None:
            try:
                from signalpilot._server.ai.tools.base import ToolContext
                tc = ToolContext(app=app)
                cf_normalized = context_file.replace("\\", "/").strip("/")
                LOGGER.info(f"[Agent Context] Looking for file: {cf_normalized}")
                for sid, sess in tc.session_manager.sessions.items():
                    file_path = sess.app_file_manager.path
                    if not file_path:
                        continue
                    fp_str = str(file_path).replace("\\", "/")
                    LOGGER.info(f"[Agent Context] Session {sid} -> {fp_str}")
                    if (
                        fp_str == cf_normalized
                        or fp_str.endswith("/" + cf_normalized)
                        or fp_str.endswith(cf_normalized)
                        or os.path.basename(fp_str) == os.path.basename(cf_normalized)
                    ):
                        context_block += f"This notebook's session_id is: `{sid}`\n"
                        context_block += "Use this session_id with notebook tools (edit_notebook, run_cells, get_cell_runtime_data, etc.) to modify this notebook directly.\n"
                        LOGGER.info(f"[Agent Context] Matched session {sid} for {context_file}")
                        matched_session = True
                        break
            except Exception as e:
                LOGGER.warning(f"Could not resolve session for context file: {e}")

        # For non-notebook files (.sql, .yml, etc.), include the file contents
        if not matched_session:
            try:
                resolved = Path(context_file)
                if not resolved.is_absolute() and app is not None:
                    from signalpilot._server.ai.tools.base import ToolContext
                    tc = ToolContext(app=app)
                    workspace_dir = getattr(tc.session_manager.workspace, "directory", None)
                    if workspace_dir:
                        resolved = Path(workspace_dir) / context_file
                if resolved.is_file():
                    contents = resolved.read_text(encoding="utf-8", errors="replace")
                    if len(contents) > 20000:
                        contents = contents[:20000] + "\n... (truncated)"
                    ext = resolved.suffix.lower()
                    lang = {"sql": "sql", "yml": "yaml", "yaml": "yaml", "json": "json", "toml": "toml"}.get(ext.lstrip("."), "")
                    context_block += f"\n```{lang}\n{contents}\n```\n"
            except Exception as e:
                LOGGER.debug(f"Could not read context file contents: {e}")

        system_prompt += context_block

    agent = _ActiveAgent()
    _active_agents[str(session_id)] = agent

    thread = threading.Thread(
        target=_run_agent_in_thread,
        args=(
            agent, message, model, max_turns, mcp_servers,
            system_prompt, chat_session_id, is_resume, app, cwd,
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
