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

from fastapi import FastAPI
import uvicorn

from agent import db, endpoints


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_path = os.environ.get("DB_PATH", "/data/improve.db")
    await db.init_db(db_path)
    crashed = await db.mark_crashed_runs()
    if crashed:
        print(f"[agent] Marked {crashed} stale run(s) as crashed from previous restart")
    print("[agent] Ready — waiting for start command on :8500")
    yield
    await db.close_db()


app = FastAPI(title="Self-Improve Agent", lifespan=lifespan)
app.include_router(endpoints.router)


def main():
    uvicorn.run(app, host="0.0.0.0", port=8500, log_level="info")


if __name__ == "__main__":
    main()
