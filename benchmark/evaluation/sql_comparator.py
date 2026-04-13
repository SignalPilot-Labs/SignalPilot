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
    """Evaluate a SQL suite task by comparing result.csv against the gold CSV.

    Returns (passed: bool, details: str).
    """
    import pandas as pd

    result_csv = work_dir / "result.csv"
    if not result_csv.exists():
        msg = f"result.csv not found in {work_dir} — agent did not save output"
        log(msg, "ERROR")
        return False, msg

    # ── Locate gold CSV ────────────────────────────────────────────────────────
    gold_csv = _find_gold_csv(instance_id, config)
    if gold_csv is None or not gold_csv.exists():
        msg = f"Gold CSV not found for {instance_id} (looked in {config.gold_dir})"
        log(msg, "ERROR")
        return False, msg

    log(f"Gold CSV:   {gold_csv}")
    log(f"Result CSV: {result_csv}")

    # ── Load eval config for comparison parameters ─────────────────────────────
    eval_entry = load_eval_config_for_suite(instance_id, config)
    condition_cols: list[int] = []
    ignore_order: bool = True  # default: order-insensitive for SQL results

    if eval_entry:
        params = eval_entry.get("evaluation", {}).get("parameters", {})
        raw_cols = params.get("condition_cols")
        if isinstance(raw_cols, list) and raw_cols:
            # condition_cols may be a list of lists (one per table) or a flat list
            first = raw_cols[0]
            condition_cols = first if isinstance(first, list) else raw_cols
        raw_order = params.get("ignore_orders")
        if isinstance(raw_order, list) and raw_order:
            ignore_order = bool(raw_order[0])
        elif isinstance(raw_order, bool):
            ignore_order = raw_order

    # ── Load DataFrames ────────────────────────────────────────────────────────
    try:
        pred_df = pd.read_csv(result_csv)
    except Exception as e:
        msg = f"Failed to read result.csv: {e}"
        log(msg, "ERROR")
        return False, msg

    try:
        gold_df = pd.read_csv(gold_csv)
    except Exception as e:
        msg = f"Failed to read gold CSV {gold_csv}: {e}"
        log(msg, "ERROR")
        return False, msg

    log(f"Gold shape: {gold_df.shape}, Result shape: {pred_df.shape}")

    # ── Row count check ────────────────────────────────────────────────────────
    gold_sub = gold_df.iloc[:, condition_cols] if condition_cols else gold_df
    if len(gold_sub) != len(pred_df):
        msg = (
            f"FAIL — row count mismatch: gold={len(gold_sub)} pred={len(pred_df)}\n"
            f"  Gold columns: {list(gold_df.columns)}\n"
            f"  Pred columns: {list(pred_df.columns)}"
        )
        log(msg)
        return False, msg

    # ── Value comparison using official Spider2 logic ─────────────────────────
    try:
        match, failed_col = _official_compare(pred_df, gold_df, condition_cols, ignore_order)
    except Exception as e:
        msg = f"FAIL — comparison error: {e}"
        log(msg, "ERROR")
        return False, msg

    if match:
        msg = "PASS"
        log(msg)
        return True, msg

    details_lines = [f"FAIL — no pred column matched gold column '{failed_col}'"]
    if isinstance(failed_col, str) and failed_col in gold_df.columns:
        details_lines.append(f"  Gold '{failed_col}' (first 5): {list(gold_df[failed_col].head(5))}")
        details_lines.append(f"  Pred columns: {list(pred_df.columns)}")
        details_lines.append(f"  Pred head:\n{pred_df.head(3).to_string()}")
    msg = "\n".join(details_lines)
    log(msg)
    return False, msg


def _find_gold_csv(instance_id: str, config: "SuiteConfig") -> Path | None:
    """Locate the gold CSV file for an instance.

    spider2-lite: gold_dir/exec_result/{instance_id}.csv
    spider2-snowflake: gold_dir/{instance_id}/<any>.csv or gold_dir/{instance_id}.csv
    """
    if config.suite == BenchmarkSuite.LITE:
        candidate = config.gold_dir / "exec_result" / f"{instance_id}.csv"
        if candidate.exists():
            return candidate
        # Fallback: check direct gold_dir
        candidate2 = config.gold_dir / f"{instance_id}.csv"
        return candidate2 if candidate2.exists() else candidate  # return even if missing for error msg

    if config.suite == BenchmarkSuite.SNOWFLAKE:
        # Check subdirectory first
        subdir = config.gold_dir / instance_id
        if subdir.is_dir():
            csv_files = list(subdir.glob("*.csv"))
            if csv_files:
                return csv_files[0]
        # Flat file
        candidate = config.gold_dir / f"{instance_id}.csv"
        return candidate

    return None
