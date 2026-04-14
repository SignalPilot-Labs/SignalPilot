"""Batch runner for Spider2 benchmark suites — runs all tasks and reports results."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

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
    """Run a single task. Returns (passed, elapsed_seconds)."""
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


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", default="spider2-dbt",
                        choices=["spider2-dbt", "spider2-snowflake", "spider2-lite"],
                        help="Which benchmark suite to run (default: spider2-dbt)")
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--max-turns", type=int, default=200)
    parser.add_argument("--timeout", type=int, default=900, help="Timeout per task in seconds")
    parser.add_argument("--tasks", nargs="*", help="Specific task IDs to run")
    parser.add_argument("--skip", nargs="*", default=[], help="Task IDs to skip")
    parser.add_argument("--eval-only", action="store_true", help="Only evaluate existing results")
    parser.add_argument("--results-file", default="/tmp/benchmark_results.json")
    parser.add_argument("--no-reset", action="store_true", help="Don't reset workdir between runs (DBT only)")
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

    for i, task_id in enumerate(sorted(tasks)):
        print(f"\n[{i+1}/{total}] {task_id}...", end=" ", flush=True)

        if args.eval_only:
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
                task_id, args.model, args.max_turns, args.timeout,
                suite=suite, no_reset=args.no_reset,
            )

        status = "PASS" if passed else "FAIL"
        print(f"{status} ({elapsed:.0f}s)")
        results[task_id] = {"passed": passed, "elapsed": elapsed}
        if passed:
            passed_count += 1

    # Summary
    print(f"\n{'='*60}")
    print(f"RESULTS [{suite}]: {passed_count}/{total} passed ({100*passed_count/total:.1f}%)")
    print(f"{'='*60}")

    # Save results
    with open(args.results_file, "w") as f:
        json.dump({"suite": suite, "total": total, "passed": passed_count, "tasks": results}, f, indent=2)
    print(f"Results saved to {args.results_file}")

    # Print failures
    failures = [t for t, r in sorted(results.items()) if not r["passed"]]
    if failures:
        print(f"\nFailed tasks ({len(failures)}):")
        for t in failures:
            print(f"  {t}")


if __name__ == "__main__":
    main()
