"""Capture table evidence for a write task.

Capture only tables that the task must build or modify.
Complete capture before branch cleanup. A capture failure must not block branch cleanup.

The ``fingerprint`` mode records table statistics and a grain check in JSON.
The ``fingerprint+sample`` mode also writes a bounded, deterministic sample to DuckDB.
The ``full`` mode writes the complete table to DuckDB and rejects output above the byte limit.
"""

from __future__ import annotations

import logging
import os
import tempfile
from typing import Any

from .grading import quote_table

logger = logging.getLogger(__name__)

# These limits prevent a manifest from exhausting worker memory or disk space.
MAX_SAMPLE_ROWS = 50_000
MAX_CAPTURE_FILE_BYTES = 128 * 1024 * 1024

_INSERT_BATCH_ROWS = 5_000

_NUMERIC_TYPES = {
    "smallint",
    "integer",
    "bigint",
    "numeric",
    "real",
    "double precision",
}


async def _connect(dsn: str):
    import asyncpg

    return await asyncpg.connect(dsn=dsn, timeout=30)


def _info_schema_filter(table: str) -> tuple[str, str]:
    parts = table.split(".")
    if len(parts) == 3:
        parts = parts[1:]
    if len(parts) == 2:
        return parts[0], parts[1]
    return "", parts[0]


async def fingerprint_table(conn, table: str, grain: list[str]) -> dict[str, Any]:
    tsql = quote_table(table)
    schema, name = _info_schema_filter(table)
    where = "table_name = $1" + (" AND table_schema = $2" if schema else "")
    args = [name] + ([schema] if schema else [])
    cols = await conn.fetch(
        f"SELECT column_name, data_type FROM information_schema.columns WHERE {where} ORDER BY ordinal_position",
        *args,
    )
    if not cols:
        return {"table": table, "exists": False}

    row_count = await conn.fetchval(f"SELECT count(*) FROM {tsql}")

    per_column: dict[str, Any] = {}
    for c in cols:
        col, dtype = c["column_name"], c["data_type"]
        entry: dict[str, Any] = {"type": dtype}
        try:
            entry["nulls"] = await conn.fetchval(f'SELECT count(*) FROM {tsql} WHERE "{col}" IS NULL')
            if dtype in _NUMERIC_TYPES:
                val = await conn.fetchval(f'SELECT sum("{col}"::numeric) FROM {tsql}')
                entry["sum"] = float(val) if val is not None else None
        except Exception as exc:
            entry["error"] = str(exc)[:120]
        per_column[col] = entry

    out: dict[str, Any] = {
        "table": table,
        "exists": True,
        "row_count": int(row_count or 0),
        "columns": per_column,
    }

    if grain:
        cols_sql = ", ".join(f'"{g}"' for g in grain)
        try:
            distinct = await conn.fetchval(f"SELECT count(*) FROM (SELECT DISTINCT {cols_sql} FROM {tsql}) d")
            out["grain"] = {
                "key": grain,
                "distinct": int(distinct or 0),
                "unique": int(distinct or 0) == int(row_count or 0),
            }
        except Exception as exc:
            out["grain"] = {"key": grain, "error": str(exc)[:200]}
    return out


async def _estimated_bytes(conn, table: str) -> int:
    schema, name = _info_schema_filter(table)
    regclass = f"{schema}.{name}" if schema else name
    try:
        return int(await conn.fetchval("SELECT pg_total_relation_size($1::regclass)", regclass))
    except Exception:
        return 0


async def _stream_rows(conn, sql: str, batch_size: int = _INSERT_BATCH_ROWS):
    """Yield row batches through a server-side cursor.

    The small default batch size supports dump-path tests without a PostgreSQL server.
    """
    batch: list[Any] = []
    async with conn.transaction():
        async for row in conn.cursor(sql):
            batch.append(row)
            if len(batch) >= batch_size:
                yield batch
                batch = []
    if batch:
        yield batch


async def _dump_to_duckdb(
    conn, table: str, limit: int | None, *, max_file_bytes: int
) -> tuple[bytes | None, str | None]:
    """Write rows in deterministic order to a DuckDB file and return its bytes.

    Read PostgreSQL rows in batches and check the file size after each batch.
    Return ``(data, None)`` on success.
    Return ``(None, reason)`` when the file exceeds ``max_file_bytes``.
    """
    import duckdb

    tsql = quote_table(table)
    schema, name = _info_schema_filter(table)
    col_rows = await conn.fetch(
        "SELECT column_name FROM information_schema.columns WHERE table_name = $1 "
        + ("AND table_schema = $2 " if schema else "")
        + "ORDER BY ordinal_position",
        *([name, schema] if schema else [name]),
    )
    columns = [r["column_name"] for r in col_rows]
    order = ", ".join(f'"{c}"' for c in columns)
    sql = f"SELECT * FROM {tsql} ORDER BY {order}"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"

    fd, path = tempfile.mkstemp(suffix=".duckdb")
    os.close(fd)
    os.unlink(path)  # duckdb wants to create it
    try:
        oversized = False
        rows_written = 0
        ddb = duckdb.connect(path)
        try:
            col_defs = ", ".join(f'"{c}" VARCHAR' for c in columns)
            ddb.execute(f"CREATE TABLE capture ({col_defs})")
            placeholders = ", ".join("?" for _ in columns)
            async for batch in _stream_rows(conn, sql):
                if limit is not None and rows_written + len(batch) > limit:
                    batch = batch[: limit - rows_written]
                if batch:
                    data = [[None if v is None else str(v) for v in row] for row in batch]
                    # The statement contains generated placeholders. Row values use parameters.
                    ddb.executemany(
                        f"INSERT INTO capture VALUES ({placeholders})",  # nosec B608
                        data,
                    )
                    rows_written += len(batch)
                ddb.execute("CHECKPOINT")
                if os.path.getsize(path) > max_file_bytes:
                    oversized = True
                    break
                if limit is not None and rows_written >= limit:
                    break
        finally:
            ddb.close()

        size = os.path.getsize(path)
        if oversized or size > max_file_bytes:
            return None, (
                f"capture file reached {size} bytes on disk, over the {max_file_bytes}-byte ceiling — fingerprint only"
            )
        with open(path, "rb") as f:
            return f.read(), None
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


async def capture_tables(
    dsn: str,
    spec: dict[str, Any],
    *,
    grain: list[str] | None = None,
    byte_budget: int,
    full_max_bytes: int,
) -> tuple[dict[str, Any], list[tuple[str, bytes]]]:
    """Run the capture spec against the task branch.

    Returns (result summary for the task row, [(filename, bytes), ...] for S3).
    Degrades rather than fails: an over-budget sample/full drops to
    fingerprint-only and says so in the summary (spec §3.4c: truncated capture
    is logged, never silent).
    """
    mode = spec.get("mode", "fingerprint")
    requested_rows = int(spec.get("sample_rows", 10_000))
    sample_rows = min(requested_rows, MAX_SAMPLE_ROWS)
    tables = list(spec.get("tables") or [])

    summary: dict[str, Any] = {"mode": mode, "tables": {}, "bytes": 0}
    if requested_rows > MAX_SAMPLE_ROWS:
        summary["sample_clamped"] = True
    files: list[tuple[str, bytes]] = []
    remaining = byte_budget

    conn = await _connect(dsn)
    try:
        for table in tables:
            entry: dict[str, Any] = {}
            try:
                entry["fingerprint"] = await fingerprint_table(conn, table, grain or [])
            except Exception as exc:
                entry["error"] = str(exc)[:300]
                summary["tables"][table] = entry
                continue

            if mode in ("fingerprint+sample", "full") and entry["fingerprint"].get("exists"):
                try:
                    # Never build a file bigger than the hard ceiling or what
                    # is left of the caller's byte budget.
                    ceiling = min(MAX_CAPTURE_FILE_BYTES, max(remaining, 0))
                    if mode == "full":
                        est = await _estimated_bytes(conn, table)
                        if est > full_max_bytes:
                            entry["capture_refused"] = (
                                f"full capture refused: ~{est} bytes exceeds the {full_max_bytes}-byte ceiling"
                            )
                            summary["tables"][table] = entry
                            continue
                        data, truncated = await _dump_to_duckdb(conn, table, None, max_file_bytes=ceiling)
                    else:
                        data, truncated = await _dump_to_duckdb(conn, table, sample_rows, max_file_bytes=ceiling)
                    if data is None:
                        entry["capture_truncated"] = truncated or (
                            "capture file over the byte ceiling — fingerprint only"
                        )
                    elif len(data) > remaining:
                        entry["capture_truncated"] = (
                            f"artifact budget exhausted ({len(data)} bytes needed, {remaining} left) — fingerprint only"
                        )
                    else:
                        fname = f"{table.replace('.', '_')}.duckdb"
                        files.append((fname, data))
                        entry["file"] = fname
                        entry["file_bytes"] = len(data)
                        remaining -= len(data)
                        summary["bytes"] += len(data)
                except Exception as exc:
                    entry["capture_error"] = str(exc)[:300]
            summary["tables"][table] = entry
    finally:
        await conn.close()
    return summary, files
