"""HTTP endpoints for the self-improve agent.

All FastAPI route handlers are defined here as an APIRouter,
included by main.py into the FastAPI app.
"""

import asyncio
import os
import traceback

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from agent import db, git_ops, session_gate, signals, runner
from agent.key_pool import KeyPool
from agent.rate_limit import check_keys_rate_limit


router = APIRouter()


# =============================================================================
# Request models
# =============================================================================

class StartRequest(BaseModel):
    prompt: str | None = None
    max_budget_usd: float = 0
    duration_minutes: float = 0
    base_branch: str = "main"
    # Credentials passed by monitor (decrypted from settings DB)
    claude_token: str | None = None
    git_token: str | None = None
    github_repo: str | None = None


class ResumeRequest(BaseModel):
    run_id: str
    max_budget_usd: float = 0
    claude_token: str | None = None
    git_token: str | None = None
    github_repo: str | None = None


class InjectRequest(BaseModel):
    payload: str | None = None


# --- Key Pool Models ---

class AddKeyRequest(BaseModel):
    provider: str  # "claude_code" or "codex"
    key: str       # Raw API key/token (will be encrypted)
    label: str = ""
    priority: int = 0


class UpdateKeyRequest(BaseModel):
    label: str | None = None
    priority: int | None = None
    is_enabled: bool | None = None


class RotationConfigUpdate(BaseModel):
    codex_fallback_enabled: bool | None = None
    auto_wait_enabled: bool | None = None
    max_wait_minutes: int | None = None
    rotation_strategy: str | None = None
    prefer_model_downgrade_over_codex: bool | None = None


# =============================================================================
# Task lifecycle
# =============================================================================

def _on_task_done(task: asyncio.Task) -> None:
    """Callback when the agent task finishes or crashes."""
    try:
        exc = task.exception()
        if exc:
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            print(f"[agent] Run task crashed:\n{tb}", flush=True)
    except asyncio.CancelledError:
        pass  # Expected from /kill
    signals.current_run_id = None


# =============================================================================
# Routes
# =============================================================================

@router.get("/health")
async def health():
    return {
        "status": "idle" if signals.current_run_id is None else "running",
        "current_run_id": signals.current_run_id,
        "elapsed_minutes": round(session_gate.elapsed_minutes(), 1) if signals.current_run_id else None,
        "time_remaining": session_gate.time_remaining_str() if signals.current_run_id else None,
        "session_unlocked": session_gate.is_unlocked() if signals.current_run_id else None,
    }


@router.post("/start")
async def start_run(body: StartRequest = StartRequest()):
    if signals.current_run_id is not None:
        raise HTTPException(status_code=409, detail=f"Run already in progress: {signals.current_run_id}")

    # Inject credentials from monitor (takes priority over env vars)
    if body.claude_token:
        os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = body.claude_token
    if body.git_token:
        os.environ["GIT_TOKEN"] = body.git_token
    if body.github_repo:
        os.environ["GITHUB_REPO"] = body.github_repo

    budget = body.max_budget_usd if body.max_budget_usd is not None and body.max_budget_usd != 0 else float(os.environ.get("MAX_BUDGET_USD", "0"))
    signals.current_task = asyncio.create_task(
        runner.run_agent(
            custom_prompt=body.prompt,
            max_budget=budget,
            duration_minutes=body.duration_minutes,
            base_branch=body.base_branch,
        )
    )
    signals.current_task.add_done_callback(_on_task_done)
    await asyncio.sleep(2)
    return {
        "ok": True,
        "run_id": signals.current_run_id,
        "prompt": body.prompt if body.prompt else None,
        "max_budget_usd": budget,
        "duration_minutes": body.duration_minutes,
        "base_branch": body.base_branch,
    }


@router.post("/resume")
async def resume_run(body: ResumeRequest):
    if signals.current_run_id is not None:
        raise HTTPException(status_code=409, detail=f"Run already in progress: {signals.current_run_id}")

    # Inject credentials from monitor
    if body.claude_token:
        os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = body.claude_token
    if body.git_token:
        os.environ["GIT_TOKEN"] = body.git_token
    if body.github_repo:
        os.environ["GITHUB_REPO"] = body.github_repo

    budget = body.max_budget_usd or float(os.environ.get("MAX_BUDGET_USD", "0"))
    signals.current_task = asyncio.create_task(runner.resume_agent(body.run_id, budget))
    signals.current_task.add_done_callback(_on_task_done)
    await asyncio.sleep(2)
    return {"ok": True, "run_id": body.run_id, "resumed": True}


@router.post("/pause")
async def pause_agent():
    """Push pause signal to the in-process queue."""
    if signals.current_run_id is None:
        raise HTTPException(status_code=409, detail="No run in progress")
    signals.push_signal("pause")
    return {"ok": True, "signal": "pause", "delivery": "instant"}


@router.post("/resume_signal")
async def resume_agent_signal():
    """Push resume signal to the in-process queue."""
    if signals.current_run_id is None:
        raise HTTPException(status_code=409, detail="No run in progress")
    signals.push_signal("resume")
    return {"ok": True, "signal": "resume", "delivery": "instant"}


@router.post("/inject")
async def inject_agent(body: InjectRequest = InjectRequest()):
    """Push inject signal with payload to the in-process queue."""
    if signals.current_run_id is None:
        raise HTTPException(status_code=409, detail="No run in progress")
    signals.push_signal("inject", body.payload)
    return {"ok": True, "signal": "inject", "delivery": "instant"}


@router.post("/unlock")
async def unlock_agent():
    """Push unlock signal to the in-process queue."""
    if signals.current_run_id is None:
        raise HTTPException(status_code=409, detail="No run in progress")
    signals.push_signal("unlock")
    return {"ok": True, "signal": "unlock", "delivery": "instant"}


@router.post("/stop")
async def stop_run_instant():
    """Push stop signal directly to the in-process queue. Instant delivery."""
    if signals.current_run_id is None:
        raise HTTPException(status_code=409, detail="No run in progress")
    signals.push_signal("stop", "Operator stop via API")
    return {"ok": True, "signal": "stop", "delivery": "instant"}


@router.post("/kill")
async def kill_run():
    """Immediately cancel the running task. No cleanup, no PR."""
    if signals.current_task is None or signals.current_run_id is None:
        raise HTTPException(status_code=409, detail="No run in progress")

    run_id = signals.current_run_id
    signals.current_task.cancel()
    # Give it a moment to process the cancellation
    await asyncio.sleep(0.5)
    # Force update DB in case the task didn't get to clean up
    try:
        await db.finish_run(run_id=run_id, status="killed")
    except Exception as e:
        print(f"[agent] Failed to update killed run status: {e}")
    signals.current_run_id = None
    return {"ok": True, "signal": "kill", "run_id": run_id}


@router.get("/branches")
async def list_branches():
    try:
        git_ops.setup_git_auth()
        output = git_ops._run_git(["branch", "-r", "--format", "%(refname:short)"])
        branches = [b.replace("origin/", "") for b in output.strip().split("\n") if b.strip() and "HEAD" not in b]
        return sorted(set(branches))
    except Exception as e:
        print(f"[agent] Failed to list branches: {e}")
        return ["main"]


@router.get("/diff/live")
async def get_live_diff():
    """Get diff stats for the currently running branch (including uncommitted)."""
    try:
        git_ops.setup_git_auth()
        base = "main"
        if signals.current_run_id:
            conn = db.get_db()
            cursor = await conn.execute("SELECT base_branch FROM runs WHERE id = ?", (signals.current_run_id,))
            row = await cursor.fetchone()
            if row and row["base_branch"]:
                base = row["base_branch"]
        stats = git_ops.get_branch_diff_live(base)
        return {"files": stats, "total_files": len(stats),
                "total_added": sum(f["added"] for f in stats),
                "total_removed": sum(f["removed"] for f in stats)}
    except Exception as e:
        print(f"[agent] /diff/live error: {e}")
        return {"files": [], "error": "Failed to compute diff"}


@router.get("/diff/{branch}")
async def get_branch_diff(branch: str, base: str = "main"):
    """Get diff stats between a branch and its base."""
    try:
        git_ops.setup_git_auth()
        stats = git_ops.get_branch_diff(branch, base)
        return {"files": stats, "total_files": len(stats),
                "total_added": sum(f["added"] for f in stats),
                "total_removed": sum(f["removed"] for f in stats)}
    except Exception as e:
        print(f"[agent] /diff/{branch} error: {e}")
        return {"files": [], "error": "Failed to compute diff"}


# =============================================================================
# Key Pool Management
# =============================================================================

@router.post("/keys", status_code=201, dependencies=[Depends(check_keys_rate_limit)])
async def add_key(req: AddKeyRequest):
    """Add a new API key to the pool."""
    pool = KeyPool()
    try:
        key = await pool.add_key(
            provider=req.provider,
            raw_key=req.key,
            label=req.label,
            priority=req.priority,
        )
        keys = await pool.list_keys()
        # Find the newly added key in the masked list
        added = next((k for k in keys if k["id"] == key.id), {})
        return added
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/keys", dependencies=[Depends(check_keys_rate_limit)])
async def list_keys():
    """List all keys (masked values, never raw)."""
    pool = KeyPool()
    return await pool.list_keys()


@router.get("/keys/status", dependencies=[Depends(check_keys_rate_limit)])
async def key_pool_status():
    """Current pool status: active key, rate limit states, next reset ETA."""
    pool = KeyPool()
    return await pool.get_pool_status()


@router.get("/keys/config", dependencies=[Depends(check_keys_rate_limit)])
async def get_rotation_config():
    """Get current rotation configuration."""
    pool = KeyPool()
    return await pool.get_config()


@router.patch("/keys/config", dependencies=[Depends(check_keys_rate_limit)])
async def update_rotation_config(req: RotationConfigUpdate):
    """Update rotation configuration."""
    pool = KeyPool()
    updates = {}
    if req.codex_fallback_enabled is not None:
        updates["codex_fallback_enabled"] = str(req.codex_fallback_enabled).lower()
    if req.auto_wait_enabled is not None:
        updates["auto_wait_enabled"] = str(req.auto_wait_enabled).lower()
    if req.max_wait_minutes is not None:
        updates["max_wait_minutes"] = str(req.max_wait_minutes)
    if req.rotation_strategy is not None:
        updates["rotation_strategy"] = req.rotation_strategy
    if req.prefer_model_downgrade_over_codex is not None:
        updates["prefer_model_downgrade_over_codex"] = str(req.prefer_model_downgrade_over_codex).lower()
    try:
        return await pool.update_config(updates)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.patch("/keys/{key_id}", dependencies=[Depends(check_keys_rate_limit)])
async def update_key(key_id: str, req: UpdateKeyRequest):
    """Update key metadata (label, priority, enabled)."""
    pool = KeyPool()
    try:
        key = await pool.update_key(
            key_id=key_id,
            label=req.label,
            priority=req.priority,
            is_enabled=req.is_enabled,
        )
        # Return masked version
        keys = await pool.list_keys()
        updated = next((k for k in keys if k["id"] == key.id), {})
        return updated
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/keys/{key_id}", dependencies=[Depends(check_keys_rate_limit)])
async def delete_key(key_id: str):
    """Remove a key from the pool."""
    pool = KeyPool()
    try:
        await pool.delete_key(key_id)
        return {"ok": True, "deleted": key_id}
    except ValueError as e:
        if "last enabled" in str(e):
            raise HTTPException(status_code=409, detail=str(e))
        raise HTTPException(status_code=404, detail=str(e))
