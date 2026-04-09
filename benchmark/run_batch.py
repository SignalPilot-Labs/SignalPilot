"""Batch runner for Spider2-DBT benchmark — runs all tasks and reports results."""

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


def get_evaluable_tasks() -> list[str]:
    """Get list of task IDs that have gold DBs with all required tables."""
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


def run_task(instance_id: str, model: str, max_turns: int, timeout: int, no_reset: bool = False) -> tuple[bool, float]:
    """Run a single task. Returns (passed, elapsed_seconds)."""
    env = os.environ.copy()
    env["SPIDER2_DBT_DIR"] = str(SPIDER2_DBT_DIR)

    cmd = [sys.executable, "-m", "benchmark.run_direct", instance_id,
           "--model", model, "--max-turns", str(max_turns)]
    if no_reset:
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
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--max-turns", type=int, default=20)
    parser.add_argument("--timeout", type=int, default=900, help="Timeout per task in seconds")
    parser.add_argument("--tasks", nargs="*", help="Specific task IDs to run")
    parser.add_argument("--skip", nargs="*", default=[], help="Task IDs to skip")
    parser.add_argument("--eval-only", action="store_true", help="Only evaluate existing results")
    parser.add_argument("--results-file", default="/tmp/benchmark_results.json")
    parser.add_argument("--no-reset", action="store_true", help="Don't reset workdir between runs")
    args = parser.parse_args()

    if args.tasks:
        tasks = args.tasks
    else:
        tasks = get_evaluable_tasks()

    tasks = [t for t in tasks if t not in args.skip]
    print(f"Running {len(tasks)} tasks with model={args.model} max_turns={args.max_turns}")

    results: dict[str, dict] = {}
    passed_count = 0
    total = len(tasks)

    for i, task_id in enumerate(sorted(tasks)):
        print(f"\n[{i+1}/{total}] {task_id}...", end=" ", flush=True)

        if args.eval_only:
            # Just evaluate existing workdir
            env = os.environ.copy()
            env["SPIDER2_DBT_DIR"] = str(SPIDER2_DBT_DIR)
            result = subprocess.run(
                [sys.executable, "-m", "benchmark.run_direct", task_id, "--skip-agent"],
                cwd=str(PROJECT_ROOT),
                capture_output=True, text=True, timeout=120, env=env,
            )
            passed = result.returncode == 0
            elapsed = 0.0
        else:
            passed, elapsed = run_task(task_id, args.model, args.max_turns, args.timeout, no_reset=args.no_reset)

        status = "PASS" if passed else "FAIL"
        print(f"{status} ({elapsed:.0f}s)")
        results[task_id] = {"passed": passed, "elapsed": elapsed}
        if passed:
            passed_count += 1

    # Summary
    print(f"\n{'='*60}")
    print(f"RESULTS: {passed_count}/{total} passed ({100*passed_count/total:.1f}%)")
    print(f"{'='*60}")

    # Save results
    with open(args.results_file, "w") as f:
        json.dump({"total": total, "passed": passed_count, "tasks": results}, f, indent=2)
    print(f"Results saved to {args.results_file}")

    # Print failures
    failures = [t for t, r in sorted(results.items()) if not r["passed"]]
    if failures:
        print(f"\nFailed tasks ({len(failures)}):")
        for t in failures:
            print(f"  {t}")


if __name__ == "__main__":
    main()
