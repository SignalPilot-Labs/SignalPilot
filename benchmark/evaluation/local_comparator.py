"""Legacy positional-column comparator used by the local (non-Docker) runner.

This predates the Spider2-compatible comparator in `comparator.py` and preserves
the original run_dbt_local.py behavior (align by positional index, compare each
selected column with numeric tolerance + string fallback).
"""

from __future__ import annotations

from pathlib import Path

from ..core.logging import log
from ..core.paths import GOLD_DIR
from ..core.tasks import load_eval_config


def evaluate(project_dir: Path, instance_id: str) -> tuple[bool, str]:
    """Evaluate result against gold standard (local runner variant)."""
    import duckdb
    import pandas as pd

    eval_config = load_eval_config(instance_id)
    if not eval_config:
        return False, "No evaluation config found"

    eval_params = eval_config["evaluation"]["parameters"]
    gold_db_path = str(GOLD_DIR / instance_id / eval_params["gold"])
    result_db_path = str(project_dir / eval_params["gold"])

    condition_tabs = eval_params.get("condition_tabs")
    condition_cols = eval_params.get("condition_cols")
    ignore_orders = eval_params.get("ignore_orders")

    log(f"Gold DB: {gold_db_path}")
    log(f"Result DB: {result_db_path}")

    if not Path(result_db_path).exists():
        return False, f"Result DB not found: {result_db_path}"
    if not Path(gold_db_path).exists():
        return False, (
            f"Gold DB not found: {gold_db_path}\n"
            f"  Run: python -m benchmark.setup_dbt --build-gold {instance_id}"
        )

    def get_tables(db_path):
        con = duckdb.connect(database=db_path, read_only=True)
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
        con.close()
        return tables

    def get_table(db_path, table_name):
        con = duckdb.connect(database=db_path, read_only=True)
        df = con.execute(f"SELECT * FROM {table_name}").fetchdf()
        con.close()
        return df

    result_tables = get_tables(result_db_path)
    gold_tables = get_tables(gold_db_path)
    log(f"Gold tables: {gold_tables}")
    log(f"Result tables: {result_tables}")

    if condition_tabs is None:
        condition_tabs = gold_tables
    if ignore_orders is None:
        ignore_orders = [False] * len(condition_tabs)
    if condition_cols is None:
        condition_cols = [[]] * len(condition_tabs)

    all_match = True
    details: list[str] = []

    for i, tab in enumerate(condition_tabs):
        log(f"Checking table: {tab}")

        if tab not in result_tables:
            details.append(f"  {tab}: FAIL - not in result DB")
            log(f"  FAIL - '{tab}' not in result (have: {result_tables})")
            all_match = False
            continue

        try:
            gold_df = get_table(gold_db_path, tab)
            pred_df = get_table(result_db_path, tab)
        except Exception as e:
            details.append(f"  {tab}: ERROR - {e}")
            log(f"  ERROR: {e}")
            all_match = False
            continue

        log(f"  Gold: {gold_df.shape}, Result: {pred_df.shape}")

        cols = condition_cols[i] if condition_cols[i] else list(range(len(gold_df.columns)))
        try:
            gold_sub = gold_df.iloc[:, cols]
            pred_sub = pred_df.iloc[:, cols]
        except IndexError as e:
            details.append(f"  {tab}: FAIL - column index error: {e}")
            all_match = False
            continue

        # Align column names: cols are selected by index, so positional match is correct
        pred_sub.columns = gold_sub.columns

        if gold_sub.shape != pred_sub.shape:
            details.append(f"  {tab}: FAIL - shape mismatch gold={gold_sub.shape} pred={pred_sub.shape}")
            log("  FAIL - shape mismatch")
            all_match = False
            continue

        if ignore_orders[i]:
            try:
                gold_sub = gold_sub.sort_values(by=list(gold_sub.columns)).reset_index(drop=True)
                pred_sub = pred_sub.sort_values(by=list(pred_sub.columns)).reset_index(drop=True)
            except (TypeError, ValueError):
                sort_cols = list(gold_sub.columns)
                gold_order = gold_sub.apply(lambda c: c.astype(str)).sort_values(by=sort_cols).index
                pred_order = pred_sub.apply(lambda c: c.astype(str)).sort_values(by=sort_cols).index
                gold_sub = gold_sub.loc[gold_order].reset_index(drop=True)
                pred_sub = pred_sub.loc[pred_order].reset_index(drop=True)

        try:
            match = True
            mismatch_col = None
            for col in gold_sub.columns:
                g = gold_sub[col]
                p = pred_sub[col]
                is_numeric = pd.api.types.is_numeric_dtype(g) or pd.api.types.is_numeric_dtype(p)
                if is_numeric:
                    try:
                        gn = pd.to_numeric(g, errors="coerce").fillna(0)
                        pn = pd.to_numeric(p, errors="coerce").fillna(0)
                        if not all(abs(a - b) < 0.01 for a, b in zip(gn, pn)):
                            match = False
                            mismatch_col = col
                            break
                    except Exception:
                        gs = g.astype(str).replace({"<NA>": "", "nan": "", "None": ""})
                        ps = p.astype(str).replace({"<NA>": "", "nan": "", "None": ""})
                        if not all(str(a).strip().lower() == str(b).strip().lower() for a, b in zip(gs, ps)):
                            match = False
                            mismatch_col = col
                            break
                else:
                    gs = g.astype(str).replace({"<NA>": "", "nan": "", "None": ""})
                    ps = p.astype(str).replace({"<NA>": "", "nan": "", "None": ""})
                    if not all(str(a).strip().lower() == str(b).strip().lower() for a, b in zip(gs, ps)):
                        match = False
                        mismatch_col = col
                        break

            if match:
                details.append(f"  {tab}: PASS ({gold_sub.shape[0]} rows, {len(cols)} cols)")
                log(f"  PASS - {gold_sub.shape[0]} rows, {len(cols)} cols")
            else:
                details.append(f"  {tab}: FAIL - values mismatch (column: {mismatch_col})")
                log(f"  FAIL - mismatch in column '{mismatch_col}'")
                all_match = False
        except Exception as e:
            details.append(f"  {tab}: FAIL - comparison error: {e}")
            all_match = False

    return all_match, "\n".join(details)
