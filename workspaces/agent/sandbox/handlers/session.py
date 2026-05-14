"""Claude SDK session HTTP handlers for the sandbox.

Thin wrappers around SessionManager: start, stream events, send follow-up
messages, interrupt, stop. Each session is owned by the manager instance
stored on the aiohttp app under the "sessions" key.
"""

import asyncio
import json
import logging

from aiohttp import web

from session.manager import SessionManager

log = logging.getLogger("sandbox.endpoints.session")


def _require_session(handler):
    """Decorator that maps 'not found' RuntimeError to HTTP 404."""
    async def wrapper(request: web.Request):
        try:
            return await handler(request)
        except RuntimeError as e:
            if "not found" in str(e):
                return web.json_response({"error": str(e)}, status=404)
            raise
    wrapper.__name__ = handler.__name__
    return wrapper


async def handle_start(request: web.Request) -> web.Response:
    """Start a new Claude SDK session."""
    sessions: SessionManager = request.app["sessions"]
    body = await request.json()
    session_id = await sessions.start(body)
    return web.json_response({"session_id": session_id})


@_require_session
async def handle_events(request: web.Request) -> web.StreamResponse:
    """Stream SSE events from a session."""
    session_id = request.match_info["session_id"]
    sessions: SessionManager = request.app["sessions"]
    queue = sessions.get_event_queue(session_id)

    response = web.StreamResponse()
    response.content_type = "text/event-stream"
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Connection"] = "keep-alive"
    await response.prepare(request)

    try:
        while True:
            event = await queue.get()
            event_type = event.get("event", "message")
            data = json.dumps(event.get("data", {}))
            payload = f"event: {event_type}\ndata: {data}\n\n"
            await response.write(payload.encode("utf-8"))

            if event_type in ("session_end", "session_error"):
                break
    except (asyncio.CancelledError, ConnectionResetError):
        pass

    return response


@_require_session
async def handle_message(request: web.Request) -> web.Response:
    """Send a follow-up message to a session."""
    session_id = request.match_info["session_id"]
    sessions: SessionManager = request.app["sessions"]
    body = await request.json()
    await sessions.send_message(session_id, body["text"])
    return web.json_response({"status": "sent"})


@_require_session
async def handle_interrupt(request: web.Request) -> web.Response:
    """Interrupt a session's current response."""
    session_id = request.match_info["session_id"]
    sessions: SessionManager = request.app["sessions"]
    await sessions.interrupt(session_id)
    return web.json_response({"status": "interrupted"})


@_require_session
async def handle_stop(request: web.Request) -> web.Response:
    """Stop a session."""
    session_id = request.match_info["session_id"]
    sessions: SessionManager = request.app["sessions"]
    await sessions.stop(session_id)
    return web.json_response({"status": "stopped"})


@_require_session
async def handle_unlock(request: web.Request) -> web.Response:
    """Unlock a session's time gate so end_session is allowed."""
    session_id = request.match_info["session_id"]
    sessions: SessionManager = request.app["sessions"]
    sessions.unlock(session_id)
    return web.json_response({"status": "unlocked"})


def register(app: web.Application) -> None:
    """Attach all /session/* routes to the aiohttp app."""
    app.router.add_post("/session/start", handle_start)
    app.router.add_get("/session/{session_id}/events", handle_events)
    app.router.add_post("/session/{session_id}/message", handle_message)
    app.router.add_post("/session/{session_id}/interrupt", handle_interrupt)
    app.router.add_post("/session/{session_id}/stop", handle_stop)
    app.router.add_post("/session/{session_id}/unlock", handle_unlock)
