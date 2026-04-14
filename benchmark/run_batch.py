"""Batch runner for Spider2 benchmark suites — runs all tasks and reports results."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from .core.audit import (
    ResultAlreadyExistsError,
    RunMetadata,
    TaskResult,
    copy_gateway_audit,
    finalize_run,
    init_run,
    save_task_result,
    save_task_transcript,
)
from .core.logging import close_log_file, log, set_log_file
from .core.paths import AUDIT_BASE
from .core.suite import BenchmarkSuite

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

SPIDER2_DBT_DIR = Path(
    os.environ.get("SPIDER2_DBT_DIR", os.path.expanduser("~/spider2-repo/spider2-dbt"))
)
EVAL_JSONL = SPIDER2_DBT_DIR / "evaluation_suite" / "gold" / "spider2_eval.jsonl"
GOLD_DIR = SPIDER2_DBT_DIR / "evaluation_suite" / "gold"


def get_evaluable_tasks_dbt() -> list[str]:
    """Get list of DBT task IDs that have gold DBs with all required tables."""
    import duckdb as ddb

    tasks = []
    with open(EVAL_JSONL) as f:
        for line in f:
            e = json.loads(line)
            iid = e["instance_id"]
            tabs = e["evaluation"]["parameters"].get("condition_tabs", [])
            gold_dbs = list((GOLD_DIR / iid).glob("*.duckdb")) if (GOLD_DIR / iid).exists() else []
            if not gold_dbs:
                continue
            try:
                con = ddb.connect(str(gold_dbs[0]), read_only=True)
                existing = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
                con.close()
                missing = [t for t in tabs if t not in existing]
                if not missing:
                    tasks.append(iid)
            except Exception:
                pass
    return tasks


def get_evaluable_tasks_sql(suite: str) -> list[str]:
    """Get task IDs for a SQL suite (snowflake or lite).

    For SQL suites gold is CSV-based — no DB introspection needed.
    Returns all instance_ids from the suite's task JSONL.
    """
    load_dotenv(PROJECT_ROOT / ".env")
    env_key = "SPIDER2_SNOWFLAKE_DIR" if suite == "spider2-snowflake" else "SPIDER2_LITE_DIR"
    default_path = os.path.expanduser(
        "~/spider2-repo/spider2-snowflake" if suite == "spider2-snowflake"
        else "~/spider2-repo/spider2-lite"
    )
    data_dir = Path(os.environ.get(env_key, default_path))
    jsonl_name = "spider2-snowflake.jsonl" if suite == "spider2-snowflake" else "spider2-lite.jsonl"
    task_jsonl = data_dir / jsonl_name

    if not task_jsonl.exists():
        print(f"Task JSONL not found: {task_jsonl}", file=sys.stderr)
        return []

    tasks: list[str] = []
    with open(task_jsonl) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            iid = entry.get("instance_id")
            if iid:
                tasks.append(iid)
    return tasks


def get_evaluable_tasks(suite: str) -> list[str]:
    """Dispatch to the correct task-discovery function for the given suite."""
    if suite == "spider2-dbt":
        return get_evaluable_tasks_dbt()
    return get_evaluable_tasks_sql(suite)


def run_task(
    instance_id: str,
    model: str,
    max_turns: int,
    timeout: int,
    suite: str,
    no_reset: bool = False,
) -> tuple[bool, float]:
    """Run a single task via subprocess. Returns (passed, elapsed_seconds)."""
    env = os.environ.copy()
    env["SPIDER2_DBT_DIR"] = str(SPIDER2_DBT_DIR)

    cmd = [
        sys.executable, "-m", "benchmark.run_direct",
        instance_id,
        "--suite", suite,
        "--model", model,
        "--max-turns", str(max_turns),
    ]
    if no_reset and suite == "spider2-dbt":
        cmd.append("--no-reset")

    start = time.monotonic()
    try:
        result = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        elapsed = time.monotonic() - start
        passed = result.returncode == 0
        return passed, elapsed
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - start
        return False, elapsed
    except Exception as e:
        elapsed = time.monotonic() - start
        print(f"  ERROR: {e}")
        return False, elapsed


def _build_task_result(
    instance_id: str,
    run_id: str,
    suite: str,
    model: str,
    passed: bool,
    elapsed: float,
    agent_result: dict,
    timestamps: dict[str, float],
    error: str | None,
) -> TaskResult:
    """Build a TaskResult dataclass from runner output."""
    return TaskResult(
        instance_id=instance_id,
        run_id=run_id,
        suite=suite,
        passed=passed,
        elapsed_seconds=elapsed,
        turns=agent_result.get("turns", 0),
        tool_call_count=len(agent_result.get("tool_calls", [])),
        cost_usd=agent_result.get("cost_usd"),
        usage=agent_result.get("usage"),
        model=model,
        error=error,
        timestamps=timestamps,
        agent_transcript_path=f"traces/{instance_id}.json",
    )


async def run_task_async(
    instance_id: str,
    suite: str,
    model: str,
    max_turns: int,
    no_reset: bool,
    run_id: str,
    semaphore: asyncio.Semaphore,
    eval_only: bool,
) -> TaskResult:
    """Run a single task asynchronously with semaphore-based concurrency limiting.

    Handles per-task log file, audit writes, and transcript saves.
    Catches ResultAlreadyExistsError to support resumable runs.
    """
    # Import here to avoid circular imports at module level
    from .runners.direct import execute_dbt_task
    from .runners.sql_runner import execute_sql_task

    connection_prefix = f"{run_id[:8]}_"

    async with semaphore:
        log_dir = AUDIT_BASE / "runs" / run_id / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_token = set_log_file(log_dir / f"{instance_id}.log")

        timestamps: dict[str, float] = {}
        error: str | None = None
        passed = False
        agent_result: dict = {
            "success": False, "messages": [], "tool_calls": [], "turns": 0, "elapsed": 0.0,
            "cost_usd": None, "usage": None, "started_at": "",
        }
        t_total = time.monotonic()

        try:
            if suite == "spider2-dbt":
                t0 = time.monotonic()
                passed, agent_result = await execute_dbt_task(
                    instance_id=instance_id,
                    model=model,
                    max_turns=max_turns,
                    no_reset=no_reset,
                    connection_prefix=connection_prefix,
                    skip_agent=eval_only,
                )
                timestamps["total"] = time.monotonic() - t0
            else:
                suite_enum = BenchmarkSuite(suite)
                t0 = time.monotonic()
                passed, agent_result = await execute_sql_task(
                    instance_id=instance_id,
                    suite=suite_enum,
                    model=model,
                    max_turns=max_turns if max_turns != 200 else None,
                    connection_prefix=connection_prefix,
                    skip_agent=eval_only,
                )
                timestamps["total"] = time.monotonic() - t0

        except Exception as e:
            error = str(e)
            log(f"Task '{instance_id}' failed with unhandled error: {e}", "ERROR")

        elapsed = time.monotonic() - t_total
        task_result = _build_task_result(
            instance_id=instance_id,
            run_id=run_id,
            suite=suite,
            model=model,
            passed=passed,
            elapsed=elapsed,
            agent_result=agent_result,
            timestamps=timestamps,
            error=error,
        )

        # Save result (immutable — skip if already exists for resumable runs)
        try:
            save_task_result(task_result)
        except ResultAlreadyExistsError:
            log(f"Task '{instance_id}' already has a result — skipping (resume mode)", "WARN")

        # Save transcript
        try:
            save_task_transcript(run_id, instance_id, {
                "tool_calls": agent_result.get("tool_calls", []),
                "messages": agent_result.get("messages", []),
                "turns": agent_result.get("turns", 0),
                "started_at": agent_result.get("started_at", ""),
            })
        except Exception as e:
            log(f"Failed to save transcript for '{instance_id}': {e}", "WARN")

        # Copy gateway audit entries (filter by prefixed connection name)
        try:
            copy_gateway_audit(run_id, instance_id, connection_name=f"{connection_prefix}{instance_id}")
        except Exception as e:
            log(f"Failed to copy gateway audit for '{instance_id}': {e}", "WARN")

        close_log_file(log_token)
        return task_result


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", default="spider2-dbt",
                        choices=["spider2-dbt", "spider2-snowflake", "spider2-lite"],
                        help="Which benchmark suite to run (default: spider2-dbt)")
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--max-turns", type=int, default=200)
    parser.add_argument("--timeout", type=int, default=900, help="Timeout per task in seconds (sequential mode)")
    parser.add_argument("--tasks", nargs="*", help="Specific task IDs to run")
    parser.add_argument("--skip", nargs="*", default=[], help="Task IDs to skip")
    parser.add_argument("--eval-only", action="store_true", help="Only evaluate existing results")
    parser.add_argument("--results-file", default="/tmp/benchmark_results.json")
    parser.add_argument("--no-reset", action="store_true", help="Don't reset workdir between runs (DBT only)")
    parser.add_argument("--parallel", type=int, default=0,
                        help="Concurrency level for parallel mode (0 = sequential/legacy, default)")
    parser.add_argument("--run-id", default=None,
                        help="Explicit run ID (UUID4) for resuming a previous run")
    args = parser.parse_args()

    suite: str = args.suite

    if args.tasks:
        tasks = args.tasks
    else:
        tasks = get_evaluable_tasks(suite)

    tasks = [t for t in tasks if t not in args.skip]
    print(f"Suite: {suite}")
    print(f"Running {len(tasks)} tasks with model={args.model} max_turns={args.max_turns}")

    results: dict[str, dict] = {}
    passed_count = 0
    total = len(tasks)

    if args.parallel > 0:
        _run_parallel(args, suite, tasks, total, results)
        passed_count = sum(1 for r in results.values() if r["passed"])
    else:
        _run_sequential(args, suite, tasks, total, results)
        passed_count = sum(1 for r in results.values() if r["passed"])

    # Summary
    print(f"\n{'='*60}")
    print(f"RESULTS [{suite}]: {passed_count}/{total} passed ({100*passed_count/total:.1f}%)" if total else "No tasks.")
    print(f"{'='*60}")

    # Save results (legacy format)
    with open(args.results_file, "w") as f:
        json.dump({"suite": suite, "total": total, "passed": passed_count, "tasks": results}, f, indent=2)
    print(f"Results saved to {args.results_file}")

    # Print failures
    failures = [t for t, r in sorted(results.items()) if not r["passed"]]
    if failures:
        print(f"\nFailed tasks ({len(failures)}):")
        for t in failures:
            print(f"  {t}")


def _run_sequential(
    args: object,
    suite: str,
    tasks: list[str],
    total: int,
    results: dict[str, dict],
) -> None:
    """Sequential (subprocess-based) execution — original behavior preserved."""
    # We still integrate audit: init_run, save results, finalize_run
    run_metadata: RunMetadata | None = None
    try:
        run_metadata = init_run(
            suite=suite,
            model=getattr(args, "model"),
            concurrency=0,
            task_ids=list(tasks),
        )
        print(f"Audit run ID: {run_metadata.run_id}")
    except Exception as e:
        print(f"WARN: Could not init audit run: {e}", file=sys.stderr)

    for i, task_id in enumerate(sorted(tasks)):
        print(f"\n[{i+1}/{total}] {task_id}...", end=" ", flush=True)

        if getattr(args, "eval_only"):
            env = os.environ.copy()
            env["SPIDER2_DBT_DIR"] = str(SPIDER2_DBT_DIR)
            result = subprocess.run(
                [sys.executable, "-m", "benchmark.run_direct",
                 task_id, "--suite", suite, "--skip-agent"],
                cwd=str(PROJECT_ROOT),
                capture_output=True, text=True, timeout=120, env=env,
            )
            passed = result.returncode == 0
            elapsed = 0.0
        else:
            passed, elapsed = run_task(
                task_id, getattr(args, "model"), getattr(args, "max_turns"),
                getattr(args, "timeout"), suite=suite, no_reset=getattr(args, "no_reset"),
            )

        status = "PASS" if passed else "FAIL"
        print(f"{status} ({elapsed:.0f}s)")
        results[task_id] = {"passed": passed, "elapsed": elapsed}

        if run_metadata is not None:
            try:
                task_result = TaskResult(
                    instance_id=task_id,
                    run_id=run_metadata.run_id,
                    suite=suite,
                    passed=passed,
                    elapsed_seconds=elapsed,
                    turns=0,
                    tool_call_count=0,
                    cost_usd=None,
                    usage=None,
                    model=getattr(args, "model"),
                    error=None,
                    timestamps={},
                    agent_transcript_path=f"traces/{task_id}.json",
                )
                save_task_result(task_result)
            except ResultAlreadyExistsError:
                pass
            except Exception as e:
                print(f"WARN: Could not save task result: {e}", file=sys.stderr)

    if run_metadata is not None:
        passed_count = sum(1 for r in results.values() if r["passed"])
        try:
            finalize_run(run_metadata.run_id, passed_count)
        except Exception as e:
            print(f"WARN: Could not finalize run: {e}", file=sys.stderr)


def _run_parallel(
    args: object,
    suite: str,
    tasks: list[str],
    total: int,
    results: dict[str, dict],
) -> None:
    """Parallel (asyncio-based) execution."""
    concurrency: int = getattr(args, "parallel")
    run_id_arg: str | None = getattr(args, "run_id")

    try:
        run_metadata = init_run(
            suite=suite,
            model=getattr(args, "model"),
            concurrency=concurrency,
            task_ids=list(tasks),
        )
    except Exception as e:
        print(f"ERROR: Could not init audit run: {e}", file=sys.stderr)
        sys.exit(1)

    # If a run_id was provided (resume mode), we'd need to load existing metadata.
    # For now, use the newly created run_id; the --run-id arg is reserved for future resumption.
    if run_id_arg is not None:
        print(f"Note: --run-id {run_id_arg!r} provided but resumption uses the new run_id "
              f"{run_metadata.run_id!r}. Full resume support is a future enhancement.")

    print(f"Audit run ID: {run_metadata.run_id}")
    print(f"Parallel mode: concurrency={concurrency}")

    task_results = asyncio.run(_gather_tasks(
        tasks=sorted(tasks),
        suite=suite,
        model=getattr(args, "model"),
        max_turns=getattr(args, "max_turns"),
        no_reset=getattr(args, "no_reset"),
        run_id=run_metadata.run_id,
        concurrency=concurrency,
        eval_only=getattr(args, "eval_only"),
    ))

    passed_count = 0
    for tr in task_results:
        results[tr.instance_id] = {"passed": tr.passed, "elapsed": tr.elapsed_seconds}
        if tr.passed:
            passed_count += 1
        status = "PASS" if tr.passed else "FAIL"
        print(f"  {tr.instance_id}: {status} ({tr.elapsed_seconds:.0f}s)")

    try:
        finalize_run(run_metadata.run_id, passed_count)
    except Exception as e:
        print(f"WARN: Could not finalize run: {e}", file=sys.stderr)

    print(f"Audit data written to: {AUDIT_BASE / 'runs' / run_metadata.run_id}")


async def _gather_tasks(
    tasks: list[str],
    suite: str,
    model: str,
    max_turns: int,
    no_reset: bool,
    run_id: str,
    concurrency: int,
    eval_only: bool,
) -> list[TaskResult]:
    """Run all tasks concurrently under a semaphore."""
    semaphore = asyncio.Semaphore(concurrency)
    coroutines = [
        run_task_async(
            instance_id=task_id,
            suite=suite,
            model=model,
            max_turns=max_turns,
            no_reset=no_reset,
            run_id=run_id,
            semaphore=semaphore,
            eval_only=eval_only,
        )
        for task_id in tasks
    ]
    return list(await asyncio.gather(*coroutines))


if __name__ == "__main__":
    main()
