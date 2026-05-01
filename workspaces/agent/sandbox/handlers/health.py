"""Health check HTTP handler for the sandbox."""

from aiohttp import web

from session.manager import SessionManager


async def handle_health(request: web.Request) -> web.Response:
    """Return health status with active session count."""
    sessions: SessionManager = request.app["sessions"]
    return web.json_response({
        "status": "healthy",
        "active_sessions": sessions.active_count(),
    })


def register(app: web.Application) -> None:
    """Attach /health route to the aiohttp app."""
    app.router.add_get("/health", handle_health)
