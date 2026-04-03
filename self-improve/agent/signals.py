"""Signal queue and shared run state.

Provides instant control signal delivery (stop, pause, inject, unlock)
via an asyncio.Queue, plus the pulse checker for stuck subagent detection.
"""

import asyncio
import json as _json

from agent import db, hooks, session_gate


# =============================================================================
# Shared run state — accessed by both runner and endpoints
# =============================================================================
current_run_id: str | None = None
current_task: asyncio.Task | None = None


# =============================================================================
# Signal queue
# =============================================================================
_signal_queue: asyncio.Queue | None = None


def init_signal_queue() -> None:
    """Initialize the signal queue for a new run."""
    global _signal_queue
    _signal_queue = asyncio.Queue()
    print("[agent] Signal queue initialized")


def teardown_signal_queue() -> None:
    """Tear down the signal queue."""
    global _signal_queue
    _signal_queue = None


def push_signal(signal: str, payload: str | None = None) -> None:
    """Push a signal directly to the queue (used by HTTP endpoints)."""
    if _signal_queue:
        _signal_queue.put_nowait({"signal": signal, "payload": payload})


def has_pending_signals() -> bool:
    """Check if there are pending signals without consuming them."""
    if not _signal_queue:
        return False
    return not _signal_queue.empty()


async def drain_signal() -> dict | None:
    """Non-blocking check for a pending signal."""
    if not _signal_queue:
        return None
    try:
        return _signal_queue.get_nowait()
    except asyncio.QueueEmpty:
        return None


async def wait_for_signal(timeout: float = 2.0) -> dict | None:
    """Wait up to timeout seconds for a signal."""
    if not _signal_queue:
        return None
    try:
        return await asyncio.wait_for(_signal_queue.get(), timeout=timeout)
    except (asyncio.TimeoutError, asyncio.QueueEmpty):
        return None


MAX_PAUSE_MINUTES = 30  # Auto-resume after 30 minutes if no signal arrives


async def handle_pause(run_id: str) -> str | None:
    """Block until resume, inject, or stop signal arrives via the instant queue.
    Auto-resumes after MAX_PAUSE_MINUTES to prevent indefinite blocking."""
    import time as _time
    pause_start = _time.time()
    print("[agent] PAUSED — waiting for signal...")
    await db.update_run_status(run_id, "paused")
    await db.log_audit(run_id, "paused", {})

    while True:
        # Auto-resume if paused too long
        elapsed = _time.time() - pause_start
        if elapsed > MAX_PAUSE_MINUTES * 60:
            print(f"[agent] AUTO-RESUMED after {MAX_PAUSE_MINUTES}m pause timeout")
            await db.update_run_status(run_id, "running")
            await db.log_audit(run_id, "auto_resumed", {"pause_minutes": round(elapsed / 60, 1)})
            return "resume"

        signal = await wait_for_signal(timeout=5.0)
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


# =============================================================================
# Pulse checker — detects stuck subagents
# =============================================================================
_pulse_task: asyncio.Task | None = None


async def _subagent_pulse_checker(run_id: str) -> None:
    """Background task that checks for stuck subagents every 30s.
    When a subagent is idle > 10 min, pushes a stuck_recovery signal
    which the main loop handles by interrupting + continuing."""
    while True:
        await asyncio.sleep(30)
        try:
            stuck = hooks.get_stuck_subagents()
            if stuck:
                descriptions = ", ".join(
                    f"agent_id={s['agent_id']} (idle {s['idle_seconds']}s, total {s['total_seconds']}s)"
                    for s in stuck
                )
                print(f"[pulse] STUCK SUBAGENTS DETECTED: {descriptions}")
                await db.log_audit(run_id, "subagent_stuck", {
                    "stuck_agents": stuck,
                    "action": "interrupt_and_recover",
                })
                push_signal("stuck_recovery", _json.dumps(stuck))
                # Only fire once per detection — wait for recovery to clear things
                return
        except Exception as e:
            print(f"[pulse] Error in pulse checker: {e}")


def start_pulse_checker(run_id: str) -> None:
    global _pulse_task
    _pulse_task = asyncio.create_task(_subagent_pulse_checker(run_id))


def stop_pulse_checker() -> None:
    global _pulse_task
    if _pulse_task and not _pulse_task.done():
        _pulse_task.cancel()
    _pulse_task = None
