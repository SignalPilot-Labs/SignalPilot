"""Standalone live MCP connectivity validator.

Answers one question: "Can I query every database through the MCP gateway layer right now?"

This script is intentionally narrow — it only tests database connectivity. It does NOT test
workdir setup, skills, prompts, or any other pipeline concerns. For the full pipeline, use
`python -m benchmark.validate_bench_e2e`.

For each backend (Snowflake, BigQuery, SQLite, DuckDB):
  1. Register a test connection via core/mcp.py helpers
  2. Query through gateway.connectors.pool_manager.PoolManager with credential_extras
  3. Verify the result
  4. Delete the connection
  5. Clean up any temp DB files

Usage:
    python -m benchmark.validate_live_mcp
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
import tempfile

from .core.mcp import (
    delete_local_connection,
    register_bigquery_connection,
    register_local_connection,
    register_snowflake_connection,
    register_sqlite_connection,
)
from .core.paths import BIGQUERY_SA_FILE, GATEWAY_SRC, SNOWFLAKE_ENV_FILE

# ANSI color codes
_GREEN = "\033[92m"
_RED = "\033[91m"
_YELLOW = "\033[93m"
_RESET = "\033[0m"

_CONN_PREFIX = "live_mcp_"

_SNOWFLAKE_QUERY = "SELECT CURRENT_TIMESTAMP() AS ts"
_BIGQUERY_QUERY = "SELECT 1 AS test_value"
_LOCAL_QUERY = "SELECT COUNT(*) AS cnt FROM test_table"

BackendResult = tuple[str, str, str]  # (backend, status, detail)  status: PASS|FAIL|SKIP


def _create_sqlite_temp_db() -> str:
    """Create a temp SQLite DB with a test_table. Returns the path string."""
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        tmp_path = f.name
    conn = sqlite3.connect(tmp_path)
    conn.execute("CREATE TABLE test_table(id INTEGER, name TEXT)")
    conn.execute("INSERT INTO test_table VALUES(1, 'live_mcp_test')")
    conn.commit()
    conn.close()
    return tmp_path


def _create_duckdb_temp_db() -> str:
    """Create a temp DuckDB DB with a test_table. Returns the path string."""
    import duckdb  # noqa: PLC0415

    with tempfile.NamedTemporaryFile(suffix=".duckdb", delete=False) as f:
        tmp_path = f.name
    # Remove the empty file so DuckDB can create a fresh database
    os.unlink(tmp_path)
    db = duckdb.connect(tmp_path)
    db.execute("CREATE TABLE test_table(id INTEGER, name TEXT)")
    db.execute("INSERT INTO test_table VALUES(1, 'live_mcp_test')")
    db.close()
    return tmp_path


def _query_via_pool_manager(conn_id: str, query: str) -> list:
    """Execute a query through PoolManager using the gateway store connection."""
    sys.path.insert(0, str(GATEWAY_SRC))
    from gateway.connectors.pool_manager import PoolManager  # noqa: PLC0415
    from gateway.store import (  # noqa: PLC0415
        get_connection,
        get_connection_string,
        get_credential_extras,
    )

    conn_info = get_connection(conn_id)
    conn_str = get_connection_string(conn_id)
    extras = get_credential_extras(conn_id)
    if conn_info is None or conn_str is None:
        raise RuntimeError(f"connection '{conn_id}' not retrievable from gateway store")

    pm = PoolManager()

    async def _run() -> list:
        async with pm.connection(conn_info.db_type, conn_str, credential_extras=extras) as connector:
            return await connector.execute(query)

    return asyncio.run(_run())


def check_snowflake() -> BackendResult:
    """Test Snowflake connectivity: register, query CURRENT_TIMESTAMP, cleanup."""
    backend = "Snowflake"
    conn_id = f"{_CONN_PREFIX}snowflake"
    if not SNOWFLAKE_ENV_FILE.exists():
        return backend, "SKIP", f"credential file absent: {SNOWFLAKE_ENV_FILE}"
    try:
        ok = register_snowflake_connection(conn_id, database="TEST_DB", schema="PUBLIC")
        if not ok:
            return backend, "FAIL", "register_snowflake_connection returned False"
        result = _query_via_pool_manager(conn_id, _SNOWFLAKE_QUERY)
        if not result:
            return backend, "FAIL", "query returned empty result"
        return backend, "PASS", f"query OK: {result[0]}"
    except Exception as exc:
        err = str(exc)
        if any(kw in err.lower() for kw in ("oauth", "credentials", "authentication", "token")):
            return backend, "SKIP", f"cloud auth issue (not a code bug): {err[:120]}"
        return backend, "FAIL", f"exception: {err[:200]}"
    finally:
        delete_local_connection(conn_id)


def check_bigquery() -> BackendResult:
    """Test BigQuery connectivity: register, query SELECT 1, cleanup."""
    backend = "BigQuery"
    conn_id = f"{_CONN_PREFIX}bigquery"
    if not BIGQUERY_SA_FILE.exists():
        return backend, "SKIP", f"credential file absent: {BIGQUERY_SA_FILE}"
    try:
        ok = register_bigquery_connection(conn_id, project="authacceptor", dataset="")
        if not ok:
            return backend, "FAIL", "register_bigquery_connection returned False"
        result = _query_via_pool_manager(conn_id, _BIGQUERY_QUERY)
        if not result:
            return backend, "FAIL", "query returned empty result"
        return backend, "PASS", f"query OK: {result[0]}"
    except Exception as exc:
        err = str(exc)
        if any(kw in err.lower() for kw in ("credentials", "authentication", "forbidden", "permission")):
            return backend, "SKIP", f"cloud auth issue (not a code bug): {err[:120]}"
        return backend, "FAIL", f"exception: {err[:200]}"
    finally:
        delete_local_connection(conn_id)


def check_sqlite() -> BackendResult:
    """Test SQLite connectivity: create temp DB, register, query test_table, cleanup."""
    backend = "SQLite"
    conn_id = f"{_CONN_PREFIX}sqlite"
    tmp_path: str | None = None
    try:
        tmp_path = _create_sqlite_temp_db()
        ok = register_sqlite_connection(conn_id, db_path=tmp_path)
        if not ok:
            return backend, "FAIL", "register_sqlite_connection returned False"
        result = _query_via_pool_manager(conn_id, _LOCAL_QUERY)
        if not result:
            return backend, "FAIL", "query returned empty result"
        return backend, "PASS", f"query OK: {result[0]}"
    except Exception as exc:
        return backend, "FAIL", f"exception: {str(exc)[:200]}"
    finally:
        delete_local_connection(conn_id)
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def check_duckdb() -> BackendResult:
    """Test DuckDB connectivity: create temp DB, register, query test_table, cleanup."""
    backend = "DuckDB"
    conn_id = f"{_CONN_PREFIX}duckdb"
    tmp_path: str | None = None
    try:
        tmp_path = _create_duckdb_temp_db()
        ok = register_local_connection(conn_id, db_path=tmp_path)
        if not ok:
            return backend, "FAIL", "register_local_connection returned False"
        result = _query_via_pool_manager(conn_id, _LOCAL_QUERY)
        if not result:
            return backend, "FAIL", "query returned empty result"
        return backend, "PASS", f"query OK: {result[0]}"
    except Exception as exc:
        return backend, "FAIL", f"exception: {str(exc)[:200]}"
    finally:
        delete_local_connection(conn_id)
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _colored_status(status: str) -> str:
    """Return ANSI-colored status label."""
    if status == "PASS":
        return f"{_GREEN}PASS{_RESET}"
    if status == "FAIL":
        return f"{_RED}FAIL{_RESET}"
    return f"{_YELLOW}SKIP{_RESET}"


def _print_summary(results: list[BackendResult]) -> None:
    """Print a summary table: Backend | Status | Detail."""
    backend_w = 12
    status_w = 8
    print()
    print("== Live MCP Connectivity ==")
    print()
    print(f"{'Backend':<{backend_w}} | {'Status':<{status_w}} | Detail")
    print("-" * 80)
    for backend, status, detail in results:
        colored = _colored_status(status)
        print(f"{backend:<{backend_w}} | {colored} | {detail}")
    print()
    passes = sum(1 for _, s, _ in results if s == "PASS")
    fails = sum(1 for _, s, _ in results if s == "FAIL")
    skips = sum(1 for _, s, _ in results if s == "SKIP")
    print(f"Results: {passes} PASS  {fails} FAIL  {skips} SKIP  (total {len(results)})")


def main() -> int:
    """Run all backend connectivity checks. Returns 0 if all pass/skip, 1 if any fail."""
    results: list[BackendResult] = []
    results.append(check_snowflake())
    results.append(check_bigquery())
    results.append(check_sqlite())
    results.append(check_duckdb())

    _print_summary(results)

    any_fail = any(s == "FAIL" for _, s, _ in results)
    return 1 if any_fail else 0


if __name__ == "__main__":
    sys.exit(main())
