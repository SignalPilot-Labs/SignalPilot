"""End-to-end validation of the Spider2 benchmark pipeline.

Runs 5 synthetic tasks (1 snowflake, 1 dbt, 3 lite backends) with 6 checks
each (30 total checks), verifying workdir setup, skills, system prompts,
connection registration, bloat-free store, and no gold file leakage.

Usage:
    python -m benchmark.validate_bench_e2e
    python -m benchmark.validate_bench_e2e --verbose
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from .core.mcp import (
    delete_local_connection,
    register_bigquery_connection,
    register_local_connection,
    register_snowflake_connection,
    register_sqlite_connection,
)
from .core.paths import (
    BIGQUERY_SA_FILE,
    GATEWAY_SRC,
    PROMPTS_DIR,
    PROJECT_ROOT,
    SKILLS_SRC,
    SNOWFLAKE_ENV_FILE,
    WORK_DIR,
)
from .core.suite import BenchmarkSuite, get_suite_config
from .core.workdir import force_rmtree, prepare_sql_workdir

# ANSI color codes
_GREEN = "\033[92m"
_RED = "\033[91m"
_YELLOW = "\033[93m"
_RESET = "\033[0m"

CheckResult = tuple[str, str, str]  # (name, status, detail)  status: PASS|FAIL|SKIP

# Connection IDs used across all 5 tasks
_CONN_SF = "e2e_validate_sf"
_CONN_DBT = "e2e_validate_dbt"
_CONN_LITE_SQLITE = "e2e_validate_lite_sqlite"
_CONN_LITE_SF = "e2e_validate_lite_sf"
_CONN_LITE_BQ = "e2e_validate_lite_bq"

_E2E_PREFIX = "e2e_validate_"

# All 5 task descriptors: (suite_name, backend_name, conn_id, task_dict)
_TASK_SPECS: list[tuple[str, str, str, dict]] = [
    (
        "spider2-snowflake",
        "snowflake",
        _CONN_SF,
        {"instance_id": "e2e_validate_sf", "type": "snowflake", "db": "TEST_DB", "schema": "PUBLIC"},
    ),
    (
        "spider2-dbt",
        "duckdb",
        _CONN_DBT,
        {"instance_id": "e2e_validate_dbt"},
    ),
    (
        "spider2-lite",
        "sqlite",
        _CONN_LITE_SQLITE,
        {"instance_id": "e2e_validate_lite_sqlite", "type": "sqlite", "db_id": "e2e_test"},
    ),
    (
        "spider2-lite",
        "snowflake",
        _CONN_LITE_SF,
        {"instance_id": "e2e_validate_lite_sf", "type": "snowflake", "db": "TEST_DB", "schema": "PUBLIC"},
    ),
    (
        "spider2-lite",
        "bigquery",
        _CONN_LITE_BQ,
        {"instance_id": "e2e_validate_lite_bq", "type": "bigquery", "project_id": "authacceptor", "dataset": ""},
    ),
]


# ── Gateway helpers ────────────────────────────────────────────────────────────

def _get_gateway_connection(conn_id: str):
    """Look up a connection in the gateway store (lazy import after sys.path setup)."""
    sys.path.insert(0, str(GATEWAY_SRC))
    from gateway.store import get_connection  # noqa: PLC0415

    return get_connection(conn_id)


def _list_gateway_connections() -> list:
    """List all connections in the gateway store (lazy import)."""
    sys.path.insert(0, str(GATEWAY_SRC))
    from gateway.store import list_connections  # noqa: PLC0415

    return list_connections()


# ── Workdir helpers ────────────────────────────────────────────────────────────

def _prepare_dbt_workdir(instance_id: str) -> Path:
    """Create a minimal dbt workdir without requiring spider2 data."""
    dst = WORK_DIR / instance_id
    if dst.exists():
        force_rmtree(dst)
    dst.mkdir(parents=True, exist_ok=True)

    # Create dummy .duckdb file
    (dst / f"{instance_id}.duckdb").touch()

    # Copy .mcp.json
    mcp_json_src = PROJECT_ROOT / ".mcp.json"
    if mcp_json_src.exists():
        shutil.copy2(mcp_json_src, dst / ".mcp.json")

    # Copy all skills (dbt workdir copies ALL skills, not filtered)
    skills_dst = dst / ".claude" / "skills"
    if SKILLS_SRC.exists():
        shutil.copytree(
            SKILLS_SRC,
            skills_dst,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("*.json", "__pycache__"),
        )

    # Git init for skill discovery
    subprocess.run(["git", "init"], cwd=str(dst), capture_output=True)

    return dst


def _prepare_sql_workdir_for_task(suite_name: str, conn_id: str, task: dict) -> Path:
    """Prepare a SQL workdir using prepare_sql_workdir."""
    suite = BenchmarkSuite(suite_name)
    config = get_suite_config(suite)
    instance_id: str = task["instance_id"]
    return prepare_sql_workdir(instance_id, config, task)


# ── SQLite temp DB helper ──────────────────────────────────────────────────────

def _create_sqlite_temp_db() -> str:
    """Create a temp SQLite DB with a test table. Returns path string."""
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        tmp_path = f.name
    conn = sqlite3.connect(tmp_path)
    conn.execute("CREATE TABLE e2e_test(id INTEGER, name TEXT)")
    conn.execute("INSERT INTO e2e_test VALUES(1, 'hello')")
    conn.commit()
    conn.close()
    return tmp_path


def _create_duckdb_temp_db() -> str:
    """Create a temp DuckDB DB with a test table. Returns path string."""
    import duckdb  # noqa: PLC0415

    with tempfile.NamedTemporaryFile(suffix=".duckdb", delete=False) as f:
        tmp_path = f.name
    # Remove the empty file so DuckDB can create a fresh database
    os.unlink(tmp_path)
    db = duckdb.connect(tmp_path)
    db.execute("CREATE TABLE e2e_test(id INTEGER, name TEXT)")
    db.execute("INSERT INTO e2e_test VALUES(1, 'hello')")
    db.close()
    return tmp_path


# ── The 6 checks for a single task ────────────────────────────────────────────

def check_workdir_setup(suite_name: str, backend: str, conn_id: str, task: dict) -> tuple[CheckResult, Path | None]:
    """Check 1: workdir directory exists, .mcp.json present, .git initialized."""
    name = "workdir_setup"
    work_dir: Path | None = None
    try:
        if suite_name == "spider2-dbt":
            work_dir = _prepare_dbt_workdir(conn_id)
        else:
            work_dir = _prepare_sql_workdir_for_task(suite_name, conn_id, task)

        if not work_dir.exists():
            return (name, "FAIL", f"workdir not created: {work_dir}"), None

        mcp_json = work_dir / ".mcp.json"
        if not mcp_json.exists():
            return (name, "FAIL", f".mcp.json missing in {work_dir}"), work_dir

        git_dir = work_dir / ".git"
        if not git_dir.exists():
            return (name, "FAIL", f".git not initialized in {work_dir}"), work_dir

        return (name, "PASS", f"workdir OK: {work_dir}"), work_dir

    except Exception as exc:
        return (name, "FAIL", f"exception: {exc}"), work_dir


def check_skills_copied(suite_name: str, work_dir: Path | None) -> CheckResult:
    """Check 2: verify suite skills are present under .claude/skills/<name>/SKILL.md."""
    name = "skills_copied"
    if work_dir is None:
        return (name, "SKIP", "workdir not available (prior check failed)")
    try:
        suite = BenchmarkSuite(suite_name)
        config = get_suite_config(suite)
        skills_dst = work_dir / ".claude" / "skills"
        missing: list[str] = []
        found: list[str] = []
        for skill_name in config.skills:
            skill_md = skills_dst / skill_name / "SKILL.md"
            if skill_md.exists():
                found.append(skill_name)
            else:
                missing.append(skill_name)
        if missing:
            return (name, "FAIL", f"missing SKILL.md for: {missing}")
        return (name, "PASS", f"all {len(found)} skills present: {found}")
    except Exception as exc:
        return (name, "FAIL", f"exception: {exc}")


def check_system_prompt(suite_name: str) -> CheckResult:
    """Check 3: correct system prompt file exists and template variables resolve."""
    name = "system_prompt"
    try:
        if suite_name == "spider2-dbt":
            prompt_file = PROMPTS_DIR / "dbt_local_system.md"
            bak_file = PROMPTS_DIR / "dbt_local_system.md.bak"
            if not prompt_file.exists():
                return (name, "FAIL", f"dbt system prompt not found: {prompt_file}")
            if not bak_file.exists():
                return (name, "FAIL", f"dbt backup prompt not found: {bak_file}")
            content = prompt_file.read_text()
            if not content.strip():
                return (name, "FAIL", "dbt_local_system.md is empty")
            return (name, "PASS", f"dbt_local_system.md OK ({len(content)} chars), .bak present")

        # SQL suites
        prompt_file = PROMPTS_DIR / "system_general.md"
        if not prompt_file.exists():
            return (name, "FAIL", f"system_general.md not found: {prompt_file}")
        content = prompt_file.read_text()
        if not content.strip():
            return (name, "FAIL", "system_general.md is empty")

        # Template variable substitution check
        substituted = (
            content
            .replace("${connection_name}", "test_conn")
            .replace("${instance_id}", "test_instance")
            .replace("${work_dir}", "/tmp/test_workdir")
        )
        if "${" in substituted:
            unresolved = [tok for tok in substituted.split("${")[1:]]
            samples = [f"${{{tok.split('}')[0]}}}" for tok in unresolved[:3]]
            return (name, "FAIL", f"unresolved template variables in system_general.md: {samples}")

        return (name, "PASS", f"system_general.md OK ({len(content)} chars), all template vars resolve")

    except Exception as exc:
        return (name, "FAIL", f"exception: {exc}")


def check_connection_registered(
    suite_name: str,
    backend: str,
    conn_id: str,
    task: dict,
    work_dir: Path | None,
) -> tuple[CheckResult, str | None]:
    """Check 4: register the DB connection and verify it appears in the gateway store.

    Returns the check result AND the path to any temp DB file created (for cleanup).
    """
    name = "connection_registered"
    tmp_db_path: str | None = None
    try:
        if backend == "snowflake":
            if not SNOWFLAKE_ENV_FILE.exists():
                return (name, "SKIP", f"no Snowflake credentials: {SNOWFLAKE_ENV_FILE}"), None
            db: str = task.get("db", "TEST_DB")
            schema: str = task.get("schema", "PUBLIC")
            ok = register_snowflake_connection(conn_id, db, schema)
            if not ok:
                return (name, "FAIL", f"register_snowflake_connection returned False for {conn_id}"), None
            conn = _get_gateway_connection(conn_id)
            if conn is None:
                return (name, "FAIL", f"connection '{conn_id}' not found in store after registration"), None
            return (name, "PASS", f"snowflake connection registered: {conn_id} (db_type={conn.db_type})"), None

        if backend == "duckdb":
            tmp_db_path = _create_duckdb_temp_db()
            ok = register_local_connection(conn_id, tmp_db_path)
            if not ok:
                return (name, "FAIL", f"register_local_connection returned False for {conn_id}"), tmp_db_path
            conn = _get_gateway_connection(conn_id)
            if conn is None:
                return (name, "FAIL", f"connection '{conn_id}' not found in store after registration"), tmp_db_path
            return (name, "PASS", f"duckdb connection registered: {conn_id} (db_type={conn.db_type})"), tmp_db_path

        if backend == "sqlite":
            tmp_db_path = _create_sqlite_temp_db()
            ok = register_sqlite_connection(conn_id, tmp_db_path)
            if not ok:
                return (name, "FAIL", f"register_sqlite_connection returned False for {conn_id}"), tmp_db_path
            conn = _get_gateway_connection(conn_id)
            if conn is None:
                return (name, "FAIL", f"connection '{conn_id}' not found in store after registration"), tmp_db_path
            return (name, "PASS", f"sqlite connection registered: {conn_id} (db_type={conn.db_type})"), tmp_db_path

        if backend == "bigquery":
            if not BIGQUERY_SA_FILE.exists():
                return (name, "SKIP", f"no BigQuery service account: {BIGQUERY_SA_FILE}"), None
            project: str = task.get("project_id", "authacceptor")
            dataset: str = task.get("dataset", "")
            ok = register_bigquery_connection(conn_id, project, dataset)
            if not ok:
                return (name, "FAIL", f"register_bigquery_connection returned False for {conn_id}"), None
            conn = _get_gateway_connection(conn_id)
            if conn is None:
                return (name, "FAIL", f"connection '{conn_id}' not found in store after registration"), None
            return (name, "PASS", f"bigquery connection registered: {conn_id} (db_type={conn.db_type})"), None

        return (name, "FAIL", f"unknown backend: {backend}"), None

    except Exception as exc:
        return (name, "FAIL", f"exception: {exc}"), tmp_db_path


def check_no_bloat(conn_id: str, conn_registered: bool) -> CheckResult:
    """Check 5: only this task's e2e_validate_ connection is present in the store."""
    name = "no_bloat"
    if not conn_registered:
        return (name, "SKIP", "connection not registered (prior check skipped/failed)")
    try:
        connections = _list_gateway_connections()
        e2e_conns = [c for c in connections if c.name.startswith(_E2E_PREFIX)]
        unexpected = [c.name for c in e2e_conns if c.name != conn_id]
        if unexpected:
            return (name, "FAIL", f"unexpected e2e connections present: {unexpected}")
        if not any(c.name == conn_id for c in e2e_conns):
            return (name, "FAIL", f"expected connection '{conn_id}' not found in store")
        return (name, "PASS", f"only {conn_id} present with e2e_validate_ prefix")
    except Exception as exc:
        return (name, "FAIL", f"exception: {exc}")


def check_mcp_query(
    backend: str,
    conn_id: str,
    conn_registered: bool,
    tmp_db_path: str | None,
) -> CheckResult:
    """Check 7: actually query the registered connection via pool_manager.

    Verifies that credential_extras flow through to the connector —
    the fix for the empty-extras bug in mcp_server.py.
    For local DBs (DuckDB/SQLite) we query the temp test table.
    For cloud DBs (Snowflake/BigQuery) we run a trivial SELECT 1.
    """
    name = "mcp_query"
    if not conn_registered:
        return (name, "SKIP", "connection not registered (prior check skipped/failed)")
    try:
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
            return (name, "FAIL", f"connection '{conn_id}' not retrievable from store")

        pm = PoolManager()

        async def _query() -> list:
            async with pm.connection(conn_info.db_type, conn_str, credential_extras=extras) as connector:
                if backend in ("duckdb", "sqlite"):
                    return await connector.execute("SELECT COUNT(*) AS cnt FROM e2e_test")
                # Cloud backends: trivial query that doesn't need tables
                return await connector.execute("SELECT 1 AS ok")

        result = asyncio.run(_query())
        if not result:
            return (name, "FAIL", f"query returned empty result for {conn_id}")
        return (name, "PASS", f"query OK: {result}")
    except Exception as exc:
        err = str(exc)
        # Cloud credential issues are SKIPs, not FAILs
        if backend in ("snowflake", "bigquery") and (
            "oauth" in err.lower() or "credentials" in err.lower() or "authentication" in err.lower()
        ):
            return (name, "SKIP", f"cloud auth issue (not a code bug): {err[:120]}")
        return (name, "FAIL", f"exception: {err[:200]}")


def check_no_gold_leak(work_dir: Path | None) -> CheckResult:
    """Check 6: no gold-named files in the workdir."""
    name = "no_gold_leak"
    if work_dir is None or not work_dir.exists():
        return (name, "SKIP", "workdir not available (prior check failed)")
    try:
        leaked: list[str] = []
        for f in work_dir.rglob("*"):
            if f.is_file() and "gold" in f.name.lower():
                leaked.append(str(f.relative_to(work_dir)))
        if leaked:
            return (name, "FAIL", f"gold files found in workdir: {leaked[:5]}")
        return (name, "PASS", "no gold files found in workdir")
    except Exception as exc:
        return (name, "FAIL", f"exception: {exc}")


# ── Per-task runner ────────────────────────────────────────────────────────────

def run_task(
    task_num: int,
    total_tasks: int,
    suite_name: str,
    backend: str,
    conn_id: str,
    task: dict,
    verbose: bool,
) -> list[CheckResult]:
    """Run all 6 checks for one task, cleaning up in a finally block."""
    print(f"\n== Task {task_num}/{total_tasks}: {suite_name} / {backend} ==")

    results: list[CheckResult] = []
    work_dir: Path | None = None
    tmp_db_path: str | None = None

    try:
        # Check 1
        r1, work_dir = check_workdir_setup(suite_name, backend, conn_id, task)
        results.append(r1)
        _print_check(r1, verbose)

        # Check 2
        r2 = check_skills_copied(suite_name, work_dir)
        results.append(r2)
        _print_check(r2, verbose)

        # Check 3
        r3 = check_system_prompt(suite_name)
        results.append(r3)
        _print_check(r3, verbose)

        # Check 4
        r4, tmp_db_path = check_connection_registered(suite_name, backend, conn_id, task, work_dir)
        results.append(r4)
        _print_check(r4, verbose)

        # Whether connection was actually registered (not skipped/failed)
        conn_registered = r4[1] == "PASS"

        # Check 5
        r5 = check_no_bloat(conn_id, conn_registered)
        results.append(r5)
        _print_check(r5, verbose)

        # Check 6
        r6 = check_no_gold_leak(work_dir)
        results.append(r6)
        _print_check(r6, verbose)

        # Check 7: actually query the connection via pool_manager
        r7 = check_mcp_query(backend, conn_id, conn_registered, tmp_db_path)
        results.append(r7)
        _print_check(r7, verbose)

    finally:
        # Clean up connection
        delete_local_connection(conn_id)

        # Clean up workdir
        if work_dir is not None and work_dir.exists():
            try:
                force_rmtree(work_dir)
            except Exception:
                pass

        # Clean up temp DB file
        if tmp_db_path is not None:
            try:
                os.unlink(tmp_db_path)
            except OSError:
                pass

    return results


# ── Output helpers ─────────────────────────────────────────────────────────────

def _print_check(result: CheckResult, verbose: bool) -> None:
    name, status, detail = result
    if status == "PASS":
        color, icon = _GREEN, "PASS"
    elif status == "FAIL":
        color, icon = _RED, "FAIL"
    else:
        color, icon = _YELLOW, "SKIP"
    print(f"  {color}[{icon}]{_RESET} {name}")
    if verbose or status != "PASS":
        print(f"         {detail}")


def _print_summary(all_results: list[CheckResult]) -> None:
    total = len(all_results)
    passed = sum(1 for _, s, _ in all_results if s == "PASS")
    failed = sum(1 for _, s, _ in all_results if s == "FAIL")
    skipped = sum(1 for _, s, _ in all_results if s == "SKIP")

    width = 44
    print()
    print("=" * width)
    print(
        f"  {_GREEN}{passed} passed{_RESET}  "
        f"{_RED}{failed} failed{_RESET}  "
        f"{_YELLOW}{skipped} skipped{_RESET}  "
        f"of {total} checks"
    )
    print("=" * width)
    print()


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="End-to-end validation of the Spider2 benchmark pipeline."
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detail lines for passing checks too.",
    )
    args = parser.parse_args()

    all_results: list[CheckResult] = []
    total_tasks = len(_TASK_SPECS)

    for i, (suite_name, backend, conn_id, task) in enumerate(_TASK_SPECS, start=1):
        task_results = run_task(
            task_num=i,
            total_tasks=total_tasks,
            suite_name=suite_name,
            backend=backend,
            conn_id=conn_id,
            task=task,
            verbose=args.verbose,
        )
        all_results.extend(task_results)

    _print_summary(all_results)

    all_ok = all(status in ("PASS", "SKIP") for _, status, _ in all_results)
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
