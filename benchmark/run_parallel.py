"""Parallel runner for spider2-lite tasks.

Launches N tasks concurrently using execute_sql_task, with unique connection prefixes
so registrations don't collide. Skips any task that already has result.csv in its workdir
(idempotent / resumable).

Usage:
    python -m benchmark.run_parallel --concurrency 4 --model claude-opus-4-7 \
        local156 local021 local168 local344 local272 local029 local193 local065 local061 local358
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

from .core.logging import log, log_separator
from .core.mcp import clear_all_connections
from .core.suite import BenchmarkSuite, get_suite_config
from .runners.sql_runner import execute_sql_task


async def _run_one(
    instance_id: str,
    suite: BenchmarkSuite,
    model: str,
    max_turns: int | None,
    semaphore: asyncio.Semaphore,
    config,
    force: bool = False,
) -> dict:
    """Run a single task respecting the semaphore.

    force=True deletes any existing result.csv/result.sql before running, so the
    task is re-evaluated against the current prompts/skills (used by the
    self-improvement loop). force=False preserves resume semantics for
    crash recovery.
    """
    work_dir = config.work_dir / instance_id

    if force:
        for f in ("result.csv", "result.sql", "harness_checks.json", "agent_output.json"):
            (work_dir / f).unlink(missing_ok=True)

    if (work_dir / "result.csv").exists():
        log(f"[{instance_id}] result.csv already present — skipping (resume mode)")
        return {"instance_id": instance_id, "status": "SKIP", "elapsed": 0.0, "cost_usd": None, "turns": 0}

    async with semaphore:
        start = time.monotonic()
        # Short, unique prefix to avoid connection-name collisions across concurrent tasks.
        prefix = f"p{uuid.uuid4().hex[:6]}_"
        log_separator(f"START {instance_id}  prefix={prefix}")
        try:
            passed, agent_result = await execute_sql_task(
                instance_id=instance_id,
                suite=suite,
                model=model,
                max_turns=max_turns,
                connection_prefix=prefix,
            )
            status = "PASS" if passed else "FAIL"
        except Exception as e:
            log(f"[{instance_id}] EXCEPTION: {e}", "ERROR")
            status = "ERROR"
            agent_result = {"cost_usd": None, "turns": 0, "elapsed": 0.0}

        elapsed = time.monotonic() - start
        log_separator(f"END {instance_id}  status={status}  elapsed={elapsed:.1f}s  cost={agent_result.get('cost_usd')}")
        return {
            "instance_id": instance_id,
            "status": status,
            "elapsed": elapsed,
            "cost_usd": agent_result.get("cost_usd"),
            "turns": agent_result.get("turns", 0),
        }


async def _amain() -> None:
    parser = argparse.ArgumentParser(description="Parallel runner for spider2-lite.")
    parser.add_argument("instance_ids", nargs="+")
    parser.add_argument("--suite", default="spider2-lite", choices=["spider2-lite", "spider2-snowflake"])
    parser.add_argument("--model", default="claude-opus-4-7")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--max-turns", type=int, default=None)
    parser.add_argument("--summary-out", help="Write per-task summary JSONL here")
    args = parser.parse_args()

    suite = BenchmarkSuite(args.suite)
    config = get_suite_config(suite)

    clear_all_connections()

    sem = asyncio.Semaphore(args.concurrency)
    coros = [_run_one(t, suite, args.model, args.max_turns, sem, config) for t in args.instance_ids]
    results = await asyncio.gather(*coros, return_exceptions=False)

    # Summary
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    errored = sum(1 for r in results if r["status"] == "ERROR")
    skipped = sum(1 for r in results if r["status"] == "SKIP")
    total_cost = sum((r["cost_usd"] or 0.0) for r in results)

    print("\n" + "=" * 60)
    print(f"  Tasks: {len(results)}  PASS={passed}  FAIL={failed}  ERROR={errored}  SKIP={skipped}")
    print(f"  Total cost: ${total_cost:.2f}")
    print("=" * 60)
    for r in results:
        cost = f"${r['cost_usd']:.2f}" if r['cost_usd'] else "    "
        print(f"  {r['instance_id']:<12}  {r['status']:<6}  turns={r['turns']:<3}  {cost}  {r['elapsed']:.1f}s")

    if args.summary_out:
        Path(args.summary_out).write_text("\n".join(json.dumps(r) for r in results) + "\n")

    sys.exit(0 if failed == 0 and errored == 0 else 1)


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
