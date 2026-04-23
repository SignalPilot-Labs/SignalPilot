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
import logging
import uuid
from pathlib import Path

from aiohttp import web

import audit
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
        {"vm_id": vm_id, "session_token": token[:8] + "..."}
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


async def browse_files_handler(request: web.Request) -> web.Response:
    """GET /files — browse host filesystem for local DB files.

    Query params:
        path: directory to list (default: user home)
        pattern: glob pattern (default: *.duckdb)
    """
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
                if fnmatch.fnmatch(entry.name.lower(), pattern.lower()):
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


def create_app() -> web.Application:
    """Create the aiohttp application."""
    app = web.Application()
    app.router.add_get("/health", health_handler)
    app.router.add_get("/vms", list_vms_handler)
    app.router.add_post("/execute", execute_handler)
    app.router.add_delete("/vm/{vm_id}", kill_vm_handler)
    app.router.add_get("/files", browse_files_handler)
    app.on_shutdown.append(on_shutdown)
    return app


if __name__ == "__main__":
    logger.info("starting sandbox manager on %s:%d (max_vms=%d)", HOST, PORT, MAX_VMS)
    app = create_app()
    web.run_app(app, host=HOST, port=PORT, print=None)
