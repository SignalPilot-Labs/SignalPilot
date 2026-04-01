"""Database utilities for audit logging."""

import json
import uuid
from datetime import datetime, timezone

import asyncpg


_pool: asyncpg.Pool | None = None


async def init_pool(dsn: str) -> asyncpg.Pool:
    """Create and cache the connection pool."""
    global _pool
    _pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)
    return _pool


def get_pool() -> asyncpg.Pool:
    """Get the cached pool. Raises if not initialized."""
    if _pool is None:
        raise RuntimeError("Database pool not initialized. Call init_pool() first.")
    return _pool


async def create_run(branch_name: str) -> str:
    """Create a new run record. Returns the run UUID as string."""
    pool = get_pool()
    row = await pool.fetchrow(
        "INSERT INTO runs (branch_name) VALUES ($1) RETURNING id",
        branch_name,
    )
    return str(row["id"])


async def finish_run(
    run_id: str,
    status: str,
    pr_url: str | None = None,
    total_cost_usd: float | None = None,
    total_input_tokens: int | None = None,
    total_output_tokens: int | None = None,
    error_message: str | None = None,
    rate_limit_info: dict | None = None,
) -> None:
    """Mark a run as finished with final stats."""
    pool = get_pool()
    await pool.execute(
        """UPDATE runs SET
            ended_at = now(),
            status = $2,
            pr_url = $3,
            total_cost_usd = $4,
            total_input_tokens = $5,
            total_output_tokens = $6,
            error_message = $7,
            rate_limit_info = $8,
            total_tool_calls = (SELECT count(*) FROM tool_calls WHERE run_id = $1 AND phase = 'pre')
        WHERE id = $1""",
        uuid.UUID(run_id),
        status,
        pr_url,
        total_cost_usd,
        total_input_tokens,
        total_output_tokens,
        error_message,
        json.dumps(rate_limit_info) if rate_limit_info else None,
    )


async def log_tool_call(
    run_id: str,
    phase: str,
    tool_name: str,
    input_data: dict | None = None,
    output_data: dict | None = None,
    duration_ms: int | None = None,
    permitted: bool = True,
    deny_reason: str | None = None,
) -> int:
    """Log a tool call. Returns the row id."""
    pool = get_pool()
    row = await pool.fetchrow(
        """INSERT INTO tool_calls
            (run_id, phase, tool_name, input_data, output_data, duration_ms, permitted, deny_reason)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING id""",
        uuid.UUID(run_id),
        phase,
        tool_name,
        json.dumps(input_data) if input_data else None,
        json.dumps(output_data) if output_data else None,
        duration_ms,
        permitted,
        deny_reason,
    )
    return row["id"]


async def log_audit(
    run_id: str,
    event_type: str,
    details: dict | None = None,
) -> None:
    """Log an audit event."""
    pool = get_pool()
    await pool.execute(
        "INSERT INTO audit_log (run_id, event_type, details) VALUES ($1, $2, $3)",
        uuid.UUID(run_id),
        event_type,
        json.dumps(details or {}),
    )


async def poll_control_signal(run_id: str) -> dict | None:
    """Fetch and consume the oldest pending control signal for this run.

    Returns dict with 'signal' and 'payload' keys, or None if no pending signals.
    """
    pool = get_pool()
    row = await pool.fetchrow(
        """UPDATE control_signals
        SET consumed = TRUE
        WHERE id = (
            SELECT id FROM control_signals
            WHERE run_id = $1 AND NOT consumed
            ORDER BY ts ASC
            LIMIT 1
        )
        RETURNING signal, payload""",
        uuid.UUID(run_id),
    )
    if row:
        return {"signal": row["signal"], "payload": row["payload"]}
    return None


async def update_run_status(run_id: str, status: str) -> None:
    """Update the run status (e.g. to 'paused')."""
    pool = get_pool()
    await pool.execute(
        "UPDATE runs SET status = $2 WHERE id = $1",
        uuid.UUID(run_id),
        status,
    )


async def mark_crashed_runs() -> int:
    """Mark any 'running' or 'paused' runs as 'crashed' on startup.

    Called when the agent container starts — any run that was 'running' when
    we last went down is stale and should be marked crashed.
    Returns the number of runs marked.
    """
    pool = get_pool()
    result = await pool.execute(
        """UPDATE runs SET status = 'crashed', ended_at = now(),
           error_message = 'Agent container restarted while run was in progress'
        WHERE status IN ('running', 'paused', 'rate_limited')"""
    )
    # result is like "UPDATE N"
    try:
        return int(result.split()[-1])
    except (ValueError, IndexError):
        return 0
