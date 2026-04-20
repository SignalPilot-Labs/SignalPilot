"""Generate all binary test data for the test task suite.

Run once (idempotent) to populate benchmark/test_tasks/ with:
- SQLite DB (sqlite_dbs/test_chinook.sqlite)
- DuckDB for dbt source (dbt_projects/test_dbt_simple001/test_dbt_simple001.duckdb)
- Gold DuckDB for dbt evaluation (gold/dbt/test_dbt_simple001/test_dbt_simple001.duckdb)
- Gold CSVs for lite tasks (gold/lite/exec_result/*.csv)
- Gold CSV for Snowflake tasks (gold/snowflake/test_sf_current_date/result.csv)

Usage:
    python -m benchmark.test_tasks.setup_test_data
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# ── Path constants ─────────────────────────────────────────────────────────────

TEST_TASKS_DIR = Path(__file__).resolve().parent
BENCHMARK_DIR = TEST_TASKS_DIR.parent

SQLITE_DBS_DIR = TEST_TASKS_DIR / "sqlite_dbs"
DBT_PROJECTS_DIR = TEST_TASKS_DIR / "dbt_projects"
GOLD_LITE_DIR = TEST_TASKS_DIR / "gold" / "lite" / "exec_result"
GOLD_SNOWFLAKE_DIR = TEST_TASKS_DIR / "gold" / "snowflake"
GOLD_DBT_DIR = TEST_TASKS_DIR / "gold" / "dbt"

# Customer data used across SQLite, DuckDB, and gold files
CUSTOMERS = [
    (1, "Alice", "Portland"),
    (2, "Bob", "Seattle"),
    (3, "Carol", "Portland"),
    (4, "Dave", "Chicago"),
    (5, "Eve", "Portland"),
]

PORTLAND_CUSTOMERS = [(r[0], r[1], r[2]) for r in CUSTOMERS if r[2] == "Portland"]


def _ensure_dirs() -> None:
    for d in [SQLITE_DBS_DIR, GOLD_LITE_DIR, GOLD_SNOWFLAKE_DIR / "test_sf_current_date", GOLD_DBT_DIR / "test_dbt_simple001"]:
        d.mkdir(parents=True, exist_ok=True)


def _create_sqlite_db() -> None:
    """Create test_chinook.sqlite with customers table (5 rows)."""
    db_path = SQLITE_DBS_DIR / "test_chinook.sqlite"
    con = sqlite3.connect(str(db_path))
    con.execute("DROP TABLE IF EXISTS customers")
    con.execute("CREATE TABLE customers (id INTEGER, name TEXT, city TEXT)")
    con.executemany("INSERT INTO customers VALUES (?, ?, ?)", CUSTOMERS)
    con.commit()
    con.close()
    print(f"  Created SQLite DB: {db_path} ({len(CUSTOMERS)} rows)")


def _create_dbt_source_duckdb() -> None:
    """Create test_dbt_simple001.duckdb with raw_customers table in dbt_projects/."""
    import duckdb

    db_path = DBT_PROJECTS_DIR / "test_dbt_simple001" / "test_dbt_simple001.duckdb"
    if db_path.exists():
        db_path.unlink()

    con = duckdb.connect(str(db_path))
    con.execute("CREATE TABLE raw_customers (id INTEGER, name VARCHAR, city VARCHAR)")
    con.executemany("INSERT INTO raw_customers VALUES (?, ?, ?)", CUSTOMERS)
    con.close()
    print(f"  Created dbt source DuckDB: {db_path} ({len(CUSTOMERS)} rows)")


def _create_gold_dbt_duckdb() -> None:
    """Create gold DuckDB for dbt eval with customer_summary table."""
    import duckdb

    db_path = GOLD_DBT_DIR / "test_dbt_simple001" / "test_dbt_simple001.duckdb"
    if db_path.exists():
        db_path.unlink()

    con = duckdb.connect(str(db_path))
    con.execute("CREATE TABLE customer_summary (id INTEGER, name VARCHAR, city VARCHAR)")
    con.executemany("INSERT INTO customer_summary VALUES (?, ?, ?)", CUSTOMERS)
    con.close()
    print(f"  Created gold dbt DuckDB: {db_path} ({len(CUSTOMERS)} rows)")


def _create_gold_lite_sqlite_csv() -> None:
    """Create gold CSV for test_lite_sqlite001 (Portland customers)."""
    csv_path = GOLD_LITE_DIR / "test_lite_sqlite001.csv"
    lines = ["id,name,city"]
    for row in PORTLAND_CUSTOMERS:
        lines.append(f"{row[0]},{row[1]},{row[2]}")
    csv_path.write_text("\n".join(lines) + "\n")
    print(f"  Created SQLite gold CSV: {csv_path} ({len(PORTLAND_CUSTOMERS)} rows)")


def _create_gold_lite_bq_csv() -> None:
    """Create gold CSV for test_lite_bq001 (literal SELECT 1, 'hello')."""
    csv_path = GOLD_LITE_DIR / "test_lite_bq001.csv"
    csv_path.write_text("test_value,test_string\n1,hello\n")
    print(f"  Created BigQuery gold CSV: {csv_path}")


def _create_gold_snowflake_csv() -> None:
    """Query live Snowflake INFORMATION_SCHEMA.DATABASES to generate gold CSV.

    Queries the databases ordered by database_name ascending.
    Falls back to a placeholder if connection fails.
    """
    sf_gold_dir = GOLD_SNOWFLAKE_DIR / "test_sf_current_date"
    csv_path = sf_gold_dir / "result.csv"

    try:
        _query_snowflake_databases(csv_path)
    except Exception as e:
        print(f"  WARN: Could not query Snowflake for gold data: {e}")
        print("  Writing placeholder gold CSV — re-run setup after Snowflake is accessible")
        csv_path.write_text("database_name\nPLACEHOLDER_RUN_SETUP_AGAIN\n")


def _query_snowflake_databases(csv_path: Path) -> None:
    """Query Snowflake and write the result to csv_path."""
    env_file = BENCHMARK_DIR / ".env.snowflake"
    if not env_file.exists():
        raise FileNotFoundError(f".env.snowflake not found: {env_file}")

    env_vars = _load_dotenv(env_file)
    account: str = env_vars["SNOWFLAKE_ACCOUNT"]
    user: str = env_vars["SNOWFLAKE_USER"]
    token: str = env_vars["SNOWFLAKE_TOKEN"]
    role: str | None = env_vars.get("SNOWFLAKE_ROLE")
    warehouse: str | None = env_vars.get("SNOWFLAKE_WAREHOUSE")

    import snowflake.connector

    conn_kwargs: dict = {
        "account": account,
        "user": user,
        "password": token,
        "database": "SNOWFLAKE",
        "schema": "INFORMATION_SCHEMA",
    }
    if role:
        conn_kwargs["role"] = role
    if warehouse:
        conn_kwargs["warehouse"] = warehouse

    con = snowflake.connector.connect(**conn_kwargs)
    try:
        cursor = con.cursor()
        cursor.execute("SELECT database_name FROM INFORMATION_SCHEMA.DATABASES ORDER BY database_name ASC")
        rows = cursor.fetchall()
        lines = ["database_name"]
        for row in rows:
            lines.append(str(row[0]))
        csv_path.write_text("\n".join(lines) + "\n")
        print(f"  Created Snowflake gold CSV: {csv_path} ({len(rows)} databases)")
    finally:
        con.close()


def _create_gold_lite_sf_csv() -> None:
    """Query live Snowflake to count databases for test_lite_sf001 gold CSV."""
    csv_path = GOLD_LITE_DIR / "test_lite_sf001.csv"

    try:
        _query_snowflake_db_count(csv_path)
    except Exception as e:
        print(f"  WARN: Could not query Snowflake for db_count gold data: {e}")
        print("  Writing placeholder gold CSV — re-run setup after Snowflake is accessible")
        csv_path.write_text("db_count\n0\n")


def _query_snowflake_db_count(csv_path: Path) -> None:
    """Query Snowflake COUNT of databases and write gold CSV."""
    env_file = BENCHMARK_DIR / ".env.snowflake"
    if not env_file.exists():
        raise FileNotFoundError(f".env.snowflake not found: {env_file}")

    env_vars = _load_dotenv(env_file)
    account: str = env_vars["SNOWFLAKE_ACCOUNT"]
    user: str = env_vars["SNOWFLAKE_USER"]
    token: str = env_vars["SNOWFLAKE_TOKEN"]
    role: str | None = env_vars.get("SNOWFLAKE_ROLE")
    warehouse: str | None = env_vars.get("SNOWFLAKE_WAREHOUSE")

    import snowflake.connector

    conn_kwargs: dict = {
        "account": account,
        "user": user,
        "password": token,
        "database": "SNOWFLAKE",
        "schema": "INFORMATION_SCHEMA",
    }
    if role:
        conn_kwargs["role"] = role
    if warehouse:
        conn_kwargs["warehouse"] = warehouse

    con = snowflake.connector.connect(**conn_kwargs)
    try:
        cursor = con.cursor()
        cursor.execute("SELECT COUNT(*) AS db_count FROM INFORMATION_SCHEMA.DATABASES")
        row = cursor.fetchone()
        count = int(row[0]) if row else 0
        csv_path.write_text(f"db_count\n{count}\n")
        print(f"  Created Snowflake count gold CSV: {csv_path} (db_count={count})")
    finally:
        con.close()


def _load_dotenv(path: Path) -> dict[str, str]:
    """Parse a .env file into a dict without mutating os.environ."""
    result: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def main() -> None:
    print("Setting up test task data...")
    _ensure_dirs()

    print("\n[1/6] SQLite DB")
    _create_sqlite_db()

    print("\n[2/6] dbt source DuckDB")
    _create_dbt_source_duckdb()

    print("\n[3/6] Gold DuckDB (dbt evaluation)")
    _create_gold_dbt_duckdb()

    print("\n[4/6] Gold CSV: test_lite_sqlite001")
    _create_gold_lite_sqlite_csv()

    print("\n[5/6] Gold CSV: test_lite_bq001")
    _create_gold_lite_bq_csv()

    print("\n[6/6] Gold CSVs: Snowflake (test_sf_current_date + test_lite_sf001)")
    _create_gold_snowflake_csv()
    _create_gold_lite_sf_csv()

    print("\nSetup complete.")


if __name__ == "__main__":
    main()
