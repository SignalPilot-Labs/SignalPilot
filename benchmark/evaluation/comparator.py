"""Spider2-compatible DuckDB-vs-gold comparator."""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING

from ..core.logging import log
from ..core.paths import GOLD_DIR
from ..core.tasks import load_eval_config, load_eval_config_for_suite
from .db_utils import find_result_db

if TYPE_CHECKING:
    from ..core.suite import SuiteConfig


def _official_compare(pred_df, gold_df, cols, ignore_order):
    """Replicates compare_pandas_table() from the official Spider2-DBT eval_utils.py.

    For each gold column (selected by positional index via cols), checks if ANY
    column in pred_df has a matching value vector. Row count must match.
    Returns (match: bool, failed_gold_col_name: str | None).
    """
    import pandas as pd

    tolerance = 1e-2

    def _normalize_for_compare(a, b):
        """Handle type mismatches between str↔Timestamp and str↔numeric."""
        from datetime import datetime, date
        a_is_dt = isinstance(a, (datetime, date, pd.Timestamp))
        b_is_dt = isinstance(b, (datetime, date, pd.Timestamp))
        if a_is_dt or b_is_dt:
            try:
                sa = str(a).rstrip('0').rstrip('.') if a_is_dt else str(a).rstrip('0').rstrip('.')
                sb = str(b).rstrip('0').rstrip('.') if b_is_dt else str(b).rstrip('0').rstrip('.')
                for suffix in [' 00:00:00', '.0', 'T00:00:00']:
                    sa = sa.removesuffix(suffix)
                    sb = sb.removesuffix(suffix)
                return sa == sb
            except Exception:
                pass
        return None

    def _sort_key(x):
        """Sort NULLs first, then numbers numerically, then strings."""
        if x is None or (isinstance(x, float) and math.isnan(x)):
            return (0, 0.0, '')
        if isinstance(x, (int, float)):
            return (1, float(x), '')
        return (2, 0.0, str(x))

    def vectors_match(v1, v2):
        try:
            if ignore_order:
                v1 = sorted(v1, key=_sort_key)
                v2 = sorted(v2, key=_sort_key)
            if len(v1) != len(v2):
                return False
            for a, b in zip(v1, v2):
                if pd.isna(a) and pd.isna(b):
                    continue
                elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
                    if not math.isclose(float(a), float(b), abs_tol=tolerance):
                        return False
                elif a != b:
                    normalized = _normalize_for_compare(a, b)
                    if normalized is not True:
                        return False
            return True
        except Exception:
            return False

    if cols:
        try:
            gold_sub = gold_df.iloc[:, cols]
        except IndexError as e:
            return False, f"gold column index error: {e}"
    else:
        gold_sub = gold_df

    # Normalize nullable dtypes (StringDtype, Int64, etc.) to plain python types
    # to ensure consistent comparison between gold and pred DataFrames.
    def _to_plain_df(df):
        import numpy as np
        for col in df.columns:
            if hasattr(df[col], 'astype'):
                try:
                    if pd.api.types.is_string_dtype(df[col]):
                        df[col] = df[col].astype(object).where(df[col].notna(), None)
                    elif pd.api.types.is_integer_dtype(df[col]) and df[col].dtype.name != 'int64':
                        df[col] = df[col].astype('int64')
                except Exception:
                    pass
        return df

    gold_sub = _to_plain_df(gold_sub.copy())
    pred_df = _to_plain_df(pred_df.copy())

    t_gold_list = gold_sub.transpose().values.tolist()
    t_pred_list = pred_df.transpose().values.tolist()

    for idx, gold_vec in enumerate(t_gold_list):
        if not any(vectors_match(gold_vec, pred_vec) for pred_vec in t_pred_list):
            col_name = gold_sub.columns[idx] if idx < len(gold_sub.columns) else str(idx)
            return False, col_name
    return True, None


def evaluate(
    project_dir: Path, instance_id: str, config: "SuiteConfig | None" = None
) -> tuple[bool, str]:
    """Evaluate the result against gold standard by comparing DuckDB table contents."""
    import duckdb

    if config is not None:
        eval_config = load_eval_config_for_suite(instance_id, config)
    else:
        eval_config = load_eval_config(instance_id)

    if not eval_config:
        return False, "No evaluation config found in spider2_eval.jsonl"

    params = eval_config["evaluation"]["parameters"]
    # The DB filename in eval config may not match the actual filename — find it
    gold_base = config.gold_dir if config is not None else GOLD_DIR
    gold_db_candidates = list((gold_base / instance_id).glob("*.duckdb"))
    gold_db_path = str(gold_db_candidates[0]) if gold_db_candidates else str(gold_base / instance_id / params["gold"])
    _path = find_result_db(project_dir, params["gold"])
    result_db_path = str(_path) if _path else str(project_dir / params["gold"])

    condition_tabs: list[str] | None = params.get("condition_tabs")
    condition_cols: list[list[int]] | None = params.get("condition_cols")
    ignore_orders: list[bool] | None = params.get("ignore_orders")

    log(f"Gold DB:   {gold_db_path}")
    log(f"Result DB: {result_db_path}")

    if not Path(result_db_path).exists():
        return False, f"Result DB not found: {result_db_path}"
    if not Path(gold_db_path).exists():
        return False, f"Gold DB not found: {gold_db_path}"

    gold_con = duckdb.connect(database=gold_db_path, read_only=True)
    result_con = duckdb.connect(database=result_db_path, read_only=True)

    def get_tables(con) -> list[str]:
        return [r[0] for r in con.execute("SHOW TABLES").fetchall()]

    def get_table_df(con, table_name: str):
        return con.execute(f"SELECT * FROM {table_name}").fetchdf()

    result_tables = get_tables(result_con)
    gold_tables = get_tables(gold_con)
    log(f"Gold tables:   {gold_tables}")
    log(f"Result tables: {result_tables}")

    raw_tabs = condition_tabs if condition_tabs is not None else gold_tables
    effective_orders = ignore_orders if ignore_orders is not None else [False] * len(raw_tabs)
    effective_cols = condition_cols if condition_cols is not None else [[]] * len(raw_tabs)

    # Resolve eval config table names against actual gold tables.
    # Spider2 eval configs sometimes use different prefixes (e.g. fct_ vs fact_).
    effective_tabs: list[str] = []
    for tab in raw_tabs:
        if tab in gold_tables:
            effective_tabs.append(tab)
        else:
            # Try common prefix swaps: fct_↔fact_, dim_↔dimension_, etc.
            resolved = None
            tab_lower = tab.lower()
            for gt in gold_tables:
                gt_lower = gt.lower()
                # Check if they share most of the name (differ only in prefix)
                if tab_lower.replace("fct_", "fact_") == gt_lower or \
                   tab_lower.replace("fact_", "fct_") == gt_lower or \
                   tab_lower == gt_lower:
                    resolved = gt
                    break
            if resolved:
                log(f"Resolved eval table '{tab}' -> gold table '{resolved}'")
                effective_tabs.append(resolved)
            else:
                effective_tabs.append(tab)  # keep original, will fail gracefully

    all_match = True
    details: list[str] = []

    for i, tab in enumerate(effective_tabs):
        log(f"Checking table: {tab}")

        # Resolve result table name (same prefix swap logic)
        result_tab = tab
        if tab not in result_tables:
            for rt in result_tables:
                if tab.lower().replace("fct_", "fact_") == rt.lower() or \
                   tab.lower().replace("fact_", "fct_") == rt.lower() or \
                   tab.lower() == rt.lower():
                    log(f"  Resolved result table '{tab}' -> '{rt}'")
                    result_tab = rt
                    break

        if result_tab not in result_tables:
            msg = f"  {tab}: FAIL — table not in result DB (have: {result_tables})"
            details.append(msg)
            log(msg)
            all_match = False
            continue

        try:
            gold_df = get_table_df(gold_con, tab)
            pred_df = get_table_df(result_con, result_tab)
        except Exception as e:
            msg = f"  {tab}: ERROR reading table — {e}"
            details.append(msg)
            log(msg, "ERROR")
            all_match = False
            continue

        log(f"  Gold shape: {gold_df.shape}, Result shape: {pred_df.shape}")

        cols = effective_cols[i] if effective_cols[i] else []

        try:
            gold_sub = gold_df.iloc[:, cols] if cols else gold_df
        except IndexError as e:
            msg = f"  {tab}: FAIL — gold column index error: {e}"
            details.append(msg)
            log(msg)
            all_match = False
            continue

        if len(gold_sub) != len(pred_df):
            msg = f"  {tab}: FAIL — row count mismatch gold={len(gold_sub)} pred={len(pred_df)}"
            details.append(msg)
            log(msg)
            all_match = False
            continue

        try:
            match, failed_col = _official_compare(pred_df, gold_df, cols, ignore_order=effective_orders[i])
            if match:
                msg = f"  {tab}: PASS"
                details.append(msg)
                log(msg)
            else:
                msg = f"  {tab}: FAIL — no pred column matched gold column '{failed_col}'"
                details.append(msg)
                log(msg)
                if isinstance(failed_col, str) and failed_col in gold_df.columns:
                    log(f"  Gold column '{failed_col}' values: {list(gold_df[failed_col].head(5))}")
                    log(f"  Pred columns: {list(pred_df.columns)}")
                    log(f"  Pred head:\n{pred_df.head(3)}")
                all_match = False
        except Exception as e:
            msg = f"  {tab}: FAIL — comparison error: {e}"
            details.append(msg)
            log(msg, "ERROR")
            all_match = False

    gold_con.close()
    result_con.close()
    return all_match, "\n".join(details)
