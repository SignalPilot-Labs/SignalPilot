"""Round runner — drives one iteration of the self-improvement loop.

For one round:
  1. Compose a sample (fresh + targeted + regression) via sampler
  2. Run all tasks via run_parallel
  3. Evaluate each completed task
  4. Read harness_checks.json for fired-check info
  5. Append per-task records to the registry
  6. Detect regressions (any registered PASS that just FAILed)
  7. Print round summary

Usage:
    python -m benchmark.loop.runner --suite spider2-lite --concurrency 10 \
        --model claude-sonnet-4-6 --n 30
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from ..core.logging import log, log_separator
from ..core.mcp import clear_all_connections
from ..core.suite import BenchmarkSuite, get_suite_config
from ..evaluation.sql_comparator import evaluate_sql
from ..run_parallel import _run_one
from . import registry as reg
from .sampler import sample_round


def _read_fired_checks(work_dir: Path) -> list[str]:
    p = work_dir / "harness_checks.json"
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
        return [f["check"] for f in data.get("failures", [])]
    except Exception:
        return []


async def run_round(
    suite: BenchmarkSuite,
    n_total: int,
    concurrency: int,
    model: str,
    max_turns: int | None,
    note: str | None = None,
) -> dict:
    config = get_suite_config(suite)

    composition = sample_round(suite=suite, n_total=n_total)
    next_round = reg.current_round(reg.load_all())

    log_separator(f"ROUND {next_round}  n={len(composition.all_tasks)}  model={model}")
    log("Composition:")
    for line in composition.summary().splitlines():
        log(line)

    if not composition.all_tasks:
        log("No tasks to run — empty sample. Exiting.", "WARN")
        return {"round": next_round, "n": 0}

    clear_all_connections()
    sem = asyncio.Semaphore(concurrency)
    # force=True so tasks re-execute against the current prompts/skills/checks
    coros = [_run_one(t, suite, model, max_turns, sem, config, force=True) for t in composition.all_tasks]
    results = await asyncio.gather(*coros, return_exceptions=False)

    # Re-evaluate to get authoritative pass/fail (run_one's status uses runtime evaluator)
    summary: dict[str, int] = {"PASS": 0, "FAIL": 0, "ERROR": 0, "SKIP": 0}
    for r in results:
        tid = r["instance_id"]
        rt_status = r["status"]  # PASS / FAIL / ERROR / SKIP
        work_dir = config.work_dir / tid
        if rt_status == "PASS" or rt_status == "FAIL":
            try:
                passed, _ = evaluate_sql(work_dir, tid, config)
                final_status = "PASS" if passed else "FAIL"
            except Exception:
                final_status = "FAIL"
        else:
            final_status = rt_status
        summary[final_status] = summary.get(final_status, 0) + 1

        record = reg.TaskRecord(
            round=next_round,
            task=tid,
            status=final_status,
            elapsed_s=r.get("elapsed"),
            cost_usd=r.get("cost_usd"),
            fired_checks=_read_fired_checks(work_dir),
        )
        reg.append_record(record)

    # Regression detection
    new_records = reg.load_all()
    regs = reg.regressions(new_records)
    regs_this_round = [r for r in regs if r[2] == next_round]

    log_separator(f"ROUND {next_round} SUMMARY")
    pass_rate = summary["PASS"] / max(1, sum(summary.values()) - summary["SKIP"])
    log(f"  PASS={summary['PASS']}  FAIL={summary['FAIL']}  ERROR={summary['ERROR']}  SKIP={summary['SKIP']}")
    log(f"  Pass rate (excl. SKIP): {pass_rate*100:.1f}%")
    if regs_this_round:
        log(f"  REGRESSIONS this round ({len(regs_this_round)}):", "WARN")
        for task, was_pass, now_fail in regs_this_round:
            log(f"    {task}: passed in round {was_pass}, failed in round {now_fail}", "WARN")
    else:
        log("  No regressions this round.")

    if note:
        # Persist a note alongside the registry for context on what changed this round
        notes_path = config.work_dir.parent.parent / "results" / "round_notes.jsonl"
        notes_path.parent.mkdir(parents=True, exist_ok=True)
        with notes_path.open("a") as f:
            f.write(json.dumps({"round": next_round, "note": note, "model": model}) + "\n")

    return {
        "round": next_round,
        "n": len(composition.all_tasks),
        "summary": summary,
        "pass_rate": pass_rate,
        "regressions": regs_this_round,
        "composition": {
            "fresh": composition.fresh,
            "targeted": composition.targeted,
            "regression": composition.regression,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one round of the self-improvement loop.")
    parser.add_argument("--suite", default="spider2-lite", choices=["spider2-lite", "spider2-snowflake"])
    parser.add_argument("--n", type=int, default=30, help="Total tasks per round (default 30)")
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--max-turns", type=int, default=None)
    parser.add_argument("--note", default=None, help="Note to record for this round (what changed)")
    args = parser.parse_args()

    suite = BenchmarkSuite(args.suite)
    result = asyncio.run(run_round(
        suite=suite,
        n_total=args.n,
        concurrency=args.concurrency,
        model=args.model,
        max_turns=args.max_turns,
        note=args.note,
    ))
    sys.exit(0 if result.get("summary", {}).get("ERROR", 0) == 0 else 1)


if __name__ == "__main__":
    main()
