"""Signal queue for instant control signal delivery.

HTTP endpoints push signals (pause, resume, inject, stop, unlock) into an
asyncio.Queue. The agent's run loop drains the queue between rounds for
instant response — no polling delay.
"""

import asyncio

from agent import db, session_gate


_signal_queue: asyncio.Queue | None = None


def init() -> None:
    """Initialize the signal queue for a new run."""
    global _signal_queue
    _signal_queue = asyncio.Queue()
    print("[agent] Signal queue initialized")


def teardown() -> None:
    """Tear down the signal queue."""
    global _signal_queue
    _signal_queue = None


def push(signal: str, payload: str | None = None) -> None:
    """Push a signal directly to the queue (used by HTTP endpoints)."""
    if _signal_queue:
        _signal_queue.put_nowait({"signal": signal, "payload": payload})


async def drain() -> dict | None:
    """Non-blocking check for a pending signal."""
    if not _signal_queue:
        return None
    try:
        return _signal_queue.get_nowait()
    except asyncio.QueueEmpty:
        return None


async def wait(timeout: float = 2.0) -> dict | None:
    """Wait up to timeout seconds for a signal."""
    if not _signal_queue:
        return None
    try:
        return await asyncio.wait_for(_signal_queue.get(), timeout=timeout)
    except (asyncio.TimeoutError, asyncio.QueueEmpty):
        return None


async def handle_pause(run_id: str) -> str | None:
    """Block until resume, inject, or stop signal arrives via the instant queue."""
    print("[agent] PAUSED — waiting for signal...")
    await db.update_run_status(run_id, "paused")
    await db.log_audit(run_id, "paused", {})

    while True:
        signal = await wait(timeout=5.0)
        if signal:
            sig = signal["signal"]
            if sig == "resume":
                print("[agent] RESUMED")
                await db.update_run_status(run_id, "running")
                return "resume"
            elif sig == "inject":
                payload = signal.get("payload", "")
                print(f"[agent] INJECTED: {payload[:100]}...")
                await db.update_run_status(run_id, "running")
                await db.log_audit(run_id, "prompt_injected", {"prompt": payload})
                return f"inject:{payload}"
            elif sig == "stop":
                print("[agent] STOP received while paused")
                await db.log_audit(run_id, "stop_requested", {"reason": signal.get("payload", "")})
                return "stop"
            elif sig == "unlock":
                session_gate.force_unlock()
                await db.update_run_status(run_id, "running")
                await db.log_audit(run_id, "session_unlocked", {})
                return "resume"
