"""In-process session, cancellation, and event-buffer state for Claude chat."""

from __future__ import annotations

import json
import queue
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import asyncio
    import threading

_SESSIONS_FILE = Path(__file__).parent / ".chat_sessions.json"


def _load_chat_sessions() -> dict[str, str]:
    try:
        if _SESSIONS_FILE.exists():
            return json.loads(_SESSIONS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


_chat_sessions: dict[str, str] = _load_chat_sessions()


def _save_chat_sessions() -> None:
    try:
        _SESSIONS_FILE.write_text(
            json.dumps(_chat_sessions, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


@dataclass
class AgentEvent:
    """A streaming event from the Claude Agent."""

    type: str
    content: str = ""
    tool_name: str = ""
    tool_input: dict[str, Any] | None = None
    tool_call_id: str = ""
    is_error: bool = False
    cost_usd: float | None = None
    usage: dict[str, Any] | None = None
    # Tool-use id of the Agent spawn this event belongs to. Empty for the
    # top-level agent; set on every event produced inside a subagent so the
    # UX can group a subagent's work under its spawn.
    parent_tool_call_id: str = ""
    turn: int = 0
    result_subtype: str = ""
    stop_reason: str = ""
    num_turns: int = 0


@dataclass
class _ActiveAgent:
    """Tracks a running agent thread so it can be cancelled or steered."""

    event_queue: queue.Queue[AgentEvent | object] = field(
        default_factory=queue.Queue
    )
    thread: threading.Thread | None = None
    loop: asyncio.AbstractEventLoop | None = None
    task: asyncio.Task[None] | None = None
    client: Any | None = None
    accepted_steering_ids: set[str] = field(default_factory=set)
    pending_steering_turns: int = 0


_active_agents: dict[str, _ActiveAgent] = {}
_event_buffers: dict[str, list[dict[str, Any]]] = {}
MAX_BUFFER_EVENTS = 500


def buffer_event(
    session_id: str,
    event_data: dict[str, Any],
    *,
    thread_id: str | None = None,
) -> int:
    """Add an event to the buffer. Returns the event index."""
    buffer_key = thread_id or session_id
    if buffer_key not in _event_buffers:
        _event_buffers[buffer_key] = []
    buf = _event_buffers[buffer_key]
    buf.append(event_data)
    if len(buf) > MAX_BUFFER_EVENTS:
        _event_buffers[buffer_key] = buf[-MAX_BUFFER_EVENTS:]
    return len(buf) - 1


def get_buffered_events(
    session_id: str,
    after_index: int = -1,
    *,
    thread_id: str | None = None,
) -> list[dict[str, Any]]:
    """Get events after the given index."""
    buf = _event_buffers.get(thread_id or session_id, [])
    return buf[after_index + 1 :]


def clear_event_buffer(
    session_id: str, *, thread_id: str | None = None
) -> None:
    """Clear the event buffer for a session."""
    _event_buffers.pop(thread_id or session_id, None)


def _get_or_create_chat_session(
    notebook_session_id: str,
    *,
    persist: bool = True,
) -> tuple[str, bool]:
    """Get or create a Claude chat session. Returns (id, is_resume)."""
    if notebook_session_id in _chat_sessions:
        return _chat_sessions[notebook_session_id], True
    chat_id = str(uuid.uuid4())
    _chat_sessions[notebook_session_id] = chat_id
    if persist:
        _save_chat_sessions()
    return chat_id, False


def clear_chat_session(
    notebook_session_id: str, *, persist: bool = True
) -> None:
    """Clear the chat session for a new conversation."""
    _chat_sessions.pop(notebook_session_id, None)
    if persist:
        _save_chat_sessions()
