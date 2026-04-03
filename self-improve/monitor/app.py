"""FastAPI monitoring app with SSE for real-time tool call streaming.

Provides:
- Real-time event feed via SSE (polling SQLite)
- Run history and detail APIs
- Control signals: pause, resume, inject prompt, stop
- Settings management with encrypted credential storage
"""

import asyncio
import hmac
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite
import httpx
from fastapi import Depends, FastAPI, Header, Query, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

from monitor import crypto


DB_PATH = os.environ.get("DB_PATH", "/data/improve.db")
MASTER_KEY_PATH = os.environ.get("MASTER_KEY_PATH", "/data/master.key")
AGENT_API_URL = os.environ.get("AGENT_API_URL", "http://agent:8500")

# Schema (same as agent/db.py — CREATE IF NOT EXISTS is safe to run from both sides)
SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at TEXT,
    branch_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    pr_url TEXT,
    total_tool_calls INTEGER DEFAULT 0,
    total_cost_usd REAL DEFAULT 0,
    total_input_tokens INTEGER DEFAULT 0,
    total_output_tokens INTEGER DEFAULT 0,
    rate_limit_info TEXT,
    error_message TEXT,
    sdk_session_id TEXT,
    custom_prompt TEXT,
    duration_minutes REAL DEFAULT 0,
    base_branch TEXT DEFAULT 'main',
    rate_limit_resets_at INTEGER,
    diff_stats TEXT,
    github_repo TEXT
);

CREATE TABLE IF NOT EXISTS tool_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id),
    ts TEXT NOT NULL DEFAULT (datetime('now')),
    phase TEXT NOT NULL CHECK (phase IN ('pre', 'post')),
    tool_name TEXT NOT NULL,
    input_data TEXT,
    output_data TEXT,
    duration_ms INTEGER,
    permitted INTEGER NOT NULL DEFAULT 1,
    deny_reason TEXT,
    agent_role TEXT NOT NULL DEFAULT 'worker',
    tool_use_id TEXT,
    session_id TEXT,
    agent_id TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id),
    ts TEXT NOT NULL DEFAULT (datetime('now')),
    event_type TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS control_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id),
    ts TEXT NOT NULL DEFAULT (datetime('now')),
    signal TEXT NOT NULL CHECK (signal IN ('pause', 'resume', 'inject', 'stop', 'unlock')),
    payload TEXT,
    consumed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    encrypted INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_tool_calls_run_id ON tool_calls(run_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_ts ON tool_calls(ts);
CREATE INDEX IF NOT EXISTS idx_audit_log_run_id ON audit_log(run_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_event_type ON audit_log(event_type);
CREATE INDEX IF NOT EXISTS idx_control_signals_run_id ON control_signals(run_id);
CREATE INDEX IF NOT EXISTS idx_control_signals_pending ON control_signals(run_id, consumed);
"""

db: aiosqlite.Connection | None = None
_db_lock = asyncio.Lock()


async def _get_db() -> aiosqlite.Connection:
    """Get or create the SQLite connection (concurrency-safe)."""
    global db
    if db is not None:
        return db
    async with _db_lock:
        # Double-check after acquiring lock
        if db is not None:
            return db
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(DB_PATH)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA busy_timeout=5000")
        await conn.executescript(SCHEMA)
        # Migrate: add github_repo column to runs if missing
        cursor = await conn.execute("PRAGMA table_info(runs)")
        cols = {row[1] for row in await cursor.fetchall()}
        if "github_repo" not in cols:
            await conn.execute("ALTER TABLE runs ADD COLUMN github_repo TEXT")
        # Migrate: add session_id and agent_id to tool_calls if missing
        cursor = await conn.execute("PRAGMA table_info(tool_calls)")
        tc_cols = {row[1] for row in await cursor.fetchall()}
        if "session_id" not in tc_cols:
            await conn.execute("ALTER TABLE tool_calls ADD COLUMN session_id TEXT")
        if "agent_id" not in tc_cols:
            await conn.execute("ALTER TABLE tool_calls ADD COLUMN agent_id TEXT")
        await conn.commit()
        db = conn
    return db


async def _autofill_settings(conn: aiosqlite.Connection) -> None:
    """Import env vars into settings DB if settings are empty (first-boot autofill)."""
    cursor = await conn.execute("SELECT count(*) FROM settings")
    row = await cursor.fetchone()
    if row[0] > 0:
        return  # Settings already configured, skip autofill

    env_mappings = {
        "claude_token": "CLAUDE_CODE_OAUTH_TOKEN",
        "git_token": "GIT_TOKEN",
        "github_repo": "GITHUB_REPO",
        "max_budget_usd": "MAX_BUDGET_USD",
    }
    secrets = {"claude_token", "git_token"}

    for key, env_var in env_mappings.items():
        val = os.environ.get(env_var)
        if val:
            is_secret = key in secrets
            stored_val = crypto.encrypt(val, MASTER_KEY_PATH) if is_secret else val
            await conn.execute(
                """INSERT OR REPLACE INTO settings (key, value, encrypted, updated_at)
                VALUES (?, ?, ?, datetime('now'))""",
                (key, stored_val, 1 if is_secret else 0),
            )
    await conn.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = await _get_db()
    await _autofill_settings(conn)
    yield
    if db:
        await db.close()


app = FastAPI(title="SignalPilot Self-Improve Monitor API", lifespan=lifespan)

# Restrict CORS to known frontends — do not use wildcard in production
_CORS_ORIGINS = os.environ.get(
    "CORS_ORIGINS",
    "http://localhost:3401,http://localhost:3400,http://127.0.0.1:3401,http://127.0.0.1:3400",
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _CORS_ORIGINS],
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "X-API-Key"],
)


# ---------------------------------------------------------------------------
# API key auth
# ---------------------------------------------------------------------------

_API_KEY = os.environ.get("SP_API_KEY", "")


async def verify_api_key(x_api_key: str = Header(default="")) -> None:
    """Verify API key if SP_API_KEY is configured. Skip auth if not set."""
    if not _API_KEY:
        return  # No API key configured — allow all (local dev)
    if not x_api_key or not hmac.compare_digest(x_api_key, _API_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def _agent_headers() -> dict[str, str]:
    """Build headers for monitor-to-agent proxy calls, including API key if configured."""
    headers: dict[str, str] = {}
    if _API_KEY:
        headers["X-API-Key"] = _API_KEY
    return headers


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_dict(row: aiosqlite.Row) -> dict:
    """Convert an aiosqlite.Row to a plain dict with JSON parsing."""
    d = dict(row)
    # Parse JSON text columns back to objects
    for col in ("input_data", "output_data", "details", "rate_limit_info", "diff_stats"):
        if col in d and isinstance(d[col], str):
            try:
                d[col] = json.loads(d[col])
            except (json.JSONDecodeError, TypeError):
                pass
    # Convert SQLite integer booleans
    if "permitted" in d:
        d["permitted"] = bool(d["permitted"])
    return d


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Run APIs
# ---------------------------------------------------------------------------

@app.get("/api/runs", dependencies=[Depends(verify_api_key)])
async def list_runs(repo: str | None = Query(default=None)):
    conn = await _get_db()
    if repo:
        cursor = await conn.execute(
            "SELECT * FROM runs WHERE github_repo = ? ORDER BY started_at DESC LIMIT 50",
            (repo,),
        )
    else:
        cursor = await conn.execute(
            "SELECT * FROM runs ORDER BY started_at DESC LIMIT 50"
        )
    rows = await cursor.fetchall()
    return [_row_to_dict(r) for r in rows]


@app.get("/api/runs/{run_id}", dependencies=[Depends(verify_api_key)])
async def get_run(run_id: str):
    conn = await _get_db()
    cursor = await conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    return _row_to_dict(row)


@app.get("/api/runs/{run_id}/tools", dependencies=[Depends(verify_api_key)])
async def get_tool_calls(
    run_id: str,
    limit: int = Query(default=200, le=1000),
    offset: int = Query(default=0, ge=0),
):
    conn = await _get_db()
    cursor = await conn.execute(
        """SELECT * FROM tool_calls
        WHERE run_id = ?
        ORDER BY ts DESC
        LIMIT ? OFFSET ?""",
        (run_id, limit, offset),
    )
    rows = await cursor.fetchall()
    return [_row_to_dict(r) for r in rows]


@app.get("/api/runs/{run_id}/audit", dependencies=[Depends(verify_api_key)])
async def get_audit_log(
    run_id: str,
    limit: int = Query(default=200, le=1000),
    offset: int = Query(default=0, ge=0),
):
    conn = await _get_db()
    cursor = await conn.execute(
        """SELECT * FROM audit_log
        WHERE run_id = ?
        ORDER BY ts DESC
        LIMIT ? OFFSET ?""",
        (run_id, limit, offset),
    )
    rows = await cursor.fetchall()
    return [_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Control Signal APIs (dual-write: DB for audit + HTTP for instant delivery)
# ---------------------------------------------------------------------------

class ControlSignalRequest(BaseModel):
    payload: str | None = Field(default=None, max_length=50000)


async def _send_agent_signal(signal: str, payload: str | None = None) -> None:
    """Forward a control signal to the agent container via HTTP."""
    # Map signal names to agent HTTP endpoints
    endpoint_map = {"resume": "resume_signal", "pause": "pause", "inject": "inject", "stop": "stop", "unlock": "unlock"}
    endpoint = endpoint_map.get(signal, signal)
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            body = {"payload": payload} if payload else {}
            await client.post(f"{AGENT_API_URL}/{endpoint}", json=body, headers=_agent_headers())
    except Exception:
        pass  # Agent may be unreachable — signal is still in DB


@app.post("/api/runs/{run_id}/pause", dependencies=[Depends(verify_api_key)])
async def pause_run(run_id: str):
    conn = await _get_db()
    cursor = await conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    if row["status"] not in ("running",):
        raise HTTPException(status_code=409, detail=f"Cannot pause run with status '{row['status']}'")

    await conn.execute(
        "INSERT INTO control_signals (run_id, signal) VALUES (?, 'pause')",
        (run_id,),
    )
    await conn.commit()
    await _send_agent_signal("pause")
    return {"ok": True, "signal": "pause"}


@app.post("/api/runs/{run_id}/resume", dependencies=[Depends(verify_api_key)])
async def resume_run(run_id: str):
    conn = await _get_db()
    cursor = await conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    if row["status"] not in ("paused",):
        raise HTTPException(status_code=409, detail=f"Cannot resume run with status '{row['status']}'")

    await conn.execute(
        "INSERT INTO control_signals (run_id, signal) VALUES (?, 'resume')",
        (run_id,),
    )
    await conn.commit()
    await _send_agent_signal("resume")
    return {"ok": True, "signal": "resume"}


@app.post("/api/runs/{run_id}/inject", dependencies=[Depends(verify_api_key)])
async def inject_prompt(run_id: str, body: ControlSignalRequest):
    if not body.payload or not body.payload.strip():
        raise HTTPException(status_code=400, detail="Payload (prompt text) is required")

    conn = await _get_db()
    cursor = await conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    if row["status"] not in ("running", "paused"):
        raise HTTPException(status_code=409, detail=f"Cannot inject into run with status '{row['status']}'")

    payload = body.payload.strip()
    await conn.execute(
        "INSERT INTO control_signals (run_id, signal, payload) VALUES (?, 'inject', ?)",
        (run_id, payload),
    )
    await conn.commit()
    await _send_agent_signal("inject", payload)
    return {"ok": True, "signal": "inject", "prompt_length": len(payload)}


@app.post("/api/runs/{run_id}/stop", dependencies=[Depends(verify_api_key)])
async def stop_run(run_id: str, body: ControlSignalRequest = ControlSignalRequest()):
    conn = await _get_db()
    cursor = await conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    if row["status"] not in ("running", "paused", "rate_limited"):
        raise HTTPException(status_code=409, detail=f"Cannot stop run with status '{row['status']}'")

    reason = (body.payload or "").strip() or "Operator requested stop"
    await conn.execute(
        "INSERT INTO control_signals (run_id, signal, payload) VALUES (?, 'stop', ?)",
        (run_id, reason),
    )
    await conn.commit()
    await _send_agent_signal("stop", reason)
    return {"ok": True, "signal": "stop", "reason": reason}


@app.post("/api/runs/{run_id}/unlock", dependencies=[Depends(verify_api_key)])
async def unlock_run(run_id: str):
    conn = await _get_db()
    cursor = await conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    if row["status"] not in ("running", "paused", "rate_limited"):
        raise HTTPException(status_code=409, detail=f"Cannot unlock run with status '{row['status']}'")

    await conn.execute(
        "INSERT INTO control_signals (run_id, signal) VALUES (?, 'unlock')",
        (run_id,),
    )
    await conn.commit()
    await _send_agent_signal("unlock")
    return {"ok": True, "signal": "unlock"}


# ---------------------------------------------------------------------------
# Agent proxy (health / branches / diff)
# ---------------------------------------------------------------------------

@app.get("/api/agent/health", dependencies=[Depends(verify_api_key)])
async def agent_health():
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            res = await client.get(f"{AGENT_API_URL}/health", headers=_agent_headers())
            return res.json()
    except Exception as e:
        logger.error(f"Agent health check failed: {e}")
        return {"status": "unreachable", "error": "Agent unreachable"}


@app.get("/api/agent/branches", dependencies=[Depends(verify_api_key)])
async def list_branches(repo: str | None = Query(None)):
    """List branches. If repo is given, queries GitHub API directly (no agent needed).
    Falls back to agent proxy, then to ["main"]."""
    # If a specific repo was requested, use GitHub API with stored token
    if repo:
        try:
            conn = await _get_db()
            cursor = await conn.execute("SELECT value, encrypted FROM settings WHERE key = 'git_token'")
            row = await cursor.fetchone()
            if row:
                token = crypto.decrypt(row["value"], MASTER_KEY_PATH) if row["encrypted"] else row["value"]
                branches: list[str] = []
                page = 1
                async with httpx.AsyncClient(timeout=15) as client:
                    while True:
                        res = await client.get(
                            f"https://api.github.com/repos/{repo}/branches",
                            headers={
                                "Authorization": f"token {token}",
                                "Accept": "application/vnd.github.v3+json",
                            },
                            params={"per_page": 100, "page": page},
                        )
                        if res.status_code != 200:
                            break
                        data = res.json()
                        if not data:
                            break
                        branches.extend(b["name"] for b in data)
                        if len(data) < 100:
                            break
                        page += 1
                if branches:
                    return sorted(branches)
        except Exception:
            pass

    # Fallback: proxy to agent
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(f"{AGENT_API_URL}/branches", headers=_agent_headers())
            if res.status_code == 200:
                return res.json()
    except Exception:
        pass
    return ["main"]


@app.get("/api/runs/{run_id}/diff", dependencies=[Depends(verify_api_key)])
async def get_run_diff(run_id: str):
    conn = await _get_db()
    cursor = await conn.execute(
        "SELECT diff_stats, branch_name, base_branch, status FROM runs WHERE id = ?",
        (run_id,),
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")

    if row["diff_stats"]:
        stats = json.loads(row["diff_stats"]) if isinstance(row["diff_stats"], str) else row["diff_stats"]
        return {
            "files": stats,
            "total_files": len(stats),
            "total_added": sum(f.get("added", 0) for f in stats),
            "total_removed": sum(f.get("removed", 0) for f in stats),
            "source": "stored",
        }

    if row["status"] in ("running", "paused"):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                res = await client.get(f"{AGENT_API_URL}/diff/live", headers=_agent_headers())
                if res.status_code == 200:
                    data = res.json()
                    data["source"] = "live"
                    return data
        except Exception:
            pass

    branch = row["branch_name"]
    base = row["base_branch"] or "main"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(f"{AGENT_API_URL}/diff/{branch}", params={"base": base}, headers=_agent_headers())
            if res.status_code == 200:
                data = res.json()
                data["source"] = "agent"
                return data
    except Exception:
        pass

    return {"files": [], "total_files": 0, "total_added": 0, "total_removed": 0, "source": "unavailable"}


# ---------------------------------------------------------------------------
# Parallel Run APIs (proxy to agent orchestrator)
# ---------------------------------------------------------------------------

class ParallelStartRequest(BaseModel):
    prompt: str | None = Field(default=None, max_length=50000)
    max_budget_usd: float = 0
    duration_minutes: float = 0
    base_branch: str = Field(default="main", max_length=200)


@app.get("/api/parallel/runs", dependencies=[Depends(verify_api_key)])
async def list_parallel_runs():
    """List all parallel run slots from the agent orchestrator."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(f"{AGENT_API_URL}/parallel/runs", headers=_agent_headers())
            return res.json()
    except Exception as e:
        logger.error(f"Failed to list parallel runs: {e}")
        return {"runs": [], "error": "Failed to reach agent"}


@app.post("/api/parallel/start", dependencies=[Depends(verify_api_key)])
async def start_parallel_run(body: ParallelStartRequest = ParallelStartRequest()):
    """Start a new parallel agent run. Decrypts credentials and passes to orchestrator."""
    conn = await _get_db()

    # Read decrypted credentials from settings DB
    creds = {}
    for key in ("claude_token", "git_token", "github_repo"):
        cursor = await conn.execute("SELECT value, encrypted FROM settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        if row:
            val = crypto.decrypt(row["value"], MASTER_KEY_PATH) if row["encrypted"] else row["value"]
            creds[key] = val

    try:
        async with httpx.AsyncClient(timeout=180) as client:
            res = await client.post(
                f"{AGENT_API_URL}/parallel/start",
                json={
                    "prompt": body.prompt,
                    "max_budget_usd": body.max_budget_usd,
                    "duration_minutes": body.duration_minutes,
                    "base_branch": body.base_branch,
                    **creds,
                },
                headers=_agent_headers(),
            )
            if res.status_code >= 400:
                raise HTTPException(status_code=res.status_code, detail=res.json().get("detail", "Failed"))
            return res.json()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Agent unreachable during parallel start: {e}")
        raise HTTPException(status_code=502, detail="Agent unreachable")


@app.get("/api/parallel/status", dependencies=[Depends(verify_api_key)])
async def parallel_status():
    """Get parallel run system status."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(f"{AGENT_API_URL}/parallel/status", headers=_agent_headers())
            return res.json()
    except Exception as e:
        logger.error(f"Parallel status check failed: {e}")
        return {"status": "unreachable", "error": "Agent unreachable"}


@app.get("/api/parallel/runs/{run_id}", dependencies=[Depends(verify_api_key)])
async def get_parallel_run(run_id: str):
    """Get status of a specific parallel run."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(f"{AGENT_API_URL}/parallel/runs/{run_id}", headers=_agent_headers())
            if res.status_code == 404:
                raise HTTPException(status_code=404, detail="Run not found")
            return res.json()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get parallel run failed: {e}")
        raise HTTPException(status_code=502, detail="Agent unreachable")


@app.post("/api/parallel/runs/{run_id}/stop", dependencies=[Depends(verify_api_key)])
async def stop_parallel_run(run_id: str, body: ControlSignalRequest = ControlSignalRequest()):
    """Stop a specific parallel run."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.post(
                f"{AGENT_API_URL}/parallel/runs/{run_id}/stop",
                json={"payload": body.payload or "Operator stop"},
                headers=_agent_headers(),
            )
            return res.json()
    except Exception as e:
        logger.error(f"Stop parallel run failed: {e}")
        raise HTTPException(status_code=502, detail="Agent unreachable")


@app.post("/api/parallel/runs/{run_id}/kill", dependencies=[Depends(verify_api_key)])
async def kill_parallel_run(run_id: str):
    """Kill a specific parallel run."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.post(f"{AGENT_API_URL}/parallel/runs/{run_id}/kill", headers=_agent_headers())
            return res.json()
    except Exception as e:
        logger.error(f"Kill parallel run failed: {e}")
        raise HTTPException(status_code=502, detail="Agent unreachable")


@app.post("/api/parallel/runs/{run_id}/pause", dependencies=[Depends(verify_api_key)])
async def pause_parallel_run(run_id: str):
    """Pause a specific parallel run."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.post(f"{AGENT_API_URL}/parallel/runs/{run_id}/pause", headers=_agent_headers())
            return res.json()
    except Exception as e:
        logger.error(f"Pause parallel run failed: {e}")
        raise HTTPException(status_code=502, detail="Agent unreachable")


@app.post("/api/parallel/runs/{run_id}/resume", dependencies=[Depends(verify_api_key)])
async def resume_parallel_run(run_id: str):
    """Resume a paused parallel run."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.post(f"{AGENT_API_URL}/parallel/runs/{run_id}/resume", headers=_agent_headers())
            return res.json()
    except Exception as e:
        logger.error(f"Resume parallel run failed: {e}")
        raise HTTPException(status_code=502, detail="Agent unreachable")


@app.post("/api/parallel/runs/{run_id}/inject", dependencies=[Depends(verify_api_key)])
async def inject_parallel_run(run_id: str, body: ControlSignalRequest = ControlSignalRequest()):
    """Inject a prompt into a parallel run."""
    if not body.payload:
        raise HTTPException(status_code=400, detail="Payload required")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.post(
                f"{AGENT_API_URL}/parallel/runs/{run_id}/inject",
                json={"payload": body.payload},
                headers=_agent_headers(),
            )
            return res.json()
    except Exception as e:
        logger.error(f"Inject parallel run failed: {e}")
        raise HTTPException(status_code=502, detail="Agent unreachable")


@app.post("/api/parallel/runs/{run_id}/unlock", dependencies=[Depends(verify_api_key)])
async def unlock_parallel_run(run_id: str):
    """Unlock session for a parallel run."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.post(f"{AGENT_API_URL}/parallel/runs/{run_id}/unlock", headers=_agent_headers())
            return res.json()
    except Exception as e:
        logger.error(f"Unlock parallel run failed: {e}")
        raise HTTPException(status_code=502, detail="Agent unreachable")


@app.post("/api/parallel/cleanup", dependencies=[Depends(verify_api_key)])
async def cleanup_parallel():
    """Clean up finished parallel run containers."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post(f"{AGENT_API_URL}/parallel/cleanup", headers=_agent_headers())
            return res.json()
    except Exception as e:
        logger.error(f"Cleanup parallel runs failed: {e}")
        raise HTTPException(status_code=502, detail="Agent unreachable")


# ---------------------------------------------------------------------------
# SSE Streaming (polling SQLite instead of pg LISTEN/NOTIFY)
# ---------------------------------------------------------------------------

@app.get("/api/stream/{run_id}", dependencies=[Depends(verify_api_key)])
async def stream_events(run_id: str):
    """SSE endpoint — polls SQLite for new tool calls and audit events."""

    async def event_generator():
        conn = await _get_db()

        # Start from current max IDs to avoid replaying history
        cursor = await conn.execute(
            "SELECT COALESCE(MAX(id), 0) FROM tool_calls WHERE run_id = ?",
            (run_id,),
        )
        row = await cursor.fetchone()
        last_tool_id = row[0]

        cursor = await conn.execute(
            "SELECT COALESCE(MAX(id), 0) FROM audit_log WHERE run_id = ?",
            (run_id,),
        )
        row = await cursor.fetchone()
        last_audit_id = row[0]

        yield f"event: connected\ndata: {json.dumps({'run_id': run_id})}\n\n"

        while True:
            found_any = False

            # Poll for new tool calls
            cursor = await conn.execute(
                "SELECT * FROM tool_calls WHERE run_id = ? AND id > ? ORDER BY id",
                (run_id, last_tool_id),
            )
            rows = await cursor.fetchall()
            for r in rows:
                found_any = True
                last_tool_id = r["id"]
                yield f"event: tool_call\ndata: {json.dumps(_row_to_dict(r), default=str)}\n\n"

            # Poll for new audit events
            cursor = await conn.execute(
                "SELECT * FROM audit_log WHERE run_id = ? AND id > ? ORDER BY id",
                (run_id, last_audit_id),
            )
            rows = await cursor.fetchall()
            for r in rows:
                found_any = True
                last_audit_id = r["id"]
                yield f"event: audit\ndata: {json.dumps(_row_to_dict(r), default=str)}\n\n"

            if not found_any:
                yield f"event: ping\ndata: {json.dumps({'ts': 'keepalive'})}\n\n"

            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/poll/{run_id}", dependencies=[Depends(verify_api_key)])
async def poll_events(run_id: str, after_tool: int = 0, after_audit: int = 0):
    """Polling fallback for environments where SSE doesn't work (e.g. Cloudflare tunnels)."""
    conn = await _get_db()

    tool_calls = []
    cursor = await conn.execute(
        "SELECT * FROM tool_calls WHERE run_id = ? AND id > ? ORDER BY id LIMIT 100",
        (run_id, after_tool),
    )
    rows = await cursor.fetchall()
    for r in rows:
        tool_calls.append(_row_to_dict(r))

    audit_events = []
    cursor = await conn.execute(
        "SELECT * FROM audit_log WHERE run_id = ? AND id > ? ORDER BY id LIMIT 100",
        (run_id, after_audit),
    )
    rows = await cursor.fetchall()
    for r in rows:
        audit_events.append(_row_to_dict(r))

    return {
        "tool_calls": tool_calls,
        "audit_events": audit_events,
    }


@app.get("/api/stream/latest", dependencies=[Depends(verify_api_key)])
async def stream_latest():
    conn = await _get_db()
    cursor = await conn.execute(
        "SELECT id FROM runs ORDER BY started_at DESC LIMIT 1"
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="No runs found")
    return await stream_events(row["id"])


# ---------------------------------------------------------------------------
# Settings API (encrypted credential storage)
# ---------------------------------------------------------------------------

SECRET_KEYS = {"claude_token", "git_token"}


@app.get("/api/settings/status", dependencies=[Depends(verify_api_key)])
async def settings_status():
    """Check which credentials are configured."""
    conn = await _get_db()
    result = {
        "configured": False,
        "has_claude_token": False,
        "has_git_token": False,
        "has_github_repo": False,
    }
    for key in ("claude_token", "git_token", "github_repo"):
        cursor = await conn.execute("SELECT 1 FROM settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        result[f"has_{key}"] = row is not None

    result["configured"] = all([
        result["has_claude_token"],
        result["has_git_token"],
        result["has_github_repo"],
    ])
    return result


@app.get("/api/settings", dependencies=[Depends(verify_api_key)])
async def get_settings():
    """Get all settings with secrets masked."""
    conn = await _get_db()
    cursor = await conn.execute("SELECT key, value, encrypted FROM settings")
    rows = await cursor.fetchall()
    result = {}
    for row in rows:
        if row["encrypted"]:
            try:
                plain = crypto.decrypt(row["value"], MASTER_KEY_PATH)
                prefix = 8 if row["key"] == "claude_token" else 6
                result[row["key"]] = crypto.mask(plain, prefix_len=prefix)
            except Exception:
                result[row["key"]] = "****"
        else:
            result[row["key"]] = row["value"]
    return result


class UpdateSettingsRequest(BaseModel):
    claude_token: str | None = Field(default=None, max_length=500)
    git_token: str | None = Field(default=None, max_length=500)
    github_repo: str | None = Field(default=None, max_length=200)
    max_budget_usd: str | None = Field(default=None, max_length=20)


@app.put("/api/settings", dependencies=[Depends(verify_api_key)])
async def update_settings(body: UpdateSettingsRequest):
    """Create or update settings. Secrets are encrypted before storage."""
    conn = await _get_db()
    updates = body.model_dump(exclude_none=True)

    for key, value in updates.items():
        is_secret = key in SECRET_KEYS
        stored_val = crypto.encrypt(value, MASTER_KEY_PATH) if is_secret else value
        await conn.execute(
            """INSERT INTO settings (key, value, encrypted, updated_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                encrypted = excluded.encrypted,
                updated_at = excluded.updated_at""",
            (key, stored_val, 1 if is_secret else 0),
        )

    # When github_repo is set, also add it to the repos list
    if "github_repo" in updates and updates["github_repo"]:
        await _add_repo_to_list(conn, updates["github_repo"])

    await conn.commit()
    return {"ok": True, "updated": list(updates.keys())}


async def _add_repo_to_list(conn: aiosqlite.Connection, repo: str) -> None:
    """Add a repo to the repos JSON array in settings (deduped)."""
    cursor = await conn.execute("SELECT value FROM settings WHERE key = 'repos'")
    row = await cursor.fetchone()
    repos: list[str] = []
    if row:
        try:
            repos = json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            repos = []
    if repo not in repos:
        repos.append(repo)
    await conn.execute(
        """INSERT INTO settings (key, value, encrypted, updated_at)
        VALUES ('repos', ?, 0, datetime('now'))
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value, updated_at = excluded.updated_at""",
        (json.dumps(repos),),
    )


@app.get("/api/repos", dependencies=[Depends(verify_api_key)])
async def list_repos():
    """List all configured repos."""
    conn = await _get_db()
    cursor = await conn.execute("SELECT value FROM settings WHERE key = 'repos'")
    row = await cursor.fetchone()
    repos: list[str] = []
    if row:
        try:
            repos = json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            repos = []

    # Also check active repo in case repos list is empty but github_repo is set
    cursor2 = await conn.execute("SELECT value FROM settings WHERE key = 'github_repo'")
    row2 = await cursor2.fetchone()
    if row2 and row2["value"] and row2["value"] not in repos:
        repos.append(row2["value"])
        await _add_repo_to_list(conn, row2["value"])
        await conn.commit()

    # Get run counts per repo
    result = []
    for repo in repos:
        cursor3 = await conn.execute(
            "SELECT count(*) as cnt FROM runs WHERE github_repo = ?", (repo,)
        )
        cnt_row = await cursor3.fetchone()
        result.append({"repo": repo, "run_count": cnt_row["cnt"] if cnt_row else 0})

    return result


class SetActiveRepoRequest(BaseModel):
    repo: str = Field(max_length=200)


@app.put("/api/repos/active", dependencies=[Depends(verify_api_key)])
async def set_active_repo(body: SetActiveRepoRequest):
    """Set the active repo."""
    repo = body.repo.strip()
    if not repo:
        raise HTTPException(status_code=400, detail="repo is required")
    conn = await _get_db()
    await conn.execute(
        """INSERT INTO settings (key, value, encrypted, updated_at)
        VALUES ('github_repo', ?, 0, datetime('now'))
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value, updated_at = excluded.updated_at""",
        (repo,),
    )
    await _add_repo_to_list(conn, repo)
    await conn.commit()
    return {"ok": True, "active_repo": repo}


@app.delete("/api/repos/{repo_slug:path}", dependencies=[Depends(verify_api_key)])
async def remove_repo(repo_slug: str):
    """Remove a repo from the list (does not delete runs)."""
    conn = await _get_db()
    cursor = await conn.execute("SELECT value FROM settings WHERE key = 'repos'")
    row = await cursor.fetchone()
    repos: list[str] = []
    if row:
        try:
            repos = json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            repos = []
    repos = [r for r in repos if r != repo_slug]
    await conn.execute(
        """INSERT INTO settings (key, value, encrypted, updated_at)
        VALUES ('repos', ?, 0, datetime('now'))
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value, updated_at = excluded.updated_at""",
        (json.dumps(repos),),
    )
    await conn.commit()
    return {"ok": True, "remaining": repos}


# ── Tunnel management ────────────────────────────────────────────────────────

import docker  # noqa: E402

_docker_client: docker.DockerClient | None = None
TUNNEL_CONTAINER = "improve-tunnel"
TUNNEL_URL_RE = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")


def _get_docker() -> docker.DockerClient:
    global _docker_client
    if _docker_client is None:
        _docker_client = docker.from_env()
    return _docker_client


def _parse_tunnel_url(container) -> str | None:
    try:
        logs = container.logs(tail=50).decode("utf-8", errors="replace")
        matches = TUNNEL_URL_RE.findall(logs)
        return matches[-1] if matches else None
    except Exception:
        return None


@app.get("/api/tunnel/status")
async def tunnel_status():
    try:
        container = _get_docker().containers.get(TUNNEL_CONTAINER)
        url = _parse_tunnel_url(container) if container.status == "running" else None
        return {
            "status": container.status,
            "url": url,
            "container_id": container.short_id,
        }
    except docker.errors.NotFound:
        return {"status": "not_found", "url": None}
    except docker.errors.APIError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/tunnel/start")
async def tunnel_start():
    try:
        container = _get_docker().containers.get(TUNNEL_CONTAINER)
        if container.status == "running":
            return {"ok": True, "message": "already running"}
        container.start()
        return {"ok": True}
    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail="Tunnel container not found")
    except docker.errors.APIError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/tunnel/stop")
async def tunnel_stop():
    try:
        container = _get_docker().containers.get(TUNNEL_CONTAINER)
        container.stop(timeout=5)
        return {"ok": True}
    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail="Tunnel container not found")
    except docker.errors.APIError as e:
        raise HTTPException(status_code=502, detail=str(e))
