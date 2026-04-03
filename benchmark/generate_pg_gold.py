"""
Generate gold-standard CSV result files for the PostgreSQL benchmark tasks.

Connects to enterprise-pg and warehouse-pg, runs the gold SQL queries, and
writes output to datasets/pg-gold/{instance_id}_a.csv.  Also writes a
matching eval config JSONL to datasets/pg-eval.jsonl.

Usage:
    python generate_pg_gold.py

Requires psycopg2 (pip install psycopg2-binary).  Falls back to a subprocess
psql call if psycopg2 is not installed.
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
GOLD_DIR = SCRIPT_DIR / "datasets" / "pg-gold"
EVAL_JSONL = SCRIPT_DIR / "datasets" / "pg-eval.jsonl"

GOLD_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Database connection parameters
# ---------------------------------------------------------------------------

ENTERPRISE_DSN = {
    "host": "host.docker.internal",
    "port": 5601,
    "dbname": "enterprise_prod",
    "user": "enterprise_admin",
    "password": "Ent3rpr1se!S3cur3",
}

WAREHOUSE_DSN = {
    "host": "host.docker.internal",
    "port": 5602,
    "dbname": "analytics_warehouse",
    "user": "warehouse_admin",
    "password": "W4reh0use!An4lyt1cs",
}

# ---------------------------------------------------------------------------
# Task definitions
# ---------------------------------------------------------------------------

TASKS: list[dict[str, Any]] = [
    {
        "instance_id": "pg_ent_001",
        "dsn": ENTERPRISE_DSN,
        "sql": (
            "SELECT loyalty_tier, COUNT(*) AS customer_count"
            " FROM customers"
            " GROUP BY loyalty_tier"
            " ORDER BY customer_count DESC"
        ),
    },
    {
        "instance_id": "pg_ent_002",
        "dsn": ENTERPRISE_DSN,
        "sql": (
            "SELECT status, COUNT(*) AS order_count, SUM(total_amount) AS total_revenue"
            " FROM orders"
            " GROUP BY status"
            " ORDER BY total_revenue DESC"
        ),
    },
    {
        "instance_id": "pg_ent_003",
        "dsn": ENTERPRISE_DSN,
        "sql": (
            "SELECT c.first_name, c.last_name, c.email,"
            " COALESCE(SUM(o.total_amount), 0) AS total_spent"
            " FROM customers c"
            " LEFT JOIN orders o ON o.customer_id = c.id"
            " GROUP BY c.id, c.first_name, c.last_name, c.email"
            " ORDER BY total_spent DESC"
            " LIMIT 10"
        ),
    },
    {
        "instance_id": "pg_ent_004",
        "dsn": ENTERPRISE_DSN,
        "sql": (
            "SELECT COUNT(*) AS customers_without_orders"
            " FROM customers c"
            " LEFT JOIN orders o ON o.customer_id = c.id"
            " WHERE o.id IS NULL"
        ),
    },
    {
        "instance_id": "pg_ent_005",
        "dsn": ENTERPRISE_DSN,
        "sql": (
            "SELECT category, AVG(unit_price) AS avg_price,"
            " SUM(stock_quantity) AS total_stock"
            " FROM products"
            " WHERE is_active = TRUE"
            " GROUP BY category"
            " ORDER BY avg_price DESC"
        ),
    },
    {
        "instance_id": "pg_ent_006",
        "dsn": ENTERPRISE_DSN,
        "sql": (
            "SELECT e.first_name, e.last_name, e.department,"
            " SUM(o.total_amount) AS total_order_value"
            " FROM employees e"
            " JOIN orders o ON o.employee_id = e.id"
            " GROUP BY e.id, e.first_name, e.last_name, e.department"
            " HAVING SUM(o.total_amount) > 60000"
            " ORDER BY total_order_value DESC"
        ),
    },
    {
        "instance_id": "pg_ent_007",
        "dsn": ENTERPRISE_DSN,
        "sql": (
            "SELECT priority,"
            " COUNT(*) AS total_tickets,"
            " COUNT(*) FILTER (WHERE resolved_at <= sla_due_at) AS met_sla,"
            " ROUND("
            "  100.0 * COUNT(*) FILTER (WHERE resolved_at <= sla_due_at)"
            "  / NULLIF(COUNT(*), 0),"
            " 1) AS sla_pct"
            " FROM support_tickets"
            " WHERE resolved_at IS NOT NULL AND sla_due_at IS NOT NULL"
            " GROUP BY priority"
            " ORDER BY priority"
        ),
    },
    {
        "instance_id": "pg_wh_001",
        "dsn": WAREHOUSE_DSN,
        "sql": (
            "SELECT d.year, SUM(f.revenue) AS total_revenue"
            " FROM analytics.fact_sales f"
            " JOIN analytics.dim_date d ON d.date_key = f.date_key"
            " GROUP BY d.year"
            " ORDER BY d.year"
        ),
    },
    {
        "instance_id": "pg_wh_002",
        "dsn": WAREHOUSE_DSN,
        "sql": (
            "SELECT p.category, SUM(f.profit) AS total_profit"
            " FROM analytics.fact_sales f"
            " JOIN analytics.dim_product p ON p.product_key = f.product_key"
            " WHERE p.is_current = TRUE"
            " GROUP BY p.category"
            " ORDER BY total_profit DESC"
        ),
    },
    {
        "instance_id": "pg_wh_003",
        "dsn": WAREHOUSE_DSN,
        "sql": (
            "WITH monthly AS ("
            "  SELECT d.year, d.month, SUM(f.revenue) AS revenue"
            "  FROM analytics.fact_sales f"
            "  JOIN analytics.dim_date d ON d.date_key = f.date_key"
            "  GROUP BY d.year, d.month"
            ")"
            " SELECT year, month, revenue,"
            "  LAG(revenue) OVER (ORDER BY year, month) AS prev_month_revenue,"
            "  ROUND("
            "    100.0 * (revenue - LAG(revenue) OVER (ORDER BY year, month))"
            "    / NULLIF(LAG(revenue) OVER (ORDER BY year, month), 0),"
            "  2) AS growth_pct"
            " FROM monthly"
            " ORDER BY year, month"
        ),
    },
]

# ---------------------------------------------------------------------------
# Eval config (mirrors spider2lite_eval.jsonl format)
# ---------------------------------------------------------------------------

EVAL_CONFIG: list[dict[str, Any]] = [
    {"instance_id": "pg_ent_001", "condition_cols": [], "ignore_order": True},
    {"instance_id": "pg_ent_002", "condition_cols": [], "ignore_order": True},
    {"instance_id": "pg_ent_003", "condition_cols": [], "ignore_order": True},
    {"instance_id": "pg_ent_004", "condition_cols": [], "ignore_order": True},
    {"instance_id": "pg_ent_005", "condition_cols": [], "ignore_order": True},
    {"instance_id": "pg_ent_006", "condition_cols": [], "ignore_order": True},
    {"instance_id": "pg_ent_007", "condition_cols": [], "ignore_order": True},
    {"instance_id": "pg_wh_001", "condition_cols": [], "ignore_order": False},
    {"instance_id": "pg_wh_002", "condition_cols": [], "ignore_order": True},
    {"instance_id": "pg_wh_003", "condition_cols": [], "ignore_order": False},
]

# ---------------------------------------------------------------------------
# DB driver selection
# ---------------------------------------------------------------------------


def _try_psycopg2() -> bool:
    try:
        import psycopg2  # noqa: F401
        return True
    except ImportError:
        return False


def _try_psycopg3() -> bool:
    try:
        import psycopg  # noqa: F401
        return True
    except ImportError:
        return False


def _run_via_psycopg2(dsn: dict, sql: str) -> tuple[list[str], list[tuple]]:
    import psycopg2
    import psycopg2.extras

    conn_str = (
        f"host={dsn['host']} port={dsn['port']} dbname={dsn['dbname']}"
        f" user={dsn['user']} password={dsn['password']}"
    )
    with psycopg2.connect(conn_str) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            rows = cur.fetchall()
            if not rows:
                # Still need column names from description
                columns = [desc[0] for desc in cur.description] if cur.description else []
                return columns, []
            columns = list(rows[0].keys())
            return columns, [tuple(r.values()) for r in rows]


def _run_via_psycopg3(dsn: dict, sql: str) -> tuple[list[str], list[tuple]]:
    import psycopg

    conn_str = (
        f"host={dsn['host']} port={dsn['port']} dbname={dsn['dbname']}"
        f" user={dsn['user']} password={dsn['password']}"
    )
    with psycopg.connect(conn_str) as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(sql)
            rows = cur.fetchall()
            if not rows:
                columns = [desc[0] for desc in cur.description] if cur.description else []
                return columns, []
            columns = list(rows[0].keys())
            return columns, [tuple(r.values()) for r in rows]


def _run_via_psql(dsn: dict, sql: str) -> tuple[list[str], list[tuple]]:
    """Fallback: run query via psql subprocess and parse CSV output."""
    env_pass = {"PGPASSWORD": dsn["password"]}
    import os
    env = {**os.environ, **env_pass}

    with tempfile.NamedTemporaryFile(mode="w", suffix=".sql", delete=False) as f:
        f.write(r"\pset format csv" + "\n")
        f.write(r"\pset tuples_only off" + "\n")
        f.write(sql.rstrip(";") + ";\n")
        sql_file = f.name

    try:
        result = subprocess.run(
            [
                "psql",
                "-h", dsn["host"],
                "-p", str(dsn["port"]),
                "-U", dsn["user"],
                "-d", dsn["dbname"],
                "-f", sql_file,
                "--no-psqlrc",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(f"psql error: {result.stderr.strip()}")

        lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
        if not lines:
            return [], []

        reader = csv.reader(lines)
        headers = next(reader, [])
        rows = [tuple(row) for row in reader if row]
        return headers, rows
    finally:
        Path(sql_file).unlink(missing_ok=True)


def run_query(dsn: dict, sql: str) -> tuple[list[str], list[tuple]]:
    """Run a SQL query using the best available driver."""
    if _try_psycopg2():
        return _run_via_psycopg2(dsn, sql)
    if _try_psycopg3():
        return _run_via_psycopg3(dsn, sql)
    print("  [warn] psycopg2/psycopg not found — falling back to psql subprocess")
    return _run_via_psql(dsn, sql)


# ---------------------------------------------------------------------------
# CSV writer
# ---------------------------------------------------------------------------


def write_gold_csv(path: Path, columns: list[str], rows: list[tuple]) -> int:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(rows)
    return len(rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    print(f"Output directory : {GOLD_DIR}")
    print(f"Eval config      : {EVAL_JSONL}")
    print()

    success = 0
    failure = 0

    for task in TASKS:
        instance_id: str = task["instance_id"]
        dsn: dict = task["dsn"]
        sql: str = task["sql"]
        out_path = GOLD_DIR / f"{instance_id}_a.csv"

        db_label = dsn["dbname"]
        print(f"[{instance_id}] {db_label} ... ", end="", flush=True)

        try:
            columns, rows = run_query(dsn, sql)
            row_count = write_gold_csv(out_path, columns, rows)
            print(f"OK  ({row_count} rows -> {out_path.name})")
            success += 1
        except Exception as exc:
            print(f"FAILED\n  {exc}")
            failure += 1

    # Write eval config JSONL
    print()
    with open(EVAL_JSONL, "w", encoding="utf-8") as f:
        for entry in EVAL_CONFIG:
            f.write(json.dumps(entry) + "\n")
    print(f"Wrote eval config: {EVAL_JSONL}")

    print()
    print(f"Done: {success} succeeded, {failure} failed.")
    if failure:
        sys.exit(1)


if __name__ == "__main__":
    main()
