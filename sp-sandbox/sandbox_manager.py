"""
Sandbox Manager — HTTP API for gVisor sandboxed code execution.

Endpoints:
    GET  /health         — Health check and instance counts
    GET  /vms            — List active sandbox instances
    POST /execute        — Execute Python code in an isolated gVisor sandbox
    DELETE /vm/{vm_id}   — Terminate a sandbox instance
    GET  /files          — Browse host files (for local DB connections)

Run:
    python3 sandbox_manager.py
"""

from __future__ import annotations

import fnmatch
import hmac as _hmac
import logging
import os
import uuid
from pathlib import Path

from aiohttp import web

import audit
from constants import HOST, MAX_CODE_LENGTH, MAX_TIMEOUT, MAX_VMS, MIN_TIMEOUT, PORT
from executor import GVisorExecutor
from session_manager import KernelSessionManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("sandbox_manager")

executor = GVisorExecutor()
session_mgr = KernelSessionManager()
active_sessions: dict[str, str] = {}  # session_token -> vm_id

SANDBOX_AUTH_TOKEN = os.environ.get("SP_SANDBOX_TOKEN", "")


def _check_auth(request: web.Request) -> bool:
    """Verify X-Sandbox-Auth header matches SP_SANDBOX_TOKEN."""
    if not SANDBOX_AUTH_TOKEN:
        # No token configured — allow all connections (dev/docker-compose mode).
        # In production, always set SP_SANDBOX_TOKEN for defense-in-depth.
        return True
    provided = request.headers.get("X-Sandbox-Auth", "")
    return _hmac.compare_digest(provided, SANDBOX_AUTH_TOKEN)


def _auth_denied() -> web.Response:
    return web.json_response({"error": "Unauthorized"}, status=401)


async def health_handler(request: web.Request) -> web.Response:
    """GET /health — report sandbox manager status."""
    if not _check_auth(request):
        return _auth_denied()
    return web.json_response({
        "status": "healthy",
        "active_vms": len(active_sessions),
        "max_vms": MAX_VMS,
    })


async def list_vms_handler(request: web.Request) -> web.Response:
    """GET /vms — list active sandbox instances."""
    if not _check_auth(request):
        return _auth_denied()
    vms = [
        {"vm_id": vm_id, "session_token": token[:8] + "..."}
        for token, vm_id in active_sessions.items()
    ]
    return web.json_response({"active_vms": vms})


async def execute_handler(request: web.Request) -> web.Response:
    """POST /execute — run Python code in a gVisor sandbox."""
    if not _check_auth(request):
        return _auth_denied()
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
    file_mounts = body.get("file_mounts", [])  # [{"host_path": "...", "sandbox_path": "...", "readonly": true}]

    client_ip = request.remote

    if len(session_token) > 128:
        return web.json_response(
            {"error": "Invalid session token"},
            status=400,
        )

    if not code:
        return web.json_response(
            {"success": False, "error": "Missing required field: code"},
            status=400,
        )

    if len(code) > MAX_CODE_LENGTH:
        audit.log_execution(
            session_token=session_token,
            vm_id=vm_id or "",
            code_length=len(code),
            code_hash="",
            timeout=0,
            mount_count=0,
            success=False,
            error=f"Code exceeds max length ({MAX_CODE_LENGTH} chars)",
            execution_ms=0,
            client_ip=client_ip,
        )
        return web.json_response(
            {"success": False, "error": f"Code exceeds max length ({MAX_CODE_LENGTH} chars)"},
            status=400,
        )

    if not isinstance(timeout, (int, float)):
        timeout = 30
    timeout = max(MIN_TIMEOUT, min(int(timeout), MAX_TIMEOUT))

    if len(active_sessions) >= MAX_VMS and session_token not in active_sessions:
        audit.log_execution(
            session_token=session_token,
            vm_id=vm_id or "",
            code_length=len(code),
            code_hash="",
            timeout=timeout,
            mount_count=0,
            success=False,
            error="Rate limited — too many sandbox requests",
            execution_ms=0,
            client_ip=client_ip,
        )
        return web.json_response(
            {"success": False, "error": "Rate limited — too many sandbox requests"},
            status=429,
        )

    if vm_id is None:
        vm_id = str(uuid.uuid4())

    # Validate file mounts
    validated_mounts = []
    host_data_root = Path("/host-data")
    for mount in file_mounts:
        host_path = mount.get("host_path", "")
        sandbox_name = mount.get("sandbox_path", "")
        if not host_path or not sandbox_name:
            continue
        # If path comes from the file browser (already under /host-data), use as-is.
        # Otherwise, try to map it: the host's home dir is mounted at /host-data
        resolved = Path(host_path).resolve()
        if not resolved.is_relative_to(Path("/host-data").resolve()):
            audit.log_execution(
                session_token=session_token,
                vm_id=vm_id,
                code_length=len(code),
                code_hash="",
                timeout=timeout,
                mount_count=0,
                success=False,
                error="Mount path not allowed",
                execution_ms=0,
                client_ip=client_ip,
            )
            return web.json_response(
                {"success": False, "error": "Mount path not allowed"},
                status=400,
            )
        if not resolved.exists() and host_data_root.exists():
            # Try stripping the host home prefix and mapping to /host-data
            # The file browser returns paths under /host-data already
            pass  # resolved stays as-is, will fail the exists() check below
        if not resolved.exists():
            return web.json_response(
                {"success": False, "error": f"Mount path does not exist: {host_path}"},
                status=400,
            )
        if not resolved.is_file():
            return web.json_response(
                {"success": False, "error": f"Mount path is not a file: {host_path}"},
                status=400,
            )
        # Only allow specific extensions for safety
        allowed_exts = {".duckdb", ".db", ".sqlite", ".sqlite3", ".parquet", ".csv", ".json"}
        if resolved.suffix.lower() not in allowed_exts:
            return web.json_response(
                {"success": False, "error": f"File type not allowed: {resolved.suffix}"},
                status=400,
            )
        validated_mounts.append({"host_path": str(resolved), "sandbox_path": sandbox_name})

    active_sessions[session_token] = vm_id

    logger.info(
        "execute: session=%s vm=%s timeout=%ds code_len=%d mounts=%d",
        session_token[:8],
        vm_id[:8],
        timeout,
        len(code),
        len(validated_mounts),
    )

    code_hash = audit.hash_code_for_audit(code)
    result = await executor.execute(code, vm_id, timeout, file_mounts=validated_mounts)

    # Clean up session after execution (these are one-shot, not persistent)
    active_sessions.pop(session_token, None)

    audit.log_execution(
        session_token=session_token,
        vm_id=result.vm_id,
        code_length=len(code),
        code_hash=code_hash,
        timeout=timeout,
        mount_count=len(validated_mounts),
        success=result.success,
        error=result.error,
        execution_ms=result.execution_ms,
        client_ip=client_ip,
    )

    return web.json_response({
        "success": result.success,
        "output": result.output,
        "error": result.error,
        "vm_id": result.vm_id,
        "execution_ms": round(result.execution_ms, 2),
    })


async def kill_vm_handler(request: web.Request) -> web.Response:
    """DELETE /vm/{vm_id} — terminate a sandbox instance."""
    if not _check_auth(request):
        return _auth_denied()
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


async def browse_files_handler(request: web.Request) -> web.Response:
    """GET /files — browse host filesystem for local DB files.

    Query params:
        path: directory to list (default: user home)
        pattern: glob pattern (default: *.duckdb)
    """
    if not _check_auth(request):
        return _auth_denied()
    # Default to /host-data (mounted from host) if it exists, else home dir
    default_path = "/host-data" if Path("/host-data").exists() else str(Path.home())
    search_path = request.query.get("path", default_path)
    pattern = request.query.get("pattern", "*.duckdb")

    resolved = Path(search_path).resolve()
    allowed_root = Path("/host-data").resolve() if Path("/host-data").exists() else Path.home().resolve()
    if not resolved.is_relative_to(allowed_root):
        return web.json_response({"error": "Access denied"}, status=403)
    if not resolved.exists() or not resolved.is_dir():
        return web.json_response(
            {"error": f"Directory not found: {search_path}", "files": [], "directories": []},
            status=400,
        )

    # List matching files and subdirectories
    files = []
    directories = []
    try:
        for entry in sorted(resolved.iterdir()):
            if entry.name.startswith("."):
                continue  # skip hidden files
            if entry.is_dir():
                directories.append({
                    "name": entry.name,
                    "path": str(entry),
                })
            elif entry.is_file():
                # Support comma-separated patterns (e.g., "*.sqlite,*.db")
                patterns = [p.strip() for p in pattern.split(",")]
                if any(fnmatch.fnmatch(entry.name.lower(), p.lower()) for p in patterns):
                    files.append({
                        "name": entry.name,
                        "path": str(entry),
                        "size_bytes": entry.stat().st_size,
                    })
    except PermissionError:
        return web.json_response(
            {"error": f"Permission denied: {search_path}", "files": [], "directories": []},
            status=403,
        )

    return web.json_response({
        "path": str(resolved),
        "files": files,
        "directories": directories,
    })


# ─── Kernel session endpoints ────────────────────────────────────────────────


async def create_session_handler(request: web.Request) -> web.Response:
    """POST /sessions — create a new kernel session."""
    if not _check_auth(request):
        return _auth_denied()
    try:
        body = await request.json()
    except Exception:
        body = {}

    session_token = body.get("session_token")
    gateway_url = body.get("gateway_url")
    session_id = body.get("session_id")

    try:
        session = await session_mgr.create_session(
            session_id=session_id,
            session_token=session_token,
            gateway_url=gateway_url,
        )
    except RuntimeError as e:
        return web.json_response({"error": str(e)}, status=429)

    return web.json_response({
        "session_id": session.id,
        "status": session.status,
        "created_at": session.created_at,
    }, status=201)


async def execute_session_handler(request: web.Request) -> web.Response:
    """POST /sessions/{session_id}/execute — execute a cell."""
    if not _check_auth(request):
        return _auth_denied()
    session_id = request.match_info["session_id"]
    session = session_mgr.get_session(session_id)
    if not session:
        return web.json_response({"error": "Session not found"}, status=404)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    code = body.get("code", "")
    if not code:
        return web.json_response({"error": "Missing required field: code"}, status=400)

    timeout = min(max(int(body.get("timeout", 30)), MIN_TIMEOUT), MAX_TIMEOUT)
    cell_id = body.get("cell_id")

    result = await session.execute(code, timeout=timeout, cell_id=cell_id)

    return web.json_response({
        "success": result.success,
        "output": result.output,
        "outputs": result.outputs or [],
        "error": result.error,
        "execution_ms": round(result.execution_ms, 2),
        "execution_count": result.execution_count,
        "cell_id": result.cell_id,
        "cell_count": session.cell_count,
        "session_status": session.status,
    })


async def get_session_handler(request: web.Request) -> web.Response:
    """GET /sessions/{session_id} — get session info."""
    if not _check_auth(request):
        return _auth_denied()
    session_id = request.match_info["session_id"]
    session = session_mgr.get_session(session_id)
    if not session:
        return web.json_response({"error": "Session not found"}, status=404)

    return web.json_response({
        "session_id": session.id,
        "status": session.status,
        "created_at": session.created_at,
        "last_active": session.last_active,
        "cell_count": session.cell_count,
    })


async def session_history_handler(request: web.Request) -> web.Response:
    """GET /sessions/{session_id}/history — cell execution history."""
    if not _check_auth(request):
        return _auth_denied()
    session_id = request.match_info["session_id"]
    session = session_mgr.get_session(session_id)
    if not session:
        return web.json_response({"error": "Session not found"}, status=404)

    cells = [
        {
            "success": c.success,
            "output": c.output,
            "outputs": c.outputs or [],
            "error": c.error,
            "execution_ms": round(c.execution_ms, 2),
            "execution_count": c.execution_count,
            "cell_id": c.cell_id,
        }
        for c in session.history
    ]
    return web.json_response({"session_id": session_id, "cells": cells})


async def delete_session_handler(request: web.Request) -> web.Response:
    """DELETE /sessions/{session_id} — terminate a session."""
    if not _check_auth(request):
        return _auth_denied()
    session_id = request.match_info["session_id"]
    deleted = await session_mgr.delete_session(session_id)
    if not deleted:
        return web.json_response({"error": "Session not found"}, status=404)
    return web.json_response({"status": "deleted"})


async def complete_session_handler(request: web.Request) -> web.Response:
    """POST /sessions/{session_id}/complete — tab completion."""
    if not _check_auth(request):
        return _auth_denied()
    session_id = request.match_info["session_id"]
    session = session_mgr.get_session(session_id)
    if not session:
        return web.json_response({"error": "Session not found"}, status=404)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    code = body.get("code", "")
    cursor_pos = body.get("cursor_pos", len(code))

    try:
        result = await session.complete(code, cursor_pos)
    except Exception:
        result = {"matches": [], "cursor_start": cursor_pos, "cursor_end": cursor_pos}

    return web.json_response(result)


async def inspect_session_handler(request: web.Request) -> web.Response:
    """POST /sessions/{session_id}/inspect — object inspection."""
    if not _check_auth(request):
        return _auth_denied()
    session_id = request.match_info["session_id"]
    session = session_mgr.get_session(session_id)
    if not session:
        return web.json_response({"error": "Session not found"}, status=404)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    code = body.get("code", "")
    cursor_pos = body.get("cursor_pos", len(code))
    detail_level = body.get("detail_level", 0)

    try:
        result = await session.inspect(code, cursor_pos, detail_level=detail_level)
    except Exception:
        result = {"found": False, "data": {}, "metadata": {}}

    return web.json_response(result)


async def interrupt_session_handler(request: web.Request) -> web.Response:
    """POST /sessions/{session_id}/interrupt — interrupt running cell."""
    if not _check_auth(request):
        return _auth_denied()
    session_id = request.match_info["session_id"]
    session = session_mgr.get_session(session_id)
    if not session:
        return web.json_response({"error": "Session not found"}, status=404)

    await session.interrupt()
    return web.json_response({"status": "ok"})


async def restart_session_handler(request: web.Request) -> web.Response:
    """POST /sessions/{session_id}/restart — restart a session."""
    if not _check_auth(request):
        return _auth_denied()
    session_id = request.match_info["session_id"]

    try:
        body = await request.json()
    except Exception:
        body = {}

    session = await session_mgr.restart_session(
        session_id=session_id,
        session_token=body.get("session_token"),
        gateway_url=body.get("gateway_url"),
    )

    return web.json_response({
        "session_id": session.id,
        "status": session.status,
    })


async def list_sessions_handler(request: web.Request) -> web.Response:
    """GET /sessions — list active kernel sessions."""
    if not _check_auth(request):
        return _auth_denied()
    sessions = session_mgr.list_sessions()
    return web.json_response({
        "sessions": [
            {
                "id": s.id,
                "status": s.status,
                "created_at": s.created_at,
                "last_active": s.last_active,
                "cell_count": s.cell_count,
            }
            for s in sessions
        ]
    })


async def on_startup(app: web.Application) -> None:
    """Start the session manager's idle reaper."""
    await session_mgr.start()


async def on_shutdown(app: web.Application) -> None:
    """Clean up all sandbox and session resources on shutdown."""
    logger.info("shutting down — cleaning up sandboxes and sessions")
    await executor.cleanup()
    await session_mgr.cleanup()


def create_app() -> web.Application:
    """Create the aiohttp application."""
    app = web.Application()
    # One-shot execution endpoints
    app.router.add_get("/health", health_handler)
    app.router.add_get("/vms", list_vms_handler)
    app.router.add_post("/execute", execute_handler)
    app.router.add_delete("/vm/{vm_id}", kill_vm_handler)
    app.router.add_get("/files", browse_files_handler)
    # Kernel session endpoints
    app.router.add_get("/sessions", list_sessions_handler)
    app.router.add_post("/sessions", create_session_handler)
    app.router.add_get("/sessions/{session_id}", get_session_handler)
    app.router.add_post("/sessions/{session_id}/execute", execute_session_handler)
    app.router.add_get("/sessions/{session_id}/history", session_history_handler)
    app.router.add_delete("/sessions/{session_id}", delete_session_handler)
    app.router.add_post("/sessions/{session_id}/restart", restart_session_handler)
    app.router.add_post("/sessions/{session_id}/complete", complete_session_handler)
    app.router.add_post("/sessions/{session_id}/inspect", inspect_session_handler)
    app.router.add_post("/sessions/{session_id}/interrupt", interrupt_session_handler)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    return app


if __name__ == "__main__":
    logger.info("starting sandbox manager on %s:%d (max_vms=%d)", HOST, PORT, MAX_VMS)
    app = create_app()
    web.run_app(app, host=HOST, port=PORT, print=None)
