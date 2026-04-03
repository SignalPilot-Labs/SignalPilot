"""Database utilities for audit logging — SQLite backend."""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite


_db: aiosqlite.Connection | None = None


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

CREATE TABLE IF NOT EXISTS workers (
    container_name TEXT PRIMARY KEY,
    run_id TEXT,
    container_id TEXT,
    status TEXT NOT NULL DEFAULT 'starting',
    prompt TEXT,
    max_budget_usd REAL DEFAULT 0,
    duration_minutes REAL DEFAULT 0,
    base_branch TEXT DEFAULT 'main',
    volume_name TEXT,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at TEXT,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_tool_calls_run_id ON tool_calls(run_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_ts ON tool_calls(ts);
CREATE INDEX IF NOT EXISTS idx_audit_log_run_id ON audit_log(run_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_event_type ON audit_log(event_type);
CREATE INDEX IF NOT EXISTS idx_control_signals_run_id ON control_signals(run_id);
CREATE INDEX IF NOT EXISTS idx_control_signals_pending ON control_signals(run_id, consumed);
CREATE INDEX IF NOT EXISTS idx_workers_status ON workers(status);

CREATE TABLE IF NOT EXISTS api_keys (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL CHECK (provider IN ('claude_code', 'codex')),
    label TEXT NOT NULL DEFAULT '',
    encrypted_key TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    is_enabled INTEGER NOT NULL DEFAULT 1,
    rate_limit_resets_at INTEGER,
    rate_limit_utilization REAL,
    last_used_at TEXT,
    total_requests INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_api_keys_provider ON api_keys(provider);
CREATE INDEX IF NOT EXISTS idx_api_keys_priority ON api_keys(provider, priority, is_enabled);

CREATE TABLE IF NOT EXISTS key_rotation_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


async def init_db(db_path: str) -> aiosqlite.Connection:
    """Open SQLite database, enable WAL mode, and create schema."""
    global _db
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    _db = await aiosqlite.connect(db_path)
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA busy_timeout=5000")
    await _db.executescript(SCHEMA)
    # Migrate: add github_repo column to runs if missing
    cursor = await _db.execute("PRAGMA table_info(runs)")
    cols = {row[1] for row in await cursor.fetchall()}
    if "github_repo" not in cols:
        await _db.execute("ALTER TABLE runs ADD COLUMN github_repo TEXT")
    # Migrate: add session_id and agent_id to tool_calls if missing
    cursor = await _db.execute("PRAGMA table_info(tool_calls)")
    tc_cols = {row[1] for row in await cursor.fetchall()}
    if "session_id" not in tc_cols:
        await _db.execute("ALTER TABLE tool_calls ADD COLUMN session_id TEXT")
    if "agent_id" not in tc_cols:
        await _db.execute("ALTER TABLE tool_calls ADD COLUMN agent_id TEXT")
    # NOTE: Do NOT mark runs as crashed here — workers share this DB.
    # Cleanup is handled by the orchestrator in lifespan() via mark_crashed_runs().
    await _db.commit()
    return _db


def get_db() -> aiosqlite.Connection:
    """Get the cached connection. Raises if not initialized."""
    if _db is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _db


async def close_db() -> None:
    """Close the database connection."""
    global _db
    if _db:
        await _db.close()
        _db = None


async def create_run(
    branch_name: str,
    custom_prompt: str | None = None,
    duration_minutes: float = 0,
    base_branch: str = "main",
    github_repo: str | None = None,
) -> str:
    """Create a new run record. Returns the run UUID as string."""
    import os
    conn = get_db()
    run_id = str(uuid.uuid4())
    repo = github_repo or os.environ.get("GITHUB_REPO", "")
    await conn.execute(
        """INSERT INTO runs (id, branch_name, custom_prompt, duration_minutes, base_branch, github_repo)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (run_id, branch_name, custom_prompt, duration_minutes, base_branch, repo or None),
    )
    await conn.commit()
    return run_id


async def save_rate_limit_reset(run_id: str, resets_at: int) -> None:
    """Save the rate limit reset timestamp."""
    conn = get_db()
    await conn.execute(
        "UPDATE runs SET rate_limit_resets_at = ? WHERE id = ?",
        (resets_at, run_id),
    )
    await conn.commit()


async def save_session_id(run_id: str, session_id: str) -> None:
    """Save the SDK session ID so we can resume later."""
    conn = get_db()
    await conn.execute(
        "UPDATE runs SET sdk_session_id = ? WHERE id = ?",
        (session_id, run_id),
    )
    await conn.commit()


async def get_run_for_resume(run_id: str) -> dict | None:
    """Get run info needed to resume a session."""
    conn = get_db()
    cursor = await conn.execute(
        """SELECT id, branch_name, status, sdk_session_id, custom_prompt,
                  duration_minutes, base_branch, total_cost_usd,
                  total_input_tokens, total_output_tokens
        FROM runs WHERE id = ?""",
        (run_id,),
    )
    row = await cursor.fetchone()
    if not row:
        return None
    return dict(row)


async def finish_run(
    run_id: str,
    status: str,
    pr_url: str | None = None,
    total_cost_usd: float | None = None,
    total_input_tokens: int | None = None,
    total_output_tokens: int | None = None,
    error_message: str | None = None,
    rate_limit_info: dict | None = None,
    diff_stats: list | None = None,
) -> None:
    """Mark a run as finished with final stats."""
    conn = get_db()
    # Count tool calls first
    cursor = await conn.execute(
        "SELECT count(*) FROM tool_calls WHERE run_id = ? AND phase = 'pre'",
        (run_id,),
    )
    count_row = await cursor.fetchone()
    tool_count = count_row[0] if count_row else 0

    await conn.execute(
        """UPDATE runs SET
            ended_at = datetime('now'),
            status = ?,
            pr_url = ?,
            total_cost_usd = ?,
            total_input_tokens = ?,
            total_output_tokens = ?,
            error_message = ?,
            rate_limit_info = ?,
            diff_stats = ?,
            total_tool_calls = ?
        WHERE id = ?""",
        (
            status,
            pr_url,
            total_cost_usd,
            total_input_tokens,
            total_output_tokens,
            error_message,
            json.dumps(rate_limit_info) if rate_limit_info else None,
            json.dumps(diff_stats) if diff_stats else None,
            tool_count,
            run_id,
        ),
    )
    await conn.commit()


async def log_tool_call(
    run_id: str,
    phase: str,
    tool_name: str,
    input_data: dict | None = None,
    output_data: dict | None = None,
    duration_ms: int | None = None,
    permitted: bool = True,
    deny_reason: str | None = None,
    agent_role: str = "worker",
    tool_use_id: str | None = None,
    session_id: str | None = None,
    agent_id: str | None = None,
) -> int:
    """Log a tool call. Returns the row id."""
    conn = get_db()
    cursor = await conn.execute(
        """INSERT INTO tool_calls
            (run_id, phase, tool_name, input_data, output_data, duration_ms, permitted, deny_reason, agent_role, tool_use_id, session_id, agent_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            run_id,
            phase,
            tool_name,
            json.dumps(input_data) if input_data else None,
            json.dumps(output_data) if output_data else None,
            duration_ms,
            1 if permitted else 0,
            deny_reason,
            agent_role,
            tool_use_id,
            session_id,
            agent_id,
        ),
    )
    await conn.commit()
    return cursor.lastrowid


async def log_audit(
    run_id: str,
    event_type: str,
    details: dict | None = None,
) -> None:
    """Log an audit event."""
    conn = get_db()
    await conn.execute(
        "INSERT INTO audit_log (run_id, event_type, details) VALUES (?, ?, ?)",
        (run_id, event_type, json.dumps(details or {})),
    )
    await conn.commit()


async def update_run_status(run_id: str, status: str) -> None:
    """Update the run status (e.g. to 'paused')."""
    conn = get_db()
    await conn.execute(
        "UPDATE runs SET status = ? WHERE id = ?",
        (status, run_id),
    )
    await conn.commit()


async def mark_crashed_runs() -> int:
    """Mark any 'running' or 'paused' runs as 'crashed' on startup."""
    conn = get_db()
    cursor = await conn.execute(
        """UPDATE runs SET status = 'crashed', ended_at = datetime('now'),
           error_message = 'Agent container restarted while run was in progress'
        WHERE status IN ('running', 'paused')"""
    )
    await conn.commit()
    return cursor.rowcount


# --- Worker (bot) tracking ---

async def upsert_worker(
    container_name: str,
    status: str,
    run_id: str | None = None,
    container_id: str | None = None,
    prompt: str | None = None,
    max_budget_usd: float = 0,
    duration_minutes: float = 0,
    base_branch: str = "main",
    volume_name: str | None = None,
    error_message: str | None = None,
) -> None:
    """Insert or update a worker slot in the DB."""
    conn = get_db()
    await conn.execute(
        """INSERT INTO workers (container_name, run_id, container_id, status, prompt,
                                max_budget_usd, duration_minutes, base_branch, volume_name, error_message)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(container_name) DO UPDATE SET
               run_id = COALESCE(excluded.run_id, workers.run_id),
               container_id = COALESCE(excluded.container_id, workers.container_id),
               status = excluded.status,
               error_message = excluded.error_message""",
        (container_name, run_id, container_id, status, prompt,
         max_budget_usd, duration_minutes, base_branch, volume_name, error_message),
    )
    await conn.commit()


async def update_worker_status(container_name: str, status: str, error_message: str | None = None) -> None:
    """Update a worker's status."""
    conn = get_db()
    ended = "datetime('now')" if status not in ("starting", "running") else "NULL"
    await conn.execute(
        f"""UPDATE workers SET status = ?, error_message = ?,
            ended_at = CASE WHEN ? NOT IN ('starting', 'running') THEN datetime('now') ELSE ended_at END
            WHERE container_name = ?""",
        (status, error_message, status, container_name),
    )
    await conn.commit()


async def update_worker_run_id(container_name: str, run_id: str) -> None:
    """Set the run_id once the worker's agent starts."""
    conn = get_db()
    await conn.execute(
        "UPDATE workers SET run_id = ? WHERE container_name = ?",
        (run_id, container_name),
    )
    await conn.commit()


async def get_active_workers() -> list[dict]:
    """Get all workers with status starting or running."""
    conn = get_db()
    cursor = await conn.execute(
        "SELECT * FROM workers WHERE status IN ('starting', 'running') ORDER BY started_at DESC"
    )
    return [dict(row) for row in await cursor.fetchall()]


async def get_all_workers(limit: int = 50) -> list[dict]:
    """Get all workers ordered by most recent."""
    conn = get_db()
    cursor = await conn.execute(
        "SELECT * FROM workers ORDER BY started_at DESC LIMIT ?", (limit,)
    )
    return [dict(row) for row in await cursor.fetchall()]


async def mark_orphaned_workers() -> int:
    """Mark any 'starting'/'running' workers as 'killed' on startup (ghosts from previous process)."""
    conn = get_db()
    cursor = await conn.execute(
        """UPDATE workers SET status = 'killed', ended_at = datetime('now'),
           error_message = 'Orphaned: parent agent restarted'
        WHERE status IN ('starting', 'running')"""
    )
    await conn.commit()
    return cursor.rowcount
