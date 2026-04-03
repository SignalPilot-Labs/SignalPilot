"""HTTP endpoints for the self-improve agent.

All FastAPI route handlers are defined here as an APIRouter,
included by main.py into the FastAPI app.
"""

import asyncio
import hmac
import logging
import os
import traceback

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from agent import db, git_ops, session_gate, signals, runner


logger = logging.getLogger(__name__)

_API_KEY = os.environ.get("SP_API_KEY", "")


async def verify_api_key(x_api_key: str = Header(default="")) -> None:
    """Verify API key if SP_API_KEY is configured."""
    if not _API_KEY:
        return
    if not x_api_key or not hmac.compare_digest(x_api_key, _API_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


router = APIRouter()


# =============================================================================
# Request models
# =============================================================================

class StartRequest(BaseModel):
    prompt: str | None = Field(default=None, max_length=50000)
    max_budget_usd: float = 0
    duration_minutes: float = 0
    base_branch: str = Field(default="main", max_length=200)
    # Credentials passed by monitor (decrypted from settings DB)
    claude_token: str | None = Field(default=None, max_length=500)
    git_token: str | None = Field(default=None, max_length=500)
    github_repo: str | None = Field(default=None, max_length=200)


class ResumeRequest(BaseModel):
    run_id: str = Field(max_length=100)
    max_budget_usd: float = 0
    claude_token: str | None = Field(default=None, max_length=500)
    git_token: str | None = Field(default=None, max_length=500)
    github_repo: str | None = Field(default=None, max_length=200)


class InjectRequest(BaseModel):
    payload: str | None = Field(default=None, max_length=50000)


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


@router.post("/start", dependencies=[Depends(verify_api_key)])
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


@router.post("/resume", dependencies=[Depends(verify_api_key)])
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


@router.post("/pause", dependencies=[Depends(verify_api_key)])
async def pause_agent():
    """Push pause signal to the in-process queue."""
    if signals.current_run_id is None:
        raise HTTPException(status_code=409, detail="No run in progress")
    signals.push_signal("pause")
    return {"ok": True, "signal": "pause", "delivery": "instant"}


@router.post("/resume_signal", dependencies=[Depends(verify_api_key)])
async def resume_agent_signal():
    """Push resume signal to the in-process queue."""
    if signals.current_run_id is None:
        raise HTTPException(status_code=409, detail="No run in progress")
    signals.push_signal("resume")
    return {"ok": True, "signal": "resume", "delivery": "instant"}


@router.post("/inject", dependencies=[Depends(verify_api_key)])
async def inject_agent(body: InjectRequest = InjectRequest()):
    """Push inject signal with payload to the in-process queue."""
    if signals.current_run_id is None:
        raise HTTPException(status_code=409, detail="No run in progress")
    signals.push_signal("inject", body.payload)
    return {"ok": True, "signal": "inject", "delivery": "instant"}


@router.post("/unlock", dependencies=[Depends(verify_api_key)])
async def unlock_agent():
    """Push unlock signal to the in-process queue."""
    if signals.current_run_id is None:
        raise HTTPException(status_code=409, detail="No run in progress")
    signals.push_signal("unlock")
    return {"ok": True, "signal": "unlock", "delivery": "instant"}


@router.post("/stop", dependencies=[Depends(verify_api_key)])
async def stop_run_instant():
    """Push stop signal directly to the in-process queue. Instant delivery."""
    if signals.current_run_id is None:
        raise HTTPException(status_code=409, detail="No run in progress")
    signals.push_signal("stop", "Operator stop via API")
    return {"ok": True, "signal": "stop", "delivery": "instant"}


@router.post("/kill", dependencies=[Depends(verify_api_key)])
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


@router.get("/branches", dependencies=[Depends(verify_api_key)])
async def list_branches():
    try:
        git_ops.setup_git_auth()
        output = git_ops._run_git(["branch", "-r", "--format", "%(refname:short)"])
        branches = [b.replace("origin/", "") for b in output.strip().split("\n") if b.strip() and "HEAD" not in b]
        return sorted(set(branches))
    except Exception as e:
        print(f"[agent] Failed to list branches: {e}")
        return ["main"]


@router.get("/diff/live", dependencies=[Depends(verify_api_key)])
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


@router.get("/diff/{branch}", dependencies=[Depends(verify_api_key)])
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
