from __future__ import annotations

from typing import TYPE_CHECKING, Any

from starlette.authentication import requires
from starlette.exceptions import HTTPException
from starlette.responses import (
    PlainTextResponse,
    Response,
    StreamingResponse,
)

from signalpilot import _loggers
from signalpilot._server.api.deps import AppState
from signalpilot._server.router import APIRouter
from signalpilot._utils.http import HTTPStatus

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from starlette.requests import Request

# Taken from pydantic_ai.ui import SSE_CONTENT_TYPE
SSE_CONTENT_TYPE = "text/event-stream"


LOGGER = _loggers.sp_logger()

# Router for file ai
router = APIRouter()

# Active notebook MCP servers keyed by session_id (for tool result routing)
_active_notebook_servers: dict[str, Any] = {}


@router.post("/agent_stop")
@requires("edit")
async def agent_stop(
    *,
    request: Request,
) -> Response:
    """Stop a running agent chat for the current session."""
    from signalpilot._server.ai.claude_agent import stop_agent

    app_state = AppState(request)
    app_state.require_current_session()
    session_id = app_state.require_current_session_id()

    stopped = stop_agent(str(session_id))
    return PlainTextResponse("stopped" if stopped else "no active agent")


@router.post("/agent_chat")
@requires("edit")
async def agent_chat(
    *,
    request: Request,
) -> StreamingResponse:
    """
    Chat endpoint using Claude Agent SDK with MCP tools.

    Streams SSE events (text, thinking, tool_use, tool_result, done, error).
    Frontend tools (edit_notebook, run_stale_cells) are sent as tool_use events.
    The frontend executes them locally and POSTs results to /ai/agent_tool_result.
    """
    import json

    from signalpilot._server.ai.claude_agent import (
        run_notebook_agent,
    )

    app_state = AppState(request)
    app_state.require_current_session()
    session_id = app_state.require_current_session_id()

    # Parse body directly (simpler than ChatRequest which requires context/include_other_code)
    body = await request.json()

    # Extract the latest user message
    user_message = ""
    ui_messages = body.get("ui_messages", [])
    if ui_messages:
        last_msg = ui_messages[-1]
        if isinstance(last_msg, dict):
            parts = last_msg.get("parts", [])
            for part in parts:
                if isinstance(part, dict) and part.get("type") == "text":
                    user_message = part.get("text", "")
                    break
            if not user_message:
                user_message = last_msg.get("content", "")
        else:
            user_message = str(last_msg)

    # Also accept a simple "message" field
    if not user_message:
        user_message = body.get("message", "")

    # Check if this is a new chat (clears session history)
    new_chat = body.get("new_chat", False)

    if not user_message:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="No user message found in request",
        )

    # Pass message history for context reconstruction after server restart
    message_history = []
    for msg in ui_messages:
        if isinstance(msg, dict):
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role and content:
                message_history.append({"role": role, "content": content})

    from signalpilot._server.ai.claude_agent import (
        buffer_event,
        clear_event_buffer,
    )

    if new_chat:
        clear_event_buffer(str(session_id))

    async def event_stream() -> AsyncGenerator[str, None]:
        try:
            async for event in run_notebook_agent(
                message=user_message,
                session_id=session_id,
                new_chat=new_chat,
                message_history=message_history,
                app=request.app,
            ):
                event_data = {
                    "type": event.type,
                    "content": event.content,
                    "tool_name": event.tool_name,
                    "tool_input": event.tool_input,
                    "tool_call_id": event.tool_call_id,
                    "is_error": event.is_error,
                    "cost_usd": event.cost_usd,
                    "turn": event.turn,
                }
                idx = buffer_event(str(session_id), event_data)
                data = json.dumps({**event_data, "idx": idx}, default=str)
                yield f"data: {data}\n\n"
        except Exception as e:
            LOGGER.error(f"Error in agent chat stream: {e}")
            yield f"data: {json.dumps({'type': 'error', 'content': str(e), 'is_error': True})}\n\n"
        finally:
            _active_notebook_servers.pop(str(session_id), None)

    return StreamingResponse(
        event_stream(),
        media_type=SSE_CONTENT_TYPE,
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/agent_events")
@requires("edit")
async def get_agent_events(
    *,
    request: Request,
) -> Response:
    """Get buffered agent events for catch-up after tab refocus."""
    import json as json_mod

    from signalpilot._server.ai.claude_agent import get_buffered_events

    app_state = AppState(request)
    session_id = app_state.require_current_session_id()

    body = await request.json()
    after_index = body.get("afterIndex", -1)

    events = get_buffered_events(str(session_id), after_index)
    return Response(
        content=json_mod.dumps({"events": events, "count": len(events)}),
        media_type="application/json",
    )
