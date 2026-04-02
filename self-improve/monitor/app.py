"""FastAPI monitoring app with SSE for real-time tool call streaming.

Provides:
- Real-time event feed via SSE (polling SQLite)
- Run history and detail APIs
- Control signals: pause, resume, inject prompt, stop
- Settings management with encrypted credential storage
"""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite
import httpx
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

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


async def _get_db() -> aiosqlite.Connection:
    """Get or create the SQLite connection."""
    global db
    if db is None:
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        db = await aiosqlite.connect(DB_PATH)
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=5000")
        await db.executescript(SCHEMA)
        # Migrate: add github_repo column to runs if missing
        cursor = await db.execute("PRAGMA table_info(runs)")
        cols = {row[1] for row in await cursor.fetchall()}
        if "github_repo" not in cols:
            await db.execute("ALTER TABLE runs ADD COLUMN github_repo TEXT")
        # Migrate: add session_id and agent_id to tool_calls if missing
        cursor = await db.execute("PRAGMA table_info(tool_calls)")
        tc_cols = {row[1] for row in await cursor.fetchall()}
        if "session_id" not in tc_cols:
            await db.execute("ALTER TABLE tool_calls ADD COLUMN session_id TEXT")
        if "agent_id" not in tc_cols:
            await db.execute("ALTER TABLE tool_calls ADD COLUMN agent_id TEXT")
        await db.commit()
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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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
# Run APIs
# ---------------------------------------------------------------------------

@app.get("/api/runs")
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


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    conn = await _get_db()
    cursor = await conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    return _row_to_dict(row)


@app.get("/api/runs/{run_id}/tools")
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


@app.get("/api/runs/{run_id}/audit")
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
    payload: str | None = None


async def _send_agent_signal(signal: str, payload: str | None = None) -> None:
    """Forward a control signal to the agent container via HTTP."""
    # Map signal names to agent HTTP endpoints
    endpoint_map = {"resume": "resume_signal", "pause": "pause", "inject": "inject", "stop": "stop", "unlock": "unlock"}
    endpoint = endpoint_map.get(signal, signal)
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            body = {"payload": payload} if payload else {}
            await client.post(f"{AGENT_API_URL}/{endpoint}", json=body)
    except Exception:
        pass  # Agent may be unreachable — signal is still in DB


@app.post("/api/runs/{run_id}/pause")
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


@app.post("/api/runs/{run_id}/resume")
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


@app.post("/api/runs/{run_id}/inject")
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


@app.post("/api/runs/{run_id}/stop")
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


@app.post("/api/runs/{run_id}/unlock")
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
# Agent proxy (start / health / branches / diff / stop / kill / resume)
# ---------------------------------------------------------------------------

class StartRunRequest(BaseModel):
    prompt: str | None = None
    max_budget_usd: float = 0
    duration_minutes: float = 0
    base_branch: str = "main"


@app.get("/api/agent/health")
async def agent_health():
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            res = await client.get(f"{AGENT_API_URL}/health")
            return res.json()
    except Exception as e:
        return {"status": "unreachable", "error": str(e)}


@app.post("/api/agent/start")
async def start_agent_run(body: StartRunRequest = StartRunRequest()):
    """Trigger a new improvement run. Decrypts stored credentials and passes them to agent."""
    conn = await _get_db()

    # Read decrypted credentials from settings DB
    creds = {}
    for key, env_key in [("claude_token", "claude_token"), ("git_token", "git_token"), ("github_repo", "github_repo")]:
        cursor = await conn.execute("SELECT value, encrypted FROM settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        if row:
            val = crypto.decrypt(row["value"], MASTER_KEY_PATH) if row["encrypted"] else row["value"]
            creds[env_key] = val

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.post(
                f"{AGENT_API_URL}/start",
                json={
                    "prompt": body.prompt,
                    "max_budget_usd": body.max_budget_usd,
                    "duration_minutes": body.duration_minutes,
                    "base_branch": body.base_branch,
                    **creds,
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
            res = await client.get(f"{AGENT_API_URL}/branches")
            if res.status_code == 200:
                return res.json()
    except Exception:
        pass
    return ["main"]


@app.get("/api/runs/{run_id}/diff")
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
                res = await client.get(f"{AGENT_API_URL}/diff/live")
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
            res = await client.get(f"{AGENT_API_URL}/diff/{branch}", params={"base": base})
            if res.status_code == 200:
                data = res.json()
                data["source"] = "agent"
                return data
    except Exception:
        pass

    return {"files": [], "total_files": 0, "total_added": 0, "total_removed": 0, "source": "unavailable"}


@app.post("/api/agent/stop")
async def stop_agent_instant():
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            res = await client.post(f"{AGENT_API_URL}/stop")
            return res.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Agent unreachable: {e}")


class ResumeRunRequest(BaseModel):
    run_id: str
    max_budget_usd: float = 0


@app.post("/api/agent/resume")
async def resume_agent_run(body: ResumeRunRequest):
    """Resume a previous run. Passes decrypted credentials to agent."""
    conn = await _get_db()

    creds = {}
    for key in ("claude_token", "git_token", "github_repo"):
        cursor = await conn.execute("SELECT value, encrypted FROM settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        if row:
            val = crypto.decrypt(row["value"], MASTER_KEY_PATH) if row["encrypted"] else row["value"]
            creds[key] = val

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.post(
                f"{AGENT_API_URL}/resume",
                json={"run_id": body.run_id, "max_budget_usd": body.max_budget_usd, **creds},
            )
            if res.status_code == 409:
                raise HTTPException(status_code=409, detail=res.json().get("detail", "Run in progress"))
            return res.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Agent unreachable: {e}")


@app.post("/api/agent/kill")
async def kill_agent():
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            res = await client.post(f"{AGENT_API_URL}/kill")
            return res.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Agent unreachable: {e}")


# ---------------------------------------------------------------------------
# SSE Streaming (polling SQLite instead of pg LISTEN/NOTIFY)
# ---------------------------------------------------------------------------

@app.get("/api/stream/{run_id}")
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


@app.get("/api/stream/latest")
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


@app.get("/api/settings/status")
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


@app.get("/api/settings")
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
    claude_token: str | None = None
    git_token: str | None = None
    github_repo: str | None = None
    max_budget_usd: str | None = None


@app.put("/api/settings")
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


@app.get("/api/repos")
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


@app.put("/api/repos/active")
async def set_active_repo(body: dict):
    """Set the active repo."""
    repo = body.get("repo", "").strip()
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


@app.delete("/api/repos/{repo_slug:path}")
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
