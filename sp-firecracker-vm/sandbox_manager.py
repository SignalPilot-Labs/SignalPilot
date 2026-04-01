"""
SignalPilot Sandbox Manager — Shuru microVM execution

Performance model:
  Cold run:    ~800ms  (VM boot + Python startup + exec)
  Checkpoint:  ~200ms  (restore from checkpoint + exec)

At startup, we optionally create a Shuru checkpoint with Python and common
modules pre-loaded. Each execution restores from the checkpoint, pipes code
to python3 via stdin, and returns the result.

Communication: subprocess stdin/stdout. Code is piped to `shuru run ... -- python3 -`,
which reads from stdin, executes, and writes output to stdout/stderr.
"""

import asyncio
import json
import logging
import os
import shutil
import tempfile
import time
import uuid

from aiohttp import web

# ─── Configuration ───────────────────────────────────────────────────────────

GATEWAY_URL = os.getenv("SP_GATEWAY_URL", "http://localhost:3300")
MAX_SANDBOXES = int(os.getenv("SP_MAX_SANDBOXES", "10"))
SANDBOX_MEMORY_MB = int(os.getenv("SP_SANDBOX_MEMORY_MB", "512"))
SANDBOX_CPUS = int(os.getenv("SP_SANDBOX_CPUS", "1"))
SANDBOX_TIMEOUT_SEC = int(os.getenv("SP_SANDBOX_TIMEOUT_SEC", "300"))
LOG_LEVEL = os.getenv("SP_LOG_LEVEL", "info").upper()
SHURU_BIN = os.getenv("SP_SHURU_BIN", "shuru")
CHECKPOINT_NAME = os.getenv("SP_CHECKPOINT_NAME", "sp-python")

logging.basicConfig(level=getattr(logging, LOG_LEVEL))
log = logging.getLogger("sandbox_manager")

active_sandboxes: dict[str, dict] = {}

# Checkpoint state
checkpoint_ready = False


# ─── Shuru helpers ──────────────────────────────────────────────────────────

async def shuru_available() -> bool:
    """Check if the shuru binary is installed and functional."""
    try:
        proc = await asyncio.create_subprocess_exec(
            SHURU_BIN, "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        return proc.returncode == 0
    except Exception:
        return False


async def checkpoint_exists(name: str) -> bool:
    """Check if a Shuru checkpoint exists."""
    try:
        proc = await asyncio.create_subprocess_exec(
            SHURU_BIN, "checkpoint", "list",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        return name in stdout.decode("utf-8", errors="replace")
    except Exception:
        return False


# ─── Checkpoint creation (runs once at startup) ────────────────────────────

BASE_CHECKPOINT = "sp-base"  # checkpoint with Python installed


async def _run_shuru_checkpoint(name: str, args: list[str], timeout: int = 120) -> bool:
    """Run a shuru checkpoint create command. Returns True on success."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    if proc.returncode != 0:
        combined = (stdout + stderr).decode("utf-8", errors="replace").strip()
        log.error(f"Checkpoint '{name}' failed (exit {proc.returncode}): {combined}")
        return False
    return True


async def create_checkpoint():
    """Create Shuru checkpoints: base (with Python installed) + app (with modules pre-loaded)."""
    global checkpoint_ready

    if await checkpoint_exists(CHECKPOINT_NAME):
        log.info(f"Existing checkpoint '{CHECKPOINT_NAME}' found, reusing")
        checkpoint_ready = True
        return

    # Step 1: Create base checkpoint with Python installed (if not exists)
    if not await checkpoint_exists(BASE_CHECKPOINT):
        log.info(f"Creating base checkpoint '{BASE_CHECKPOINT}' (installing Python)...")
        start = time.monotonic()
        ok = await _run_shuru_checkpoint(BASE_CHECKPOINT, [
            SHURU_BIN, "checkpoint", "create", BASE_CHECKPOINT,
            "--allow-net",
            "--cpus", str(SANDBOX_CPUS),
            "--memory", str(SANDBOX_MEMORY_MB),
            "--", "sh", "-c",
            "apt-get update -qq && apt-get install -y -qq python3 > /dev/null 2>&1 && python3 --version",
        ], timeout=180)
        elapsed_ms = (time.monotonic() - start) * 1000
        if ok:
            log.info(f"Base checkpoint created in {elapsed_ms:.0f}ms")
        else:
            log.error("Failed to create base checkpoint — running without checkpoints")
            return
    else:
        log.info(f"Base checkpoint '{BASE_CHECKPOINT}' exists")

    # Step 2: Create app checkpoint from base with Python modules pre-loaded
    log.info(f"Creating app checkpoint '{CHECKPOINT_NAME}' from '{BASE_CHECKPOINT}'...")
    start = time.monotonic()
    ok = await _run_shuru_checkpoint(CHECKPOINT_NAME, [
        SHURU_BIN, "checkpoint", "create", CHECKPOINT_NAME,
        "--from", BASE_CHECKPOINT,
        "--cpus", str(SANDBOX_CPUS),
        "--memory", str(SANDBOX_MEMORY_MB),
        "--", "python3", "-c",
        "import collections, datetime, functools, hashlib, "
        "itertools, math, random, re, string, time; "
        "print('SP checkpoint ready')",
    ], timeout=60)
    elapsed_ms = (time.monotonic() - start) * 1000

    if ok:
        checkpoint_ready = True
        log.info(f"App checkpoint '{CHECKPOINT_NAME}' created in {elapsed_ms:.0f}ms")
    else:
        log.error("Failed to create app checkpoint — running without checkpoints")


# ─── Execution ──────────────────────────────────────────────────────────────

def cleanup_sandbox(sandbox_id: str):
    sb = active_sandboxes.pop(sandbox_id, None)
    if sb is None:
        return
    proc = sb.get("process")
    if proc and proc.returncode is None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
    tmp_dir = sb.get("tmp_dir")
    if tmp_dir and os.path.exists(tmp_dir):
        shutil.rmtree(tmp_dir, ignore_errors=True)
    log.info(f"Sandbox {sandbox_id} cleaned up")


async def execute_code(code: str, timeout: int = 30) -> dict:
    """Execute Python code in a Shuru microVM sandbox."""
    if len(active_sandboxes) >= MAX_SANDBOXES:
        raise RuntimeError(f"Max concurrent sandboxes ({MAX_SANDBOXES}) reached")

    sandbox_id = str(uuid.uuid4())[:8]
    start_time = time.monotonic()

    # Write code to a temp dir inside CWD (Shuru only mounts paths within CWD)
    sandbox_tmp = os.path.join(os.getcwd(), ".sandbox-tmp")
    os.makedirs(sandbox_tmp, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix=f"sp_{sandbox_id}_", dir=sandbox_tmp)
    code_file = os.path.join(tmp_dir, "code.py")
    with open(code_file, "w") as f:
        f.write(code)

    # Build shuru command
    cmd = [SHURU_BIN, "run"]
    if checkpoint_ready:
        cmd.extend(["--from", CHECKPOINT_NAME])
    cmd.extend([
        "--cpus", str(SANDBOX_CPUS),
        "--memory", str(SANDBOX_MEMORY_MB),
        "--mount", f"{tmp_dir}:/sandbox:ro",
        "--", "python3", "/sandbox/code.py",
    ])

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        active_sandboxes[sandbox_id] = {
            "process": proc,
            "tmp_dir": tmp_dir,
            "started_at": time.time(),
        }

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            elapsed_ms = (time.monotonic() - start_time) * 1000
            return {
                "success": False,
                "output": "",
                "error": f"Execution timed out after {timeout}s",
                "exit_code": -1,
                "vm_id": sandbox_id,
                "execution_ms": elapsed_ms,
            }

        elapsed_ms = (time.monotonic() - start_time) * 1000
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        return {
            "success": proc.returncode == 0,
            "output": stdout.rstrip(),
            "error": stderr.rstrip() or None,
            "exit_code": proc.returncode,
            "vm_id": sandbox_id,
            "execution_ms": elapsed_ms,
        }

    finally:
        cleanup_sandbox(sandbox_id)


# ─── HTTP API ────────────────────────────────────────────────────────────────

async def handle_health(request):
    available = await shuru_available()
    return web.json_response({
        "status": "healthy" if available else "degraded",
        "shuru_available": available,
        "active_sandboxes": len(active_sandboxes),
        "max_sandboxes": MAX_SANDBOXES,
        "checkpoint_ready": checkpoint_ready,
    })


async def handle_execute(request):
    body = await request.json()
    code = body.get("code")
    if not code:
        return web.json_response({"error": "code is required"}, status=400)

    timeout = body.get("timeout", SANDBOX_TIMEOUT_SEC)

    try:
        result = await execute_code(code, timeout=timeout)
        return web.json_response(result)
    except RuntimeError as e:
        return web.json_response({"error": str(e)}, status=503)
    except Exception as e:
        log.exception("execute error")
        return web.json_response({"error": str(e)}, status=500)


async def handle_kill(request):
    sandbox_id = request.match_info["vm_id"]
    cleanup_sandbox(sandbox_id)
    return web.json_response({"status": "killed", "vm_id": sandbox_id})


async def handle_status(request):
    sbs = [
        {"vm_id": k, "uptime_sec": time.time() - v["started_at"]}
        for k, v in active_sandboxes.items()
    ]
    return web.json_response({"active_vms": sbs})


async def cleanup_expired_sandboxes():
    while True:
        now = time.time()
        expired = [
            k for k, v in active_sandboxes.items()
            if now - v["started_at"] > SANDBOX_TIMEOUT_SEC
        ]
        for sandbox_id in expired:
            log.warning(f"Sandbox {sandbox_id} expired, killing")
            cleanup_sandbox(sandbox_id)
        await asyncio.sleep(10)


async def on_startup(app):
    # Create checkpoint at startup
    try:
        await create_checkpoint()
    except Exception:
        log.exception("Checkpoint creation failed — running without checkpoint")

    app["cleanup_task"] = asyncio.create_task(cleanup_expired_sandboxes())


async def on_shutdown(app):
    app["cleanup_task"].cancel()
    for sandbox_id in list(active_sandboxes.keys()):
        cleanup_sandbox(sandbox_id)


def main():
    app = web.Application()
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    app.router.add_get("/health", handle_health)
    app.router.add_post("/execute", handle_execute)
    app.router.add_delete("/vm/{vm_id}", handle_kill)
    app.router.add_get("/vms", handle_status)

    log.info(
        f"Sandbox manager starting on :8080 "
        f"(max {MAX_SANDBOXES} sandboxes, shuru backend)"
    )
    web.run_app(app, host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()
