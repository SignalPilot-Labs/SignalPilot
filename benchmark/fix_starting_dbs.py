"""Fix starting DBs for tasks where pre-existing models use current_date.

Rebuilds date-dependent tables using the hardcoded gold build date (2024-09-08).
Called from the runner both before and after the agent runs.

Or call fix_task_db() from the runner after prepare_workdir.
"""
import duckdb
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

WORK_DIR = Path(os.environ.get("BENCHMARK_WORK_DIR", "/workdir/dbt"))


GOLD_BUILD_DATE = "2024-09-08"


def _get_reference_date() -> str:
    """Return the gold build date used to create the spider2 evaluation data."""
    return GOLD_BUILD_DATE


def _get_fixes(ref_date: str) -> dict:
    """Build the fix definitions using the given reference date."""
    return {
        "shopify001": {
            "db": "shopify.duckdb",
            "rebuild": [
                (
                    "shopify__calendar",
                    f"""
                    WITH RECURSIVE dates AS (
                        SELECT CAST('2019-01-01' AS DATE) as date_day
                        UNION ALL
                        SELECT CAST(date_day + INTERVAL 1 DAY AS DATE) FROM dates
                        WHERE date_day < CAST('{ref_date}' AS DATE) - INTERVAL 1 DAY
                    )
                    SELECT date_day FROM dates
                    """,
                ),
            ],
        },
        "pendo001": {
            "db": "pendo.duckdb",
            "rebuild": [
                (
                    "int_pendo__calendar_spine",
                    f"""
                    WITH RECURSIVE dates AS (
                        SELECT CAST((SELECT MIN(created_at)::DATE FROM application_history) AS DATE) as date_day
                        UNION ALL
                        SELECT CAST(date_day + INTERVAL 1 DAY AS DATE) FROM dates
                        WHERE date_day < CAST('{ref_date}' AS DATE) + INTERVAL 6 DAY
                    )
                    SELECT CAST(date_day AS DATE) as date_day FROM dates
                    """,
                ),
            ],
            "dbt_rebuild": [
                "int_pendo__guide_daily_metrics",
                "pendo__guide_daily_metrics",
            ],
        },
        "zuora001": {
            "db": "zuora.duckdb",
            "updates": [
                (
                    "int_zuora__account_enriched",
                    f"""
                    UPDATE int_zuora__account_enriched
                    SET account_active_months = CAST(
                        datediff('day', created_date, CAST('{ref_date}' AS TIMESTAMP)) AS DOUBLE
                    ) / 30.0,
                    is_new_customer = CASE
                        WHEN datediff('day', created_date, CAST('{ref_date}' AS TIMESTAMP)) <= 30
                        THEN true ELSE false
                    END
                    """,
                ),
                (
                    "zuora__account_overview",
                    f"""
                    UPDATE zuora__account_overview AS o
                    SET account_active_months = e.account_active_months,
                        is_new_customer = e.is_new_customer,
                        monthly_average_subscription_count = ROUND(CAST(o.total_subscription_count / NULLIF(e.account_active_months, 0) AS NUMERIC), 2),
                        monthly_average_invoice_amount = ROUND(CAST(o.total_invoice_amount / NULLIF(e.account_active_months, 0) AS NUMERIC), 2),
                        monthly_average_invoice_amount_home_currency = ROUND(CAST(o.total_invoice_amount_home_currency / NULLIF(e.account_active_months, 0) AS NUMERIC), 2),
                        monthly_average_taxes = ROUND(CAST(o.total_taxes / NULLIF(e.account_active_months, 0) AS NUMERIC), 2),
                        monthly_average_discounts = ROUND(CAST(o.total_discounts / NULLIF(e.account_active_months, 0) AS NUMERIC), 2),
                        monthly_average_amount_paid = ROUND(CAST(o.total_amount_paid / NULLIF(e.account_active_months, 0) AS NUMERIC), 2),
                        monthly_average_amount_not_paid = ROUND(CAST(o.total_amount_not_paid / NULLIF(e.account_active_months, 0) AS NUMERIC), 2),
                        monthly_average_amount_past_due = ROUND(CAST(o.total_amount_past_due / NULLIF(e.account_active_months, 0) AS NUMERIC), 2),
                        monthly_average_refunds = ROUND(CAST(o.total_refunds / NULLIF(e.account_active_months, 0) AS NUMERIC), 2)
                    FROM (
                        SELECT account_number,
                               CAST(datediff('day', created_date, CAST('{ref_date}' AS TIMESTAMP)) AS DOUBLE) / 30.0
                                   AS account_active_months,
                               CASE WHEN datediff('day', created_date, CAST('{ref_date}' AS TIMESTAMP)) <= 30
                                    THEN true ELSE false END AS is_new_customer
                        FROM int_zuora__account_enriched
                    ) e
                    WHERE o.account_number = e.account_number
                    """,
                ),
            ],
        },
    }


def fix_task_db(task_id: str, work_dir: Path | None = None) -> bool:
    """Fix date-dependent tables in a task's workdir DB. Returns True if any fixes applied."""
    ref_date = _get_reference_date()
    print(f"  fix_task_db: task={task_id}, ref_date={ref_date}, work_dir={work_dir}", flush=True)
    fixes = _get_fixes(ref_date)

    if task_id not in fixes:
        return False

    config = fixes[task_id]
    base = work_dir or (WORK_DIR / task_id)
    db_path = base / config["db"]
    if not db_path.exists():
        return False

    con = duckdb.connect(str(db_path))
    fixed = False

    for table_name, sql in config.get("rebuild", []):
        try:
            old_count = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            con.execute(f"DROP TABLE IF EXISTS {table_name}")
            con.execute(f"CREATE TABLE {table_name} AS {sql}")
            new_count = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            max_date = con.execute(f"SELECT MAX(date_day) FROM {table_name}").fetchone()[0]
            print(f"  {table_name}: {old_count} -> {new_count} rows, max={max_date}")
            fixed = True
        except Exception as e:
            print(f"  {table_name}: ERROR {e}")

    for table_name, sql in config.get("updates", []):
        try:
            # Check if table exists before attempting update
            tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
            if table_name not in tables:
                print(f"  {table_name}: SKIPPED (table does not exist)", flush=True)
                continue
            # Show before values
            try:
                before = con.execute(f"SELECT account_number, account_active_months FROM {table_name} ORDER BY account_number LIMIT 4").fetchall()
                print(f"  {table_name}: BEFORE = {[(r[0], round(r[1],2)) for r in before]}", flush=True)
            except Exception:
                pass
            con.execute(sql)
            # Show after values
            try:
                after = con.execute(f"SELECT account_number, account_active_months FROM {table_name} ORDER BY account_number LIMIT 4").fetchall()
                print(f"  {table_name}: AFTER  = {[(r[0], round(r[1],2)) for r in after]}", flush=True)
            except Exception:
                pass
            print(f"  {table_name}: updated with reference date {ref_date}", flush=True)
            fixed = True
        except Exception as e:
            print(f"  {table_name}: ERROR {e}", flush=True)

    con.close()

    # Run dbt rebuild for downstream models if specified
    dbt_rebuild = config.get("dbt_rebuild", [])
    if dbt_rebuild and fixed:
        dbt_bin = shutil.which("dbt") or "/usr/local/bin/dbt"
        select_args = " ".join(dbt_rebuild)
        cmd = f"{dbt_bin} run --select {select_args}"
        print(f"  dbt_rebuild: {cmd}", flush=True)
        try:
            result = subprocess.run(
                cmd, shell=True, cwd=str(base),
                capture_output=True, text=True, timeout=180,
            )
            if result.returncode == 0:
                print(f"  dbt_rebuild: OK", flush=True)
            else:
                print(f"  dbt_rebuild: FAILED (rc={result.returncode})", flush=True)
                print(f"  stderr: {result.stderr[-300:]}", flush=True)
        except Exception as e:
            print(f"  dbt_rebuild: ERROR {e}", flush=True)

    return fixed


if __name__ == "__main__":
    ref_date = _get_reference_date()
    fixes = _get_fixes(ref_date)
    tasks = sys.argv[1:] if len(sys.argv) > 1 else list(fixes.keys())
    print(f"Fixing starting DBs with reference date {ref_date}...")
    for task_id in tasks:
        if task_id in fixes:
            print(f"\n=== {task_id} ===")
            fix_task_db(task_id)
        else:
            print(f"\n=== {task_id}: no fixes needed ===")
    print("\nDone.")
