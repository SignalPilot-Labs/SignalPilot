"""Calibrate harness checks against known PASS/FAIL labels.

Runs every check in CHECK_REGISTRY against every completed task in a workdir,
then computes precision (% of fires that landed on FAIL tasks) and recall
(% of FAIL tasks each check caught). This is the foundation for the
self-improvement loop — a check with low precision is a false-positive
generator and shouldn't gate anything until refined.

Usage:
    python -m benchmark.calibrate_checks --suite spider2-lite
    python -m benchmark.calibrate_checks --suite spider2-lite --tasks-file benchmark/results/lite-strat50/tasks.txt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from .checks import CHECK_REGISTRY
from .core.suite import BenchmarkSuite, get_suite_config
from .core.tasks import load_task_for_suite
from .evaluation.sql_comparator import evaluate_sql


def calibrate(suite: BenchmarkSuite, task_ids: list[str] | None = None) -> dict:
    config = get_suite_config(suite)

    if task_ids is None:
        task_ids = sorted(p.name for p in config.work_dir.iterdir() if p.is_dir())

    rows: list[dict] = []
    for tid in task_ids:
        work_dir = config.work_dir / tid
        result_csv = work_dir / "result.csv"
        if not result_csv.exists():
            continue
        try:
            task = load_task_for_suite(tid, config)
            question = task.get("instruction") or task.get("question") or ""
        except Exception:
            question = ""
        try:
            df = pd.read_csv(result_csv)
        except Exception:
            continue
        sql = (work_dir / "result.sql").read_text() if (work_dir / "result.sql").exists() else ""

        try:
            passed, _ = evaluate_sql(work_dir, tid, config)
        except Exception:
            passed = None

        row: dict = {"instance_id": tid, "passed": passed}
        for name, (fn, _enabled) in CHECK_REGISTRY.items():
            try:
                result = fn(question, sql, df)
                row[f"check_{name}"] = 1 if result is not None else 0
            except Exception:
                row[f"check_{name}"] = -1  # crashed
        rows.append(row)

    by_check: dict[str, dict] = {}
    n_fail = sum(1 for r in rows if r["passed"] is False)
    n_pass = sum(1 for r in rows if r["passed"] is True)

    for name in CHECK_REGISTRY:
        col = f"check_{name}"
        fired = [r for r in rows if r.get(col) == 1]
        fired_on_fail = sum(1 for r in fired if r["passed"] is False)
        fired_on_pass = sum(1 for r in fired if r["passed"] is True)
        precision = (fired_on_fail / len(fired)) if fired else None
        recall = (fired_on_fail / n_fail) if n_fail else None
        by_check[name] = {
            "n_fired": len(fired),
            "fired_on_fail": fired_on_fail,
            "fired_on_pass": fired_on_pass,
            "precision": precision,
            "recall": recall,
        }

    return {
        "n_tasks": len(rows),
        "n_pass": n_pass,
        "n_fail": n_fail,
        "by_check": by_check,
        "rows": rows,
    }


def _fmt_pct(x: float | None) -> str:
    return f"{x*100:5.1f}%" if x is not None else "  n/a"


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate Layer-1 checks against known labels.")
    parser.add_argument("--suite", default="spider2-lite", choices=["spider2-lite", "spider2-snowflake"])
    parser.add_argument("--tasks-file", help="File with one instance_id per line (default: all completed tasks)")
    args = parser.parse_args()

    task_ids: list[str] | None = None
    if args.tasks_file:
        task_ids = [t.strip() for t in Path(args.tasks_file).read_text().split() if t.strip()]

    suite = BenchmarkSuite(args.suite)
    result = calibrate(suite, task_ids)

    print(f"\nCalibrated against {result['n_tasks']} tasks  (PASS={result['n_pass']}  FAIL={result['n_fail']})")
    print()
    print(f"  {'check':<28} {'fired':>6} {'on_fail':>8} {'on_pass':>8} {'precision':>10} {'recall':>10}")
    print("  " + "-" * 76)
    for name, stats in sorted(result["by_check"].items(), key=lambda kv: -(kv[1]["precision"] or 0)):
        print(
            f"  {name:<28} "
            f"{stats['n_fired']:>6} "
            f"{stats['fired_on_fail']:>8} "
            f"{stats['fired_on_pass']:>8} "
            f"{_fmt_pct(stats['precision']):>10} "
            f"{_fmt_pct(stats['recall']):>10}"
        )
    print()
    print("Precision = % of fires on FAIL tasks (high = useful gate; low = false-positive risk)")
    print("Recall    = % of FAIL tasks this check caught (high = comprehensive)")


if __name__ == "__main__":
    main()
