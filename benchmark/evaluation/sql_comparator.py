"""CSV-based evaluator for spider2-snowflake and spider2-lite benchmark suites.

Imports _official_compare from comparator.py (same vector-matching logic as DBT eval).
Does NOT modify comparator.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ..core.logging import log
from ..core.suite import BenchmarkSuite
from ..core.tasks import load_eval_config_for_suite
from .comparator import _official_compare

if TYPE_CHECKING:
    from ..core.suite import SuiteConfig


def evaluate_sql(work_dir: Path, instance_id: str, config: "SuiteConfig") -> tuple[bool, str]:
    """Evaluate a SQL suite task by comparing result.csv against the gold CSV(s).

    Spider2 supports multiple acceptable answers ({id}_a.csv, {id}_b.csv, etc.).
    If any gold variant matches, the task passes.

    Returns (passed: bool, details: str).
    """
    import pandas as pd

    result_csv = work_dir / "result.csv"
    if not result_csv.exists():
        msg = f"result.csv not found in {work_dir} — agent did not save output"
        log(msg, "ERROR")
        return False, msg

    # ── Load eval config for comparison parameters ─────────────────────────────
    eval_entry = load_eval_config_for_suite(instance_id, config)
    condition_cols: list[int] = []
    ignore_order: bool = True  # default: order-insensitive for SQL results

    if eval_entry:
        params = eval_entry.get("evaluation", {}).get("parameters", {})
        raw_cols = params.get("condition_cols")
        if isinstance(raw_cols, list) and raw_cols:
            first = raw_cols[0]
            condition_cols = first if isinstance(first, list) else raw_cols
        raw_order = params.get("ignore_orders")
        if isinstance(raw_order, list) and raw_order:
            ignore_order = bool(raw_order[0])
        elif isinstance(raw_order, bool):
            ignore_order = raw_order

    # ── Load prediction ────────────────────────────────────────────────────────
    try:
        pred_df = pd.read_csv(result_csv)
    except Exception as e:
        msg = f"Failed to read result.csv: {e}"
        log(msg, "ERROR")
        return False, msg

    # ── Find all gold CSV variants ────────────────────────────────────────────
    gold_csvs = _find_all_gold_csvs(instance_id, config)
    if not gold_csvs:
        msg = f"Gold CSV not found for {instance_id} (looked in {config.gold_dir})"
        log(msg, "ERROR")
        return False, msg

    log(f"Result CSV: {result_csv} (shape: {pred_df.shape})")
    log(f"Gold CSVs:  {[str(g) for g in gold_csvs]}")

    # ── Try each gold variant — pass if any matches ──────────────────────────
    last_fail = ""
    for gold_csv in gold_csvs:
        try:
            gold_df = pd.read_csv(gold_csv)
        except Exception as e:
            log(f"Failed to read gold CSV {gold_csv}: {e}", "WARN")
            continue

        gold_sub = gold_df.iloc[:, condition_cols] if condition_cols else gold_df
        if len(gold_sub) != len(pred_df):
            last_fail = (
                f"row count mismatch vs {gold_csv.name}: gold={len(gold_sub)} pred={len(pred_df)}"
            )
            continue

        try:
            match, failed_col = _official_compare(pred_df, gold_df, condition_cols, ignore_order)
        except Exception as e:
            last_fail = f"comparison error vs {gold_csv.name}: {e}"
            continue

        if match:
            msg = f"PASS (matched {gold_csv.name})"
            log(msg)
            return True, msg

        last_fail = f"no pred column matched gold column '{failed_col}' in {gold_csv.name}"

    msg = f"FAIL — {last_fail}"
    log(msg)
    return False, msg


def _find_all_gold_csvs(instance_id: str, config: "SuiteConfig") -> list[Path]:
    """Find all gold CSV variants for an instance ({id}.csv, {id}_a.csv, {id}_b.csv, ...)."""
    import re
    exec_result = config.gold_dir / "exec_result"
    if not exec_result.is_dir():
        # Fallback to gold_dir directly
        exec_result = config.gold_dir

    pattern = re.compile(rf"^{re.escape(instance_id)}(_[a-z])?\.csv$")
    matches = sorted(f for f in exec_result.iterdir() if pattern.match(f.name))
    return matches


def _find_gold_csv(instance_id: str, config: "SuiteConfig") -> Path | None:
    """Locate the gold CSV file for an instance.

    spider2-lite: gold_dir/exec_result/{instance_id}.csv
    spider2-snowflake: gold_dir/{instance_id}/<any>.csv or gold_dir/{instance_id}.csv
    """
    if config.suite == BenchmarkSuite.LITE:
        exec_result = config.gold_dir / "exec_result"
        candidate = exec_result / f"{instance_id}.csv"
        if candidate.exists():
            return candidate
        # Fallback: {id}_a.csv (primary answer variant)
        candidate_a = exec_result / f"{instance_id}_a.csv"
        if candidate_a.exists():
            return candidate_a
        # Fallback: check direct gold_dir
        candidate2 = config.gold_dir / f"{instance_id}.csv"
        return candidate2 if candidate2.exists() else candidate  # return even if missing for error msg

    if config.suite == BenchmarkSuite.SNOWFLAKE:
        exec_result = config.gold_dir / "exec_result"
        # Spider2-Snow gold CSVs: exec_result/{id}.csv or exec_result/{id}_a.csv
        candidate = exec_result / f"{instance_id}.csv"
        if candidate.exists():
            return candidate
        # Fallback: {id}_a.csv (primary answer variant)
        candidate_a = exec_result / f"{instance_id}_a.csv"
        if candidate_a.exists():
            return candidate_a
        # Fallback: subdirectory
        subdir = config.gold_dir / instance_id
        if subdir.is_dir():
            csv_files = list(subdir.glob("*.csv"))
            if csv_files:
                return csv_files[0]
        return candidate  # return for error message

    return None
