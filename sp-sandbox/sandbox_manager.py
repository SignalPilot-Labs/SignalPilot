"""
Sandbox Manager — HTTP API for gVisor sandboxed code execution.

Endpoints:
    GET  /health         — Health check and instance counts
    GET  /vms            — List active sandbox instances
    POST /execute        — Execute Python code in an isolated gVisor sandbox
    DELETE /vm/{vm_id}   — Terminate a sandbox instance

Run:
    python3 sandbox_manager.py
"""

from __future__ import annotations

import logging
import uuid

from aiohttp import web

from constants import HOST, MAX_CODE_LENGTH, MAX_TIMEOUT, MAX_VMS, MIN_TIMEOUT, PORT
from executor import GVisorExecutor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("sandbox_manager")

executor = GVisorExecutor()
active_sessions: dict[str, str] = {}  # session_token -> vm_id


async def health_handler(request: web.Request) -> web.Response:
    """GET /health — report sandbox manager status."""
    return web.json_response({
        "status": "healthy",
        "active_vms": len(active_sessions),
        "max_vms": MAX_VMS,
    })


async def list_vms_handler(request: web.Request) -> web.Response:
    """GET /vms — list active sandbox instances."""
    vms = [
        {"vm_id": vm_id, "session_token": token}
        for token, vm_id in active_sessions.items()
    ]
    return web.json_response({"active_vms": vms})


async def execute_handler(request: web.Request) -> web.Response:
    """POST /execute — run Python code in a gVisor sandbox."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"success": False, "error": "Invalid JSON body"},
            status=400,
        )

    code = body.get("code", "")
    session_token = body.get("session_token", "")
    timeout = body.get("timeout", 30)
    vm_id = body.get("vm_id")

    if not code:
        return web.json_response(
            {"success": False, "error": "Missing required field: code"},
            status=400,
        )

    if len(code) > MAX_CODE_LENGTH:
        return web.json_response(
            {"success": False, "error": f"Code exceeds max length ({MAX_CODE_LENGTH} chars)"},
            status=400,
        )

    if not isinstance(timeout, (int, float)):
        timeout = 30
    timeout = max(MIN_TIMEOUT, min(int(timeout), MAX_TIMEOUT))

    if len(active_sessions) >= MAX_VMS and session_token not in active_sessions:
        return web.json_response(
            {"success": False, "error": "Rate limited — too many sandbox requests"},
            status=429,
        )

    if vm_id is None:
        vm_id = str(uuid.uuid4())

    active_sessions[session_token] = vm_id

    logger.info(
        "execute: session=%s vm=%s timeout=%ds code_len=%d",
        session_token[:8],
        vm_id[:8],
        timeout,
        len(code),
    )

    result = await executor.execute(code, vm_id, timeout)

    if not result.success:
        active_sessions.pop(session_token, None)

    return web.json_response({
        "success": result.success,
        "output": result.output,
        "error": result.error,
        "vm_id": result.vm_id,
        "execution_ms": round(result.execution_ms, 2),
    })


async def kill_vm_handler(request: web.Request) -> web.Response:
    """DELETE /vm/{vm_id} — terminate a sandbox instance."""
    vm_id = request.match_info["vm_id"]

    killed = await executor.kill(vm_id)

    tokens_to_remove = [
        t for t, v in active_sessions.items() if v == vm_id
    ]
    for token in tokens_to_remove:
        del active_sessions[token]

    if killed:
        logger.info("killed vm=%s", vm_id[:8])
        return web.json_response({"status": "killed"})

    return web.json_response({"status": "not_found"}, status=404)


async def on_shutdown(app: web.Application) -> None:
    """Clean up all sandbox resources on shutdown."""
    logger.info("shutting down — cleaning up sandboxes")
    await executor.cleanup()


def create_app() -> web.Application:
    """Create the aiohttp application."""
    app = web.Application()
    app.router.add_get("/health", health_handler)
    app.router.add_get("/vms", list_vms_handler)
    app.router.add_post("/execute", execute_handler)
    app.router.add_delete("/vm/{vm_id}", kill_vm_handler)
    app.on_shutdown.append(on_shutdown)
    return app


if __name__ == "__main__":
    logger.info("starting sandbox manager on %s:%d (max_vms=%d)", HOST, PORT, MAX_VMS)
    app = create_app()
    web.run_app(app, host=HOST, port=PORT, print=None)
