"""Seed the registry with results from runs that predate the loop infrastructure.

Reads each task's workdir + harness_checks.json (if present) + evaluator output,
and appends a row to the registry under round=0 (historical baseline).

Usage:
    python -m benchmark.loop.seed_registry --suite spider2-lite \
        --tasks-file benchmark/results/lite-strat50/tasks.txt
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from ..core.logging import log
from ..core.suite import BenchmarkSuite, get_suite_config
from ..evaluation.sql_comparator import evaluate_sql
from . import registry as reg


def _fired_checks_for(work_dir: Path, question: str, sql: str) -> list[str]:
    p = work_dir / "harness_checks.json"
    if p.exists():
        try:
            data = json.loads(p.read_text())
            return [f["check"] for f in data.get("failures", [])]
        except Exception:
            pass
    # Fallback: run checks in-process so we backfill the field
    try:
        from ..checks import run_all_checks
        df = pd.read_csv(work_dir / "result.csv")
        return [cf.check_name for cf in run_all_checks(question, sql, df)]
    except Exception:
        return []


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed registry from existing workdirs.")
    parser.add_argument("--suite", default="spider2-lite", choices=["spider2-lite", "spider2-snowflake"])
    parser.add_argument("--tasks-file", required=True)
    parser.add_argument("--round", type=int, default=0, help="Round number to record under (default 0)")
    args = parser.parse_args()

    suite = BenchmarkSuite(args.suite)
    config = get_suite_config(suite)
    task_ids = [t.strip() for t in Path(args.tasks_file).read_text().split() if t.strip()]

    from ..core.tasks import load_task_for_suite

    n_seeded = 0
    for tid in task_ids:
        work_dir = config.work_dir / tid
        if not (work_dir / "result.csv").exists():
            continue
        try:
            task = load_task_for_suite(tid, config)
            question = task.get("instruction") or task.get("question") or ""
        except Exception:
            question = ""
        sql = (work_dir / "result.sql").read_text() if (work_dir / "result.sql").exists() else ""
        try:
            passed, _ = evaluate_sql(work_dir, tid, config)
            status = "PASS" if passed else "FAIL"
        except Exception:
            status = "ERROR"
        fired = _fired_checks_for(work_dir, question, sql)

        record = reg.TaskRecord(
            round=args.round,
            task=tid,
            status=status,
            fired_checks=fired,
        )
        reg.append_record(record)
        n_seeded += 1

    log(f"Seeded {n_seeded} records into registry under round={args.round}")


if __name__ == "__main__":
    main()
