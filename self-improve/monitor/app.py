"""FastAPI monitoring app with SSE for real-time tool call streaming.

Provides:
- Real-time event feed via SSE (pg LISTEN/NOTIFY)
- Run history and detail APIs
- Control signals: pause, resume, inject prompt, stop
"""

import asyncio
import json
import os
import uuid as uuid_mod
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

AUDIT_DB_URL = os.environ.get(
    "AUDIT_DB_URL",
    "postgresql://improve_admin:Impr0ve!Aud1t@localhost:5610/improve_audit",
)

pool: asyncpg.Pool | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    pool = await asyncpg.create_pool(AUDIT_DB_URL, min_size=2, max_size=10)
    yield
    if pool:
        await pool.close()


app = FastAPI(title="SignalPilot Self-Improve Monitor API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Run APIs ---

@app.get("/api/runs")
async def list_runs():
    rows = await pool.fetch(
        "SELECT * FROM runs ORDER BY started_at DESC LIMIT 50"
    )
    return [dict(r) for r in rows]


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    row = await pool.fetchrow("SELECT * FROM runs WHERE id = $1", run_id)
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    return dict(row)


@app.get("/api/runs/{run_id}/tools")
async def get_tool_calls(
    run_id: str,
    limit: int = Query(default=200, le=1000),
    offset: int = Query(default=0, ge=0),
):
    rows = await pool.fetch(
        """SELECT * FROM tool_calls
        WHERE run_id = $1
        ORDER BY ts DESC
        LIMIT $2 OFFSET $3""",
        run_id,
        limit,
        offset,
    )
    return [dict(r) for r in rows]


@app.get("/api/runs/{run_id}/audit")
async def get_audit_log(
    run_id: str,
    limit: int = Query(default=200, le=1000),
    offset: int = Query(default=0, ge=0),
):
    rows = await pool.fetch(
        """SELECT * FROM audit_log
        WHERE run_id = $1
        ORDER BY ts DESC
        LIMIT $2 OFFSET $3""",
        run_id,
        limit,
        offset,
    )
    return [dict(r) for r in rows]


# --- Control Signal APIs ---

class ControlSignalRequest(BaseModel):
    payload: str | None = None


@app.post("/api/runs/{run_id}/pause")
async def pause_run(run_id: str):
    """Send a pause signal to the running agent."""
    run = await pool.fetchrow("SELECT status FROM runs WHERE id = $1", run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run["status"] not in ("running",):
        raise HTTPException(status_code=409, detail=f"Cannot pause run with status '{run['status']}'")

    await pool.execute(
        "INSERT INTO control_signals (run_id, signal) VALUES ($1, 'pause')",
        uuid_mod.UUID(run_id),
    )
    return {"ok": True, "signal": "pause"}


@app.post("/api/runs/{run_id}/resume")
async def resume_run(run_id: str):
    """Send a resume signal to a paused agent."""
    run = await pool.fetchrow("SELECT status FROM runs WHERE id = $1", run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run["status"] not in ("paused",):
        raise HTTPException(status_code=409, detail=f"Cannot resume run with status '{run['status']}'")

    await pool.execute(
        "INSERT INTO control_signals (run_id, signal) VALUES ($1, 'resume')",
        uuid_mod.UUID(run_id),
    )
    return {"ok": True, "signal": "resume"}


@app.post("/api/runs/{run_id}/inject")
async def inject_prompt(run_id: str, body: ControlSignalRequest):
    """Inject a custom prompt into the running agent."""
    if not body.payload or not body.payload.strip():
        raise HTTPException(status_code=400, detail="Payload (prompt text) is required")

    run = await pool.fetchrow("SELECT status FROM runs WHERE id = $1", run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run["status"] not in ("running", "paused"):
        raise HTTPException(status_code=409, detail=f"Cannot inject into run with status '{run['status']}'")

    await pool.execute(
        "INSERT INTO control_signals (run_id, signal, payload) VALUES ($1, 'inject', $2)",
        uuid_mod.UUID(run_id),
        body.payload.strip(),
    )
    return {"ok": True, "signal": "inject", "prompt_length": len(body.payload.strip())}


@app.post("/api/runs/{run_id}/stop")
async def stop_run(run_id: str, body: ControlSignalRequest = ControlSignalRequest()):
    """Send a graceful stop signal. Agent will commit progress and create PR."""
    run = await pool.fetchrow("SELECT status FROM runs WHERE id = $1", run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run["status"] not in ("running", "paused", "rate_limited"):
        raise HTTPException(status_code=409, detail=f"Cannot stop run with status '{run['status']}'")

    reason = (body.payload or "").strip() or "Operator requested stop"
    await pool.execute(
        "INSERT INTO control_signals (run_id, signal, payload) VALUES ($1, 'stop', $2)",
        uuid_mod.UUID(run_id),
        reason,
    )
    return {"ok": True, "signal": "stop", "reason": reason}


@app.post("/api/runs/{run_id}/unlock")
async def unlock_run(run_id: str):
    """Unlock the session gate early, allowing end_session to succeed."""
    run = await pool.fetchrow("SELECT status FROM runs WHERE id = $1", run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run["status"] not in ("running", "paused", "rate_limited"):
        raise HTTPException(status_code=409, detail=f"Cannot unlock run with status '{run['status']}'")

    await pool.execute(
        "INSERT INTO control_signals (run_id, signal) VALUES ($1, 'unlock')",
        uuid_mod.UUID(run_id),
    )
    return {"ok": True, "signal": "unlock"}


# --- Agent start / health (proxied to agent container :8500) ---

import httpx

AGENT_API_URL = os.environ.get("AGENT_API_URL", "http://agent:8500")


class StartRunRequest(BaseModel):
    prompt: str | None = None
    max_budget_usd: float = 50.0
    duration_minutes: float = 0
    base_branch: str = "main"


@app.get("/api/agent/health")
async def agent_health():
    """Check if the agent container is alive and whether a run is in progress."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            res = await client.get(f"{AGENT_API_URL}/health")
            return res.json()
    except Exception as e:
        return {"status": "unreachable", "error": str(e)}


@app.post("/api/agent/start")
async def start_agent_run(body: StartRunRequest = StartRunRequest()):
    """Trigger a new improvement run on the agent container."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.post(
                f"{AGENT_API_URL}/start",
                json={
                    "prompt": body.prompt,
                    "max_budget_usd": body.max_budget_usd,
                    "duration_minutes": body.duration_minutes,
                    "base_branch": body.base_branch,
                },
            )
            if res.status_code == 409:
                raise HTTPException(status_code=409, detail=res.json().get("detail", "Run in progress"))
            return res.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Agent unreachable: {e}")


@app.get("/api/agent/branches")
async def list_branches():
    """Get all remote branches from the agent's clone."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(f"{AGENT_API_URL}/branches")
            if res.status_code == 200:
                return res.json()
    except Exception:
        pass
    return ["main", "staging"]


@app.post("/api/agent/stop")
async def stop_agent_instant():
    """Instant stop — pushes directly to the agent's in-process queue."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            res = await client.post(f"{AGENT_API_URL}/stop")
            return res.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Agent unreachable: {e}")


@app.post("/api/agent/kill")
async def kill_agent():
    """Immediately kill the running task. No cleanup."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            res = await client.post(f"{AGENT_API_URL}/kill")
            return res.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Agent unreachable: {e}")


# --- SSE Streaming ---

@app.get("/api/stream/{run_id}")
async def stream_events(run_id: str):
    """SSE endpoint — streams tool calls and audit events in real-time via pg LISTEN/NOTIFY."""

    async def event_generator():
        conn = await asyncpg.connect(AUDIT_DB_URL)
        queue: asyncio.Queue = asyncio.Queue()

        def on_tool_call(conn, pid, channel, payload):
            try:
                data = json.loads(payload)
                if str(data.get("run_id")) == run_id:
                    queue.put_nowait(("tool_call", data))
            except json.JSONDecodeError:
                pass

        def on_audit(conn, pid, channel, payload):
            try:
                data = json.loads(payload)
                if str(data.get("run_id")) == run_id:
                    queue.put_nowait(("audit", data))
            except json.JSONDecodeError:
                pass

        await conn.add_listener("tool_call_inserted", on_tool_call)
        await conn.add_listener("audit_inserted", on_audit)

        try:
            yield f"event: connected\ndata: {json.dumps({'run_id': run_id})}\n\n"

            while True:
                try:
                    event_type, data = await asyncio.wait_for(queue.get(), timeout=30)
                    payload = json.dumps(data, default=str)
                    yield f"event: {event_type}\ndata: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield f"event: ping\ndata: {json.dumps({'ts': 'keepalive'})}\n\n"
        finally:
            await conn.remove_listener("tool_call_inserted", on_tool_call)
            await conn.remove_listener("audit_inserted", on_audit)
            await conn.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/stream/latest")
async def stream_latest():
    """Stream events for the most recent run."""
    row = await pool.fetchrow(
        "SELECT id FROM runs ORDER BY started_at DESC LIMIT 1"
    )
    if not row:
        raise HTTPException(status_code=404, detail="No runs found")
    return await stream_events(str(row["id"]))
