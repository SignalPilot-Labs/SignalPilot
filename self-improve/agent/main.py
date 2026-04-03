"""Self-improve agent orchestrator.

The agent container runs an HTTP server on port 8500 that waits for
start commands from the monitor UI. Each POST /start triggers a new
improvement run on a background task.

Control signals (stop, pause, inject, unlock) are delivered INSTANTLY
via an asyncio.Queue — no polling delay. The /kill endpoint cancels
the task immediately without waiting for the agent to wrap up.

Module layout:
  main.py      — FastAPI app, lifespan, entry point (this file)
  signals.py   — Signal queue, shared run state, pulse checker
  runner.py    — run_agent(), resume_agent(), shared loop
  endpoints.py — All HTTP route handlers (APIRouter)
  subagents.py — Subagent definitions for parallel work
  prompt.py    — Prompt loading and building
  hooks.py     — Tool call logging and subagent monitoring
  session_gate.py — Time-lock / end_session MCP tool
  permissions.py  — Tool permission gating
  git_ops.py   — Git workflow (clone, branch, push, PR)
  db.py        — SQLite audit database
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn

from agent import db, endpoints
from agent.run_manager import RunManager


class ParallelStartRequest(BaseModel):
    prompt: str | None = None
    max_budget_usd: float = 0
    duration_minutes: float = 0
    base_branch: str = "main"
    claude_token: str | None = None
    git_token: str | None = None
    github_repo: str | None = None


class ParallelSignalRequest(BaseModel):
    payload: str | None = None


_run_manager = RunManager()


def _is_worker() -> bool:
    """Check if this process is running inside a worker container (not the orchestrator)."""
    try:
        hostname = os.uname().nodename
        return hostname.startswith("improve-worker-") or os.environ.get("WORKER_MODE") == "1"
    except Exception:
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_path = os.environ.get("DB_PATH", "/data/improve.db")
    await db.init_db(db_path)
    # Only the orchestrator (main agent) should clean up — workers must not touch other containers or runs
    if not _is_worker():
        crashed = await db.mark_crashed_runs()
        if crashed:
            print(f"[agent] Marked {crashed} stale run(s) as crashed from previous restart")
        orphans = await _run_manager.cleanup_orphans()
        if orphans:
            print(f"[agent] Killed {orphans} orphan worker container(s)")
    print("[agent] Ready — waiting for start command on :8500")
    yield
    await db.close_db()


app = FastAPI(title="Self-Improve Agent", lifespan=lifespan)
app.include_router(endpoints.router)


# =============================================================================
# Parallel run endpoints — multiple concurrent agents in Docker containers
# =============================================================================

@app.get("/parallel/runs")
async def list_parallel_runs():
    """List all parallel run slots (active and finished)."""
    return [RunManager.to_dict(s) for s in _run_manager.get_all_slots()]


@app.post("/parallel/start")
async def start_parallel_run(body: ParallelStartRequest = ParallelStartRequest()):
    """Start a new parallel agent run in its own Docker container."""
    credentials = {}
    if body.claude_token:
        credentials["claude_token"] = body.claude_token
    if body.git_token:
        credentials["git_token"] = body.git_token
    if body.github_repo:
        credentials["github_repo"] = body.github_repo

    try:
        slot = await _run_manager.start_run(
            prompt=body.prompt,
            max_budget_usd=body.max_budget_usd,
            duration_minutes=body.duration_minutes,
            base_branch=body.base_branch,
            credentials=credentials,
        )
        return {
            "ok": True,
            **RunManager.to_dict(slot),
        }
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/parallel/runs/{run_id}")
async def get_parallel_run(run_id: str):
    """Get status of a specific parallel run by run_id."""
    slot = _run_manager.get_slot_by_run_id(run_id)
    if not slot:
        raise HTTPException(status_code=404, detail=f"Parallel run {run_id} not found")
    return RunManager.to_dict(slot)


@app.get("/parallel/runs/{run_id}/health")
async def parallel_run_health(run_id: str):
    """Get health of a specific parallel worker container."""
    slot = _run_manager.get_slot_by_run_id(run_id)
    if not slot:
        raise HTTPException(status_code=404, detail=f"Parallel run {run_id} not found")
    try:
        return await _run_manager.get_worker_health(slot.container_name)
    except Exception as e:
        return {"status": "unreachable", "error": str(e)}


@app.post("/parallel/runs/{run_id}/stop")
async def stop_parallel_run(run_id: str, body: ParallelSignalRequest = ParallelSignalRequest()):
    """Stop a specific parallel run."""
    slot = _run_manager.get_slot_by_run_id(run_id)
    if not slot:
        raise HTTPException(status_code=404, detail=f"Parallel run {run_id} not found")
    if slot.status not in ("starting", "running"):
        raise HTTPException(status_code=409, detail=f"Run status is '{slot.status}', cannot stop")
    reason = body.payload or "Operator stop via API"
    return await _run_manager.stop_run(slot.container_name, reason)


@app.post("/parallel/runs/{run_id}/kill")
async def kill_parallel_run(run_id: str):
    """Kill a specific parallel run immediately."""
    slot = _run_manager.get_slot_by_run_id(run_id)
    if not slot:
        raise HTTPException(status_code=404, detail=f"Parallel run {run_id} not found")
    return await _run_manager.kill_run(slot.container_name)


@app.post("/parallel/runs/{run_id}/pause")
async def pause_parallel_run(run_id: str):
    """Pause a specific parallel run."""
    slot = _run_manager.get_slot_by_run_id(run_id)
    if not slot:
        raise HTTPException(status_code=404, detail=f"Parallel run {run_id} not found")
    if slot.status != "running":
        raise HTTPException(status_code=409, detail=f"Run status is '{slot.status}', cannot pause")
    return await _run_manager.pause_run(slot.container_name)


@app.post("/parallel/runs/{run_id}/resume")
async def resume_parallel_run(run_id: str):
    """Resume a paused parallel run."""
    slot = _run_manager.get_slot_by_run_id(run_id)
    if not slot:
        raise HTTPException(status_code=404, detail=f"Parallel run {run_id} not found")
    return await _run_manager.resume_run(slot.container_name)


@app.post("/parallel/runs/{run_id}/inject")
async def inject_parallel_run(run_id: str, body: ParallelSignalRequest = ParallelSignalRequest()):
    """Inject a prompt into a parallel run."""
    slot = _run_manager.get_slot_by_run_id(run_id)
    if not slot:
        raise HTTPException(status_code=404, detail=f"Parallel run {run_id} not found")
    if not body.payload:
        raise HTTPException(status_code=400, detail="Payload is required")
    return await _run_manager.inject_prompt(slot.container_name, {"payload": body.payload})


@app.post("/parallel/runs/{run_id}/unlock")
async def unlock_parallel_run(run_id: str):
    """Unlock the session gate for a parallel run."""
    slot = _run_manager.get_slot_by_run_id(run_id)
    if not slot:
        raise HTTPException(status_code=404, detail=f"Parallel run {run_id} not found")
    return await _run_manager.unlock_run(slot.container_name)


@app.post("/parallel/cleanup")
async def cleanup_parallel_runs():
    """Clean up finished parallel run containers."""
    before = len([s for s in _run_manager.get_all_slots() if s.status not in ("starting", "running")])
    _run_manager.cleanup_all_finished()
    return {"ok": True, "cleaned": before}


@app.get("/parallel/status")
async def parallel_status():
    """Summary of parallel run system."""
    slots = _run_manager.get_all_slots()
    return {
        "total_slots": len(slots),
        "active": _run_manager.active_count(),
        "max_concurrent": 10,
        "slots": [RunManager.to_dict(s) for s in slots],
    }


def main():
    uvicorn.run(app, host="0.0.0.0", port=8500, log_level="info")


if __name__ == "__main__":
    main()
