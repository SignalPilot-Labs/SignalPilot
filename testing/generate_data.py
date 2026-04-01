#!/usr/bin/env python3
"""
SignalPilot Test Data Generator
================================
Fills the enterprise-pg and warehouse-pg Docker databases with ~5GB of
realistic fake company data using Faker + psycopg COPY.

Prerequisites:
    pip install psycopg[binary] faker

Usage:
    # Start databases first
    cd testing && docker compose up -d

    # Wait for healthy, then generate data
    python generate_data.py

    # Or generate only one database:
    python generate_data.py --enterprise-only
    python generate_data.py --warehouse-only

    # Use smaller dataset for quick testing:
    python generate_data.py --scale 0.01
"""

import argparse
import sys
import time

from datagen.config import COUNTS, ENTERPRISE_DB, WAREHOUSE_DB
from datagen.db import connect


def wait_for_db(db_config: dict, label: str, retries: int = 30, delay: float = 2.0):
    """Wait for a database to be ready."""
    import psycopg
    for attempt in range(1, retries + 1):
        try:
            conn = connect(db_config)
            conn.execute("SELECT 1")
            conn.close()
            print(f"  {label}: ready")
            return
        except Exception as e:
            if attempt == retries:
                print(f"  {label}: FAILED after {retries} attempts — {e}")
                sys.exit(1)
            sys.stdout.write(f"\r  {label}: waiting... (attempt {attempt}/{retries})")
            sys.stdout.flush()
            time.sleep(delay)
    print()


def apply_scale(scale: float):
    """Scale all row counts by a factor (e.g., 0.1 for 10% size)."""
    for field in COUNTS.__dataclass_fields__:
        if field == "dim_dates_years":
            continue  # always keep full date range
        val = getattr(COUNTS, field)
        setattr(COUNTS, field, max(10, int(val * scale)))


def generate_enterprise():
    """Generate all enterprise OLTP tables."""
    from datagen.enterprise import (
        generate_employees,
        generate_products,
        generate_customers,
        generate_orders,
        generate_order_items,
        generate_payments,
        generate_support_tickets,
        generate_sensitive_tables,
        generate_audit_log,
    )

    print("\n== Enterprise OLTP Database ==")
    conn = connect(ENTERPRISE_DB)

    # Order matters: employees & products first (referenced by orders)
    generate_employees(conn)
    generate_products(conn)
    generate_customers(conn)
    generate_orders(conn)
    generate_order_items(conn)
    generate_payments(conn)
    generate_support_tickets(conn)
    generate_sensitive_tables(conn)
    generate_audit_log(conn)

    # Print DB size
    with conn.cursor() as cur:
        cur.execute("SELECT pg_database_size(current_database())")
        size_bytes = cur.fetchone()[0]
    print(f"\n  Enterprise DB size: {size_bytes / (1024**3):.2f} GB")
    conn.close()


def generate_warehouse():
    """Generate all warehouse analytics tables."""
    from datagen.warehouse import (
        generate_dim_dates,
        generate_dim_channels,
        generate_dim_customers,
        generate_dim_products,
        generate_dim_employees,
        generate_fact_sales,
        generate_fact_web_events,
        generate_fact_inventory,
        generate_raw_events,
        generate_raw_transactions,
        generate_ml_tables,
    )

    print("\n== Analytics Warehouse Database ==")
    conn = connect(WAREHOUSE_DB)

    # Dimensions first (referenced by facts)
    date_keys = generate_dim_dates(conn)
    num_channels = generate_dim_channels(conn)
    generate_dim_customers(conn)
    generate_dim_products(conn)
    generate_dim_employees(conn)

    # Facts
    generate_fact_sales(conn, date_keys)
    generate_fact_web_events(conn, date_keys)
    generate_fact_inventory(conn, date_keys)

    # Raw landing zone
    generate_raw_events(conn, date_keys)
    generate_raw_transactions(conn, date_keys)

    # ML tables
    generate_ml_tables(conn)

    # Print DB size
    with conn.cursor() as cur:
        cur.execute("SELECT pg_database_size(current_database())")
        size_bytes = cur.fetchone()[0]
    print(f"\n  Warehouse DB size: {size_bytes / (1024**3):.2f} GB")
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Generate fake enterprise data for SignalPilot testing")
    parser.add_argument("--scale", type=float, default=1.0,
                        help="Scale factor for row counts (0.01=tiny, 0.1=small, 1.0=full ~5GB)")
    parser.add_argument("--enterprise-only", action="store_true",
                        help="Only generate enterprise OLTP data")
    parser.add_argument("--warehouse-only", action="store_true",
                        help="Only generate warehouse analytics data")
    args = parser.parse_args()

    if args.scale != 1.0:
        apply_scale(args.scale)
        print(f"Scale factor: {args.scale}x")

    print("Row counts:")
    for field in COUNTS.__dataclass_fields__:
        print(f"  {field}: {getattr(COUNTS, field):,}")

    print("\nWaiting for databases...")
    do_enterprise = not args.warehouse_only
    do_warehouse = not args.enterprise_only

    if do_enterprise:
        wait_for_db(ENTERPRISE_DB, "enterprise-pg")
    if do_warehouse:
        wait_for_db(WAREHOUSE_DB, "warehouse-pg")

    overall_start = time.time()

    if do_enterprise:
        generate_enterprise()
    if do_warehouse:
        generate_warehouse()

    elapsed = time.time() - overall_start
    print(f"\nTotal generation time: {elapsed / 60:.1f} minutes")
    print("Done!")


if __name__ == "__main__":
    main()
