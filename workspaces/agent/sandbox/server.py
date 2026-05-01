"""Workspaces Sandbox Server — HTTP API app wiring.

Starts the aiohttp app, installs auth middleware, and registers the four
endpoint groups (execute, session, file_system, health). All request
handling lives under handlers/.
"""

import hmac
import logging
import os

from aiohttp import web

from config.loader import sandbox_config
from constants import (
    INTERNAL_SECRET_ENV_VAR,
    INTERNAL_SECRET_HEADER,
    SANDBOX_HOST,
    SANDBOX_PORT,
)
from handlers.execute import register as register_execute
from handlers.file_system import register as register_file_system
from handlers.health import register as register_health
from handlers.session import register as register_session
from session.manager import SessionManager

cfg = sandbox_config()

logging.basicConfig(level=getattr(logging, cfg.get("log_level", "info").upper()))
log = logging.getLogger("sandbox.server")


# Cache the internal secret in Python memory at import time, then scrub
# it from os.environ so subprocesses spawned by the SDK Bash tool (and
# anything else running in this process) cannot inherit it. The sandbox
# process keeps it in memory for auth_middleware — nothing on the OS env.
_INTERNAL_SECRET = os.environ.pop(INTERNAL_SECRET_ENV_VAR, "")
if not _INTERNAL_SECRET:
    raise RuntimeError(
        f"{INTERNAL_SECRET_ENV_VAR} is empty — sandbox cannot start",
    )


@web.middleware
async def auth_middleware(
    request: web.Request,
    handler,
) -> web.StreamResponse:
    """Check X-Internal-Secret header on all endpoints except /health."""
    if request.path == "/health":
        return await handler(request)

    provided = request.headers.get(INTERNAL_SECRET_HEADER, "")
    if not hmac.compare_digest(provided, _INTERNAL_SECRET):
        log.warning("Auth failed from %s on %s", request.remote, request.path)
        return web.json_response({"error": "unauthorized"}, status=401)

    return await handler(request)


async def on_startup(app: web.Application) -> None:
    """Initialize session manager."""
    app["sessions"] = SessionManager()


async def on_shutdown(app: web.Application) -> None:
    """Stop all active sessions."""
    sessions: SessionManager = app["sessions"]
    await sessions.stop_all()


def main() -> None:
    """Start the Workspaces Sandbox HTTP server."""
    app = web.Application(middlewares=[auth_middleware])
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    register_execute(app)
    register_session(app)
    register_file_system(app)
    register_health(app)

    log.info("Workspaces Sandbox server starting on :%d", SANDBOX_PORT)
    web.run_app(app, host=SANDBOX_HOST, port=SANDBOX_PORT)


if __name__ == "__main__":
    main()
