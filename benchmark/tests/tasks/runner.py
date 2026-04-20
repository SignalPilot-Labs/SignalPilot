"""Test task runner for the self-contained benchmark test suite.

Runs all 5 synthetic test tasks without invoking the agent — writes known-correct
result.csv/duckdb files to verify the full evaluation pipeline works end-to-end.

Usage:
    python -m benchmark.tests.tasks.runner
"""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path
from typing import NamedTuple

from ...core.logging import log, log_separator
from ...core.mcp import (
    delete_local_connection,
    register_bigquery_connection,
    register_local_connection,
    register_snowflake_connection,
    register_sqlite_connection,
)
from ...core.suite import BenchmarkSuite, DBBackend, SuiteConfig, TEST_TASKS_DIR, get_test_suite_config
from ...core.tasks import load_task_for_suite
from ...core.workdir import prepare_sql_workdir, prepare_workdir, write_claude_md, write_sql_claude_md
from ...evaluation.comparator import evaluate
from ...evaluation.sql_comparator import evaluate_sql

# ── Constants ────────────────────────────────────────────────────────────────

SQLITE_DB_DIR = TEST_TASKS_DIR / "sqlite_dbs"

# All test tasks: (instance_id, suite)
TEST_TASK_SPECS: list[tuple[str, BenchmarkSuite]] = [
    ("test_sf_current_date", BenchmarkSuite.SNOWFLAKE),
    ("test_dbt_simple001", BenchmarkSuite.DBT),
    ("test_lite_sqlite001", BenchmarkSuite.LITE),
    ("test_lite_sf001", BenchmarkSuite.LITE),
    ("test_lite_bq001", BenchmarkSuite.LITE),
]


class TaskResult(NamedTuple):
    instance_id: str
    suite: str
    backend: str
    passed: bool
    details: str
    elapsed: float


def _run_sql_task(
    instance_id: str,
    config: SuiteConfig,
) -> TaskResult:
    """Run a single SQL task (snowflake or lite) end-to-end."""
    t0 = time.monotonic()
    suite_label = config.suite.value

    log_separator(f"SQL Task: {instance_id} ({suite_label})")

    # 1. Load task
    task = load_task_for_suite(instance_id, config)
    instruction: str = task["instruction"]
    task_type: str = task.get("type", "snowflake")
    log(f"Loaded task: {instance_id}, type={task_type}")

    # 2. Prepare workdir
    work_dir = prepare_sql_workdir(
        instance_id, config, task, sqlite_db_dir=SQLITE_DB_DIR
    )
    log(f"Workdir: {work_dir}")

    # 3. Determine backend and connection name
    backend_label = task_type

    # 4. Write CLAUDE.md
    backend_map: dict[str, DBBackend] = {
        "sqlite": DBBackend.SQLITE,
        "snowflake": DBBackend.SNOWFLAKE,
        "bigquery": DBBackend.BIGQUERY,
    }
    if config.suite == BenchmarkSuite.SNOWFLAKE:
        db_backend = DBBackend.SNOWFLAKE
        backend_label = "snowflake"
    else:
        db_backend = backend_map.get(task_type, DBBackend.SQLITE)

    write_sql_claude_md(work_dir, instance_id, instruction, db_backend, connection_name=instance_id)

    # 5. Register MCP connection
    conn_ok = _register_sql_connection(instance_id, db_backend, task, work_dir)
    if not conn_ok:
        log(f"Connection registration failed for {instance_id}", "WARN")

    # 6. Write known-correct result.csv (skip agent)
    _write_correct_result_csv(instance_id, config, work_dir)

    # 7. Assert workdir contents
    _assert_sql_workdir(instance_id, db_backend, work_dir, task)

    # 8. Clean up connection
    delete_local_connection(instance_id)

    # 9. Evaluate
    passed, details = evaluate_sql(work_dir, instance_id, config)

    elapsed = time.monotonic() - t0
    status = "PASS" if passed else "FAIL"
    log(f"{instance_id}: {status} in {elapsed:.2f}s — {details[:80]}")
    return TaskResult(instance_id, suite_label, backend_label, passed, details, elapsed)


def _run_dbt_task(
    instance_id: str,
    config: SuiteConfig,
) -> TaskResult:
    """Run a single dbt task end-to-end."""
    t0 = time.monotonic()
    suite_label = config.suite.value

    log_separator(f"DBT Task: {instance_id} ({suite_label})")

    # 1. Load task
    task = load_task_for_suite(instance_id, config)
    instruction: str = task["instruction"]
    log(f"Loaded task: {instance_id}")

    # 2. Prepare workdir (copy dbt project from config.data_dir/instance_id)
    work_dir = prepare_workdir(instance_id, data_dir=config.data_dir)
    log(f"Workdir: {work_dir}")

    # 3. Write CLAUDE.md
    write_claude_md(work_dir, instance_id, instruction)

    # 4. Register DuckDB connection
    duckdb_files = list(work_dir.glob("*.duckdb"))
    if duckdb_files:
        db_path = str(duckdb_files[0])
        conn_ok = register_local_connection(instance_id, db_path)
        if not conn_ok:
            log(f"DuckDB connection registration failed for {instance_id}", "WARN")
    else:
        log(f"No DuckDB file found in {work_dir} — skipping connection registration", "WARN")

    # 5. Assert workdir contents
    _assert_dbt_workdir(instance_id, work_dir)

    # 6. Write known-correct dbt output (skip agent)
    _write_correct_dbt_result(instance_id, config, work_dir)

    # 7. Clean up connection
    delete_local_connection(instance_id)

    # 8. Evaluate
    passed, details = evaluate(work_dir, instance_id, config)

    elapsed = time.monotonic() - t0
    status = "PASS" if passed else "FAIL"
    log(f"{instance_id}: {status} in {elapsed:.2f}s — {details[:80]}")
    return TaskResult(instance_id, suite_label, "duckdb", passed, details, elapsed)


def _register_sql_connection(
    instance_id: str,
    backend: DBBackend,
    task: dict,
    work_dir: Path,
) -> bool:
    """Register appropriate connection for the given backend."""
    if backend == DBBackend.SNOWFLAKE:
        database: str = task.get("db", task.get("database", ""))
        schema: str = task.get("schema", task.get("schema_name", "PUBLIC"))
        return register_snowflake_connection(instance_id, database, schema)

    if backend == DBBackend.SQLITE:
        db_id: str = task.get("db_id", "")
        db_path = str(work_dir / f"{db_id}.sqlite") if db_id else str(work_dir)
        return register_sqlite_connection(instance_id, db_path)

    if backend == DBBackend.BIGQUERY:
        project: str = task.get("project_id", task.get("project", ""))
        dataset: str = task.get("dataset", task.get("schema", ""))
        return register_bigquery_connection(instance_id, project, dataset)

    log(f"Unsupported backend '{backend}' for connection registration", "WARN")
    return False


def _write_correct_result_csv(
    instance_id: str,
    config: SuiteConfig,
    work_dir: Path,
) -> None:
    """Copy the gold CSV to result.csv to simulate a correct agent answer."""
    from ...evaluation.sql_comparator import _find_gold_csv

    gold_csv = _find_gold_csv(instance_id, config)
    if gold_csv is None or not gold_csv.exists():
        log(f"Gold CSV not found for {instance_id} — cannot write correct result", "ERROR")
        raise FileNotFoundError(f"Gold CSV missing for {instance_id}: {gold_csv}")

    result_csv = work_dir / "result.csv"
    shutil.copy2(gold_csv, result_csv)
    log(f"Wrote correct result.csv for {instance_id} (copied from gold)")


def _write_correct_dbt_result(
    instance_id: str,
    config: SuiteConfig,
    work_dir: Path,
) -> None:
    """Copy the gold DuckDB into the workdir to simulate correct dbt output."""
    from ...core.tasks import load_eval_config_for_suite

    eval_entry = load_eval_config_for_suite(instance_id, config)
    if not eval_entry:
        raise ValueError(f"No eval config found for dbt task {instance_id}")

    gold_db_name: str = eval_entry["evaluation"]["parameters"]["gold"]
    gold_db_path = config.gold_dir / instance_id / gold_db_name
    if not gold_db_path.exists():
        raise FileNotFoundError(f"Gold DuckDB not found: {gold_db_path}")

    result_db_path = work_dir / gold_db_name
    shutil.copy2(gold_db_path, result_db_path)
    log(f"Wrote correct dbt result DuckDB for {instance_id} (copied from gold)")


def _assert_sql_workdir(
    instance_id: str,
    backend: DBBackend,
    work_dir: Path,
    task: dict,
) -> None:
    """Assert key files exist in SQL workdir after preparation."""
    claude_md = work_dir / "CLAUDE.md"
    if not claude_md.exists():
        raise AssertionError(f"CLAUDE.md missing in workdir for {instance_id}: {work_dir}")
    log("  Assert OK: CLAUDE.md exists")

    if backend == DBBackend.SQLITE:
        db_id: str = task.get("db_id", "")
        if db_id:
            sqlite_file = work_dir / f"{db_id}.sqlite"
            if not sqlite_file.exists():
                raise AssertionError(f"SQLite DB missing in workdir for {instance_id}: {sqlite_file}")
            log(f"  Assert OK: {db_id}.sqlite exists in workdir")


def _assert_dbt_workdir(instance_id: str, work_dir: Path) -> None:
    """Assert key dbt project files exist in workdir after preparation."""
    for path in [work_dir / "dbt_project.yml", work_dir / "models"]:
        if not path.exists():
            raise AssertionError(f"DBT project file missing in workdir for {instance_id}: {path}")
        log(f"  Assert OK: {path.name} exists in workdir")


def _print_results_table(results: list[TaskResult]) -> None:
    """Print a formatted results table."""
    print("\n" + "=" * 80)
    print("TEST TASK RESULTS")
    print("=" * 80)
    header = f"{'Task ID':<28} {'Suite':<20} {'Backend':<12} {'Result':<8} {'Time':>8}"
    print(header)
    print("-" * 80)
    passed_count = 0
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        print(f"{r.instance_id:<28} {r.suite:<20} {r.backend:<12} {status:<8} {r.elapsed:>7.2f}s")
        if r.passed:
            passed_count += 1
    print("-" * 80)
    print(f"  {passed_count}/{len(results)} tasks passed")
    print("=" * 80)


def main() -> None:
    """Run all 5 test tasks and print a results table."""
    log_separator("Test Task Suite Runner")
    results: list[TaskResult] = []

    for instance_id, suite in TEST_TASK_SPECS:
        config = get_test_suite_config(suite)
        try:
            if suite == BenchmarkSuite.DBT:
                result = _run_dbt_task(instance_id, config)
            else:
                result = _run_sql_task(instance_id, config)
        except Exception as exc:
            import traceback
            log(f"EXCEPTION in {instance_id}: {exc}", "ERROR")
            traceback.print_exc()
            result = TaskResult(
                instance_id=instance_id,
                suite=suite.value,
                backend="unknown",
                passed=False,
                details=str(exc),
                elapsed=0.0,
            )
        results.append(result)

    _print_results_table(results)
    failed = [r for r in results if not r.passed]
    if failed:
        print(f"\nFailed tasks: {[r.instance_id for r in failed]}")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
