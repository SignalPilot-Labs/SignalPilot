#!/usr/bin/env python3
"""One-time migration: PostgreSQL -> SQLite.

Exports all data from the old improve-pg container and imports it into
the new SQLite database at /data/improve.db (or a local path).

Usage:
    python migrate-pg-to-sqlite.py [--db-path ./improve.db]

Requires: psycopg2-binary (pip install psycopg2-binary)
"""

import argparse
import json
import sqlite3
import sys

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("Install psycopg2-binary first:  pip install psycopg2-binary")
    sys.exit(1)


PG_DSN = "postgresql://improve_admin:Impr0ve!Aud1t@localhost:5610/improve_audit"

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
    diff_stats TEXT
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
    tool_use_id TEXT
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


def json_col(val):
    """Convert a Python dict/list or psycopg2 Json to a JSON string."""
    if val is None:
        return None
    if isinstance(val, str):
        return val
    return json.dumps(val, default=str)


def ts_col(val):
    """Convert a datetime to ISO 8601 string."""
    if val is None:
        return None
    return val.isoformat()


def bool_col(val):
    """Convert boolean to SQLite integer."""
    if val is None:
        return 1
    return 1 if val else 0


def main():
    parser = argparse.ArgumentParser(description="Migrate PostgreSQL to SQLite")
    parser.add_argument("--db-path", default="./improve.db", help="Output SQLite path")
    args = parser.parse_args()

    print(f"Connecting to PostgreSQL at localhost:5610...")
    pg = psycopg2.connect(PG_DSN)
    pg_cur = pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    print(f"Creating SQLite database at {args.db_path}...")
    sl = sqlite3.connect(args.db_path)
    sl.executescript(SCHEMA)
    sl.execute("PRAGMA journal_mode=WAL")
    sl.execute("PRAGMA busy_timeout=5000")

    # --- Migrate runs ---
    pg_cur.execute("SELECT * FROM runs ORDER BY started_at")
    runs = pg_cur.fetchall()
    print(f"Migrating {len(runs)} runs...")
    for r in runs:
        sl.execute(
            """INSERT OR IGNORE INTO runs
            (id, started_at, ended_at, branch_name, status, pr_url,
             total_tool_calls, total_cost_usd, total_input_tokens, total_output_tokens,
             rate_limit_info, error_message, sdk_session_id, custom_prompt,
             duration_minutes, base_branch, rate_limit_resets_at, diff_stats)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                str(r["id"]),
                ts_col(r["started_at"]),
                ts_col(r.get("ended_at")),
                r["branch_name"],
                r["status"],
                r.get("pr_url"),
                r.get("total_tool_calls", 0),
                r.get("total_cost_usd", 0),
                r.get("total_input_tokens", 0),
                r.get("total_output_tokens", 0),
                json_col(r.get("rate_limit_info")),
                r.get("error_message"),
                r.get("sdk_session_id"),
                r.get("custom_prompt"),
                r.get("duration_minutes", 0),
                r.get("base_branch", "main"),
                r.get("rate_limit_resets_at"),
                json_col(r.get("diff_stats")),
            ),
        )
    sl.commit()

    # --- Migrate tool_calls (in batches) ---
    pg_cur.execute("SELECT count(*) as cnt FROM tool_calls")
    total_tc = pg_cur.fetchone()["cnt"]
    print(f"Migrating {total_tc} tool calls...")
    batch_size = 2000
    offset = 0
    while offset < total_tc:
        pg_cur.execute(
            "SELECT * FROM tool_calls ORDER BY id LIMIT %s OFFSET %s",
            (batch_size, offset),
        )
        rows = pg_cur.fetchall()
        if not rows:
            break
        for r in rows:
            sl.execute(
                """INSERT OR IGNORE INTO tool_calls
                (id, run_id, ts, phase, tool_name, input_data, output_data,
                 duration_ms, permitted, deny_reason, agent_role, tool_use_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    r["id"],
                    str(r["run_id"]),
                    ts_col(r["ts"]),
                    r["phase"],
                    r["tool_name"],
                    json_col(r.get("input_data")),
                    json_col(r.get("output_data")),
                    r.get("duration_ms"),
                    bool_col(r.get("permitted", True)),
                    r.get("deny_reason"),
                    r.get("agent_role", "worker"),
                    r.get("tool_use_id"),
                ),
            )
        sl.commit()
        offset += batch_size
        print(f"  ... {min(offset, total_tc)}/{total_tc}")

    # --- Migrate audit_log (in batches) ---
    pg_cur.execute("SELECT count(*) as cnt FROM audit_log")
    total_al = pg_cur.fetchone()["cnt"]
    print(f"Migrating {total_al} audit events...")
    offset = 0
    while offset < total_al:
        pg_cur.execute(
            "SELECT * FROM audit_log ORDER BY id LIMIT %s OFFSET %s",
            (batch_size, offset),
        )
        rows = pg_cur.fetchall()
        if not rows:
            break
        for r in rows:
            sl.execute(
                """INSERT OR IGNORE INTO audit_log
                (id, run_id, ts, event_type, details)
                VALUES (?,?,?,?,?)""",
                (
                    r["id"],
                    str(r["run_id"]),
                    ts_col(r["ts"]),
                    r["event_type"],
                    json_col(r.get("details", {})),
                ),
            )
        sl.commit()
        offset += batch_size
        print(f"  ... {min(offset, total_al)}/{total_al}")

    # --- Migrate control_signals ---
    pg_cur.execute("SELECT * FROM control_signals ORDER BY id")
    signals = pg_cur.fetchall()
    print(f"Migrating {len(signals)} control signals...")
    for r in signals:
        sl.execute(
            """INSERT OR IGNORE INTO control_signals
            (id, run_id, ts, signal, payload, consumed)
            VALUES (?,?,?,?,?,?)""",
            (
                r["id"],
                str(r["run_id"]),
                ts_col(r["ts"]),
                r["signal"],
                r.get("payload"),
                bool_col(r.get("consumed", False)),
            ),
        )
    sl.commit()

    pg_cur.close()
    pg.close()
    sl.close()

    print(f"\nMigration complete! SQLite database at: {args.db_path}")
    print("You can now stop the old postgres container and remove its volume.")


if __name__ == "__main__":
    main()
