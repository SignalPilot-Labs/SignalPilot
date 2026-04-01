"""
SignalPilot Sandbox Manager — unified HTTP API for code execution.

Auto-detects the best available backend:
  - /dev/kvm present → Firecracker microVMs (snapshot-accelerated, ~200ms)
  - No /dev/kvm      → gVisor sandbox (user-space kernel, ~50ms)

Both backends implement ExecutorBase, so the HTTP layer is identical
regardless of which backend is active.
"""

import asyncio
import logging
import os

from aiohttp import web

from executor_base import ExecutorBase

# ─── Configuration ───────────────────────────────────────────────────────────

MAX_VMS = int(os.getenv("SP_MAX_VMS", "10"))
VM_MEMORY_MB = int(os.getenv("SP_VM_MEMORY_MB", "512"))
VM_VCPUS = int(os.getenv("SP_VM_VCPUS", "1"))
VM_TIMEOUT_SEC = int(os.getenv("SP_VM_TIMEOUT_SEC", "300"))
LOG_LEVEL = os.getenv("SP_LOG_LEVEL", "info").upper()

logging.basicConfig(level=getattr(logging, LOG_LEVEL))
log = logging.getLogger("sandbox_manager")


# ─── Backend detection ───────────────────────────────────────────────────────

def _detect_executor() -> ExecutorBase:
    """Pick the best executor for this environment."""
    if os.path.exists("/dev/kvm"):
        from executor_firecracker import FirecrackerExecutor
        log.info("KVM detected — using Firecracker backend")
        return FirecrackerExecutor(MAX_VMS, VM_MEMORY_MB, VM_VCPUS, VM_TIMEOUT_SEC)

    from executor_gvisor import GVisorExecutor
    log.info("No KVM — using gVisor backend")
    return GVisorExecutor(MAX_VMS, VM_TIMEOUT_SEC)


# ─── HTTP handlers ───────────────────────────────────────────────────────────

async def handle_health(request: web.Request) -> web.Response:
    executor: ExecutorBase = request.app["executor"]
    status = executor.health()
    status["status"] = "healthy"
    return web.json_response(status)


async def handle_execute(request: web.Request) -> web.Response:
    executor: ExecutorBase = request.app["executor"]
    body = await request.json()

    code = body.get("code")
    if not code:
        return web.json_response({"error": "code is required"}, status=400)

    timeout = body.get("timeout", VM_TIMEOUT_SEC)

    try:
        result = await executor.execute(code, timeout=timeout)
        return web.json_response(result)
    except RuntimeError as e:
        return web.json_response({"error": str(e)}, status=503)
    except Exception as e:
        log.exception("execute error")
        return web.json_response({"error": str(e)}, status=500)


async def handle_kill(request: web.Request) -> web.Response:
    executor: ExecutorBase = request.app["executor"]
    vm_id = request.match_info["vm_id"]
    executor.cleanup_vm(vm_id)
    return web.json_response({"status": "killed", "vm_id": vm_id})


async def handle_status(request: web.Request) -> web.Response:
    executor: ExecutorBase = request.app["executor"]
    return web.json_response({"active_vms": executor.list_vms()})


# ─── App lifecycle ───────────────────────────────────────────────────────────

async def _cleanup_expired(app: web.Application) -> None:
    """Periodically kill VMs that exceed the timeout."""
    executor: ExecutorBase = app["executor"]
    while True:
        for vm in executor.list_vms():
            if vm["uptime_sec"] > VM_TIMEOUT_SEC:
                log.warning("VM %s expired, killing", vm["vm_id"])
                executor.cleanup_vm(vm["vm_id"])
        await asyncio.sleep(10)


async def on_startup(app: web.Application) -> None:
    executor = _detect_executor()
    await executor.start()
    app["executor"] = executor
    app["cleanup_task"] = asyncio.create_task(_cleanup_expired(app))


async def on_shutdown(app: web.Application) -> None:
    app["cleanup_task"].cancel()
    executor: ExecutorBase = app["executor"]
    for vm in executor.list_vms():
        executor.cleanup_vm(vm["vm_id"])


def main() -> None:
    app = web.Application()
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    app.router.add_get("/health", handle_health)
    app.router.add_post("/execute", handle_execute)
    app.router.add_delete("/vm/{vm_id}", handle_kill)
    app.router.add_get("/vms", handle_status)

    log.info("Sandbox manager starting on :8080")
    web.run_app(app, host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()
