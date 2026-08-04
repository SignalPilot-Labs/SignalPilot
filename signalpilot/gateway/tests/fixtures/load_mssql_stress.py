"""Load a multi-database SQL Server stress fixture: 8 databases, ~2 GB each.

Each database models a different business domain but shares a star-schema shape:
three large fact tables carrying the bulk of the bytes, plus ~40 dimension and
lookup tables so schema introspection has real metadata to chew through.

Data is generated server-side with set-based INSERT...SELECT over a cross-joined
tally, under SIMPLE recovery with TABLOCK, so the load is minimally logged and
never round-trips rows over the wire.

Usage:
    python load_mssql_stress.py                # load all 8, 4 at a time
    python load_mssql_stress.py --target-gb 1  # smaller/faster
    python load_mssql_stress.py --only sp_retail
    python load_mssql_stress.py --drop         # tear the databases down
"""

from __future__ import annotations

import argparse
import concurrent.futures
import time

import pymssql

HOST = "127.0.0.1"
PORT = "1434"
USER = "sa"
PWD = "Str0ng!Passw0rd"

BATCH_ROWS = 1_000_000
DEFAULT_TARGET_GB = 2.0

# ── Domain definitions ──────────────────────────────────────────────────────
# Each domain gets its own vocabulary so the eight databases do not look like
# eight copies of the same schema to the introspection layer.

DOMAINS: dict[str, dict] = {
    "sp_retail": {
        "schema": "retail",
        "grain": "order",
        "facts": ["fact_orders", "fact_order_items", "fact_returns"],
        "dims": ["customer", "product", "store", "promotion", "supplier"],
        "measures": [("amount", "DECIMAL(12,2)"), ("quantity", "INT"), ("discount", "DECIMAL(5,2)")],
        "statuses": ["placed", "picked", "shipped", "delivered", "returned", "cancelled"],
        "channels": ["web", "mobile", "store", "phone", "partner"],
    },
    "sp_finance": {
        "schema": "finance",
        "grain": "journal_entry",
        "facts": ["fact_ledger_entries", "fact_invoices", "fact_payments"],
        "dims": ["account", "cost_center", "vendor", "currency", "fiscal_period"],
        "measures": [("debit", "DECIMAL(14,2)"), ("credit", "DECIMAL(14,2)"), ("fx_rate", "DECIMAL(12,6)")],
        "statuses": ["draft", "posted", "reversed", "approved", "void"],
        "channels": ["manual", "import", "recurring", "accrual", "system"],
    },
    "sp_logistics": {
        "schema": "logistics",
        "grain": "shipment",
        "facts": ["fact_shipments", "fact_shipment_legs", "fact_exceptions"],
        "dims": ["carrier", "warehouse", "route", "vehicle", "container"],
        "measures": [("weight_kg", "DECIMAL(10,3)"), ("distance_km", "DECIMAL(10,2)"), ("cost", "DECIMAL(12,2)")],
        "statuses": ["booked", "in_transit", "customs", "delivered", "delayed", "lost"],
        "channels": ["air", "sea", "rail", "road", "courier"],
    },
    "sp_marketing": {
        "schema": "marketing",
        "grain": "touchpoint",
        "facts": ["fact_impressions", "fact_clicks", "fact_conversions"],
        "dims": ["campaign", "creative", "audience", "channel_ref", "landing_page"],
        "measures": [("spend", "DECIMAL(12,4)"), ("revenue", "DECIMAL(12,2)"), ("bid", "DECIMAL(8,4)")],
        "statuses": ["served", "viewed", "clicked", "converted", "bounced"],
        "channels": ["search", "social", "display", "email", "affiliate"],
    },
    "sp_support": {
        "schema": "support",
        "grain": "ticket",
        "facts": ["fact_tickets", "fact_ticket_events", "fact_surveys"],
        "dims": ["agent", "queue", "product_area", "sla_tier", "contact"],
        "measures": [("handle_seconds", "INT"), ("csat_score", "DECIMAL(4,2)"), ("cost", "DECIMAL(10,2)")],
        "statuses": ["new", "open", "pending", "escalated", "resolved", "closed"],
        "channels": ["email", "chat", "phone", "portal", "social"],
    },
    "sp_iot": {
        "schema": "telemetry",
        "grain": "reading",
        "facts": ["fact_sensor_readings", "fact_device_events", "fact_alerts"],
        "dims": ["device", "sensor_type", "site", "firmware", "gateway"],
        "measures": [("value", "DECIMAL(14,6)"), ("battery_pct", "DECIMAL(5,2)"), ("signal_dbm", "INT")],
        "statuses": ["ok", "warn", "critical", "stale", "offline"],
        "channels": ["mqtt", "http", "lorawan", "cellular", "wifi"],
    },
    "sp_billing": {
        "schema": "billing",
        "grain": "charge",
        "facts": ["fact_charges", "fact_subscriptions", "fact_credits"],
        "dims": ["plan", "account_ref", "coupon", "tax_region", "payment_method"],
        "measures": [("amount", "DECIMAL(12,2)"), ("tax", "DECIMAL(10,2)"), ("proration", "DECIMAL(10,4)")],
        "statuses": ["pending", "charged", "failed", "refunded", "disputed"],
        "channels": ["card", "ach", "wire", "paypal", "invoice"],
    },
    "sp_hr": {
        "schema": "people",
        "grain": "timesheet_entry",
        "facts": ["fact_timesheets", "fact_payroll_runs", "fact_absences"],
        "dims": ["employee", "department", "job_grade", "location", "benefit_plan"],
        "measures": [("hours", "DECIMAL(8,2)"), ("gross_pay", "DECIMAL(12,2)"), ("tax_withheld", "DECIMAL(10,2)")],
        "statuses": ["submitted", "approved", "rejected", "paid", "adjusted"],
        "channels": ["web", "kiosk", "mobile", "import", "manual"],
    },
}

# Extra narrow tables per database, purely to give schema introspection volume.
LOOKUP_SUFFIXES = [
    "type", "status_ref", "category", "subcategory", "region", "segment", "tier",
    "source_system", "audit_ref", "config", "mapping", "hierarchy", "attribute",
    "tag", "note", "flag", "threshold", "rule", "override", "snapshot",
    "stg_raw", "stg_clean", "stg_reject", "stg_dedup", "stg_audit",
]


def _connect(database: str = "master"):
    return pymssql.connect(
        server=HOST, port=PORT, user=USER, password=PWD,
        database=database, autocommit=True, login_timeout=10, timeout=0,
    )


def _sql_case(column: str, values: list[str], modulo: int) -> str:
    """Build a deterministic CASE that maps rn -> one of `values`."""
    whens = " ".join(
        f"WHEN {i} THEN '{v}'" for i, v in enumerate(values)
    )
    return f"CASE {column} % {modulo} {whens} ELSE '{values[0]}' END"


def _create_database(cur, db: str, target_gb: float) -> None:
    cur.execute(f"IF DB_ID('{db}') IS NULL CREATE DATABASE [{db}]")
    # SIMPLE recovery keeps the log from growing to the size of the load.
    cur.execute(f"ALTER DATABASE [{db}] SET RECOVERY SIMPLE")
    # Pre-size the data file so the load is not stalled by autogrow events.
    data_mb = int(target_gb * 1024 * 1.25)
    try:
        cur.execute(
            f"ALTER DATABASE [{db}] MODIFY FILE (NAME='{db}', SIZE={data_mb}MB, FILEGROWTH=512MB)"
        )
    except Exception:
        pass  # logical file name differs on some builds; autogrow still works
    try:
        cur.execute(
            f"ALTER DATABASE [{db}] MODIFY FILE (NAME='{db}_log', SIZE=512MB, FILEGROWTH=256MB)"
        )
    except Exception:
        pass


def _create_objects(cur, db: str, cfg: dict) -> None:
    sch = cfg["schema"]
    cur.execute(f"IF SCHEMA_ID('{sch}') IS NULL EXEC('CREATE SCHEMA {sch}')")

    # ── dimensions ──
    for dim in cfg["dims"]:
        cur.execute(f"""
        IF OBJECT_ID('{sch}.dim_{dim}') IS NULL
        CREATE TABLE {sch}.dim_{dim} (
            {dim}_id      INT NOT NULL PRIMARY KEY,
            {dim}_code    VARCHAR(24)  NOT NULL,
            {dim}_name    NVARCHAR(120) NOT NULL,
            region        VARCHAR(24)  NULL,
            segment       VARCHAR(24)  NULL,
            is_active     BIT          NOT NULL,
            valid_from    DATE         NULL,
            valid_to      DATE         NULL,
            attributes    NVARCHAR(400) NULL
        )""")

    # ── fact tables ──
    measures = cfg["measures"]
    measure_cols = ",\n            ".join(f"{n} {t} NULL" for n, t in measures)
    dim_fks = ",\n            ".join(f"{d}_id INT NULL" for d in cfg["dims"])
    for fact in cfg["facts"]:
        cur.execute(f"""
        IF OBJECT_ID('{sch}.{fact}') IS NULL
        CREATE TABLE {sch}.{fact} (
            {fact}_key    BIGINT NOT NULL,
            {dim_fks},
            {measure_cols},
            status        VARCHAR(16)  NULL,
            channel       VARCHAR(16)  NULL,
            event_date    DATE         NULL,
            created_at    DATETIME2(0) NULL,
            updated_at    DATETIME2(0) NULL,
            source_ref    VARCHAR(40)  NULL,
            notes         VARCHAR(120) NULL,
            CONSTRAINT pk_{fact} PRIMARY KEY CLUSTERED ({fact}_key)
        )""")

    # ── lookup / staging tables (metadata volume for introspection) ──
    for suffix in LOOKUP_SUFFIXES:
        cur.execute(f"""
        IF OBJECT_ID('{sch}.{cfg["grain"]}_{suffix}') IS NULL
        CREATE TABLE {sch}.{cfg["grain"]}_{suffix} (
            id            INT IDENTITY(1,1) PRIMARY KEY,
            code          VARCHAR(32)  NOT NULL,
            label         NVARCHAR(120) NULL,
            numeric_value DECIMAL(12,4) NULL,
            effective_at  DATETIME2(0) NULL,
            is_current    BIT NOT NULL DEFAULT 1
        )""")

    # ── views ──
    primary_fact = cfg["facts"][0]
    first_measure = measures[0][0]
    first_dim = cfg["dims"][0]
    cur.execute(f"""
    IF OBJECT_ID('{sch}.v_{primary_fact}_by_status') IS NULL
    EXEC('CREATE VIEW {sch}.v_{primary_fact}_by_status AS
          SELECT status, channel, COUNT_BIG(*) AS row_count,
                 SUM({first_measure}) AS total_{first_measure}
          FROM {sch}.{primary_fact}
          GROUP BY status, channel')""")
    cur.execute(f"""
    IF OBJECT_ID('{sch}.v_{primary_fact}_enriched') IS NULL
    EXEC('CREATE VIEW {sch}.v_{primary_fact}_enriched AS
          SELECT f.{primary_fact}_key, f.event_date, f.status, f.{first_measure},
                 d.{first_dim}_name, d.region
          FROM {sch}.{primary_fact} f
          LEFT JOIN {sch}.dim_{first_dim} d ON d.{first_dim}_id = f.{first_dim}_id')""")

    # ── documentation via extended properties ──
    cur.execute(f"""
    IF NOT EXISTS (SELECT 1 FROM sys.extended_properties ep
                   JOIN sys.objects o ON ep.major_id = o.object_id
                   WHERE o.name = '{primary_fact}' AND ep.minor_id = 0 AND ep.name = 'MS_Description')
    EXEC sys.sp_addextendedproperty @name=N'MS_Description',
        @value=N'Primary {cfg["grain"]} fact table for the {sch} domain',
        @level0type=N'SCHEMA', @level0name=N'{sch}',
        @level1type=N'TABLE',  @level1name=N'{primary_fact}'""")


def _seed_dimensions(cur, cfg: dict) -> None:
    sch = cfg["schema"]
    for i, dim in enumerate(cfg["dims"]):
        rows = 20_000 + i * 15_000
        cur.execute(f"SELECT COUNT_BIG(*) FROM {sch}.dim_{dim}")
        if cur.fetchone()[0] > 0:
            continue
        cur.execute(f"""
        WITH n AS (
            SELECT TOP ({rows}) ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) AS rn
            FROM sys.all_objects a CROSS JOIN sys.all_objects b
        )
        INSERT INTO {sch}.dim_{dim} WITH (TABLOCK)
            ({dim}_id, {dim}_code, {dim}_name, region, segment, is_active,
             valid_from, valid_to, attributes)
        SELECT rn,
               CONCAT('{dim[:3].upper()}-', RIGHT('000000' + CAST(rn AS VARCHAR(10)), 6)),
               CONCAT(N'{dim.title()} ', CAST(rn AS NVARCHAR(10)), N' / ',
                      {_sql_case("rn", ["Alpha", "Bravo", "Charlie", "Delta", "Echo"], 5)}),
               {_sql_case("rn", ["NORTH", "SOUTH", "EAST", "WEST", "CENTRAL", "INTL"], 6)},
               {_sql_case("rn", ["enterprise", "midmarket", "smb", "consumer"], 4)},
               CASE WHEN rn % 17 = 0 THEN 0 ELSE 1 END,
               DATEADD(day, -(rn % 2000), '2025-01-01'),
               CASE WHEN rn % 23 = 0 THEN DATEADD(day, rn % 400, '2025-01-01') END,
               REPLICATE(N'attr', 40)
        FROM n""")


def _seed_lookups(cur, cfg: dict) -> None:
    sch = cfg["schema"]
    grain = cfg["grain"]
    for suffix in LOOKUP_SUFFIXES:
        tbl = f"{sch}.{grain}_{suffix}"
        cur.execute(f"SELECT COUNT_BIG(*) FROM {tbl}")
        if cur.fetchone()[0] > 0:
            continue
        cur.execute(f"""
        WITH n AS (
            SELECT TOP (500) ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) AS rn
            FROM sys.all_objects
        )
        INSERT INTO {tbl} WITH (TABLOCK) (code, label, numeric_value, effective_at, is_current)
        SELECT CONCAT('{suffix[:4].upper()}-', rn),
               CONCAT(N'{suffix.replace("_", " ").title()} ', CAST(rn AS NVARCHAR(10))),
               rn * 1.5,
               DATEADD(hour, -rn, '2025-06-01T00:00:00'),
               CASE WHEN rn % 11 = 0 THEN 0 ELSE 1 END
        FROM n""")


def _measure_expr(typ: str, i: int) -> str:
    """Build a deterministic measure value that cannot overflow its declared type.

    DECIMAL(p,s) holds at most (p - s) integer digits, so the generated value is
    capped below 10^(p-s) rather than assuming every column is wide enough.
    """
    if typ.upper().startswith("INT"):
        return f"(rn % {500 + i * 250}) + 1"

    inner = typ[typ.index("(") + 1: typ.index(")")]
    precision, scale = (int(x.strip()) for x in inner.split(","))
    # Value is (rn % modulo + 1) / 100.0, so modulo/100 must stay under the cap.
    max_modulo = 10 ** (precision - scale) * 100 - 1
    modulo = min(9000 + i * 1000, max_modulo)
    return f"CAST(((rn % {modulo}) + 1) / 100.0 AS {typ})"


def _fact_insert_sql(cfg: dict, fact: str, start_key: int, rows: int) -> str:
    sch = cfg["schema"]
    dims = cfg["dims"]
    measures = cfg["measures"]

    dim_cols = ", ".join(f"{d}_id" for d in dims)
    dim_vals = ", ".join(f"((rn * {7 + i * 3}) % {20_000 + i * 15_000}) + 1" for i, d in enumerate(dims))

    measure_cols = ", ".join(n for n, _ in measures)
    measure_vals_sql = ", ".join(
        _measure_expr(typ, i) for i, (_name, typ) in enumerate(measures)
    )

    return f"""
    WITH n AS (
        SELECT TOP ({rows})
               {start_key} + ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) AS rn
        FROM sys.all_objects a CROSS JOIN sys.all_objects b CROSS JOIN sys.all_objects c
    )
    INSERT INTO {sch}.{fact} WITH (TABLOCK)
        ({fact}_key, {dim_cols}, {measure_cols}, status, channel,
         event_date, created_at, updated_at, source_ref, notes)
    SELECT rn,
           {dim_vals},
           {measure_vals_sql},
           {_sql_case("rn", cfg["statuses"], len(cfg["statuses"]))},
           {_sql_case("rn", cfg["channels"], len(cfg["channels"]))},
           DATEADD(day, -(rn % 1095), '2025-07-01'),
           DATEADD(minute, -(rn % 1500000), '2025-07-01T00:00:00'),
           DATEADD(minute, -(rn % 900000), '2025-07-01T00:00:00'),
           CONCAT('{cfg["schema"][:3].upper()}-SRC-', RIGHT('0000000000' + CAST(rn AS VARCHAR(12)), 10)),
           CONCAT('{cfg["grain"]} ', CAST(rn AS VARCHAR(12)), ' ',
                  {_sql_case("rn", ["standard processing", "manual review applied",
                                    "auto-approved by rule engine", "backdated adjustment",
                                    "partner-submitted record"], 5)})
    FROM n"""


def _db_size_mb(cur) -> float:
    cur.execute(
        "SELECT CAST(ISNULL(SUM(used_page_count), 0) * 8.0 / 1024 AS FLOAT) "
        "FROM sys.dm_db_partition_stats"
    )
    return float(cur.fetchone()[0] or 0.0)


def _create_secondary_indexes(cur, cfg: dict) -> None:
    """Built after the load — index maintenance during bulk insert is wasteful."""
    sch = cfg["schema"]
    lead_dim = cfg["dims"][0]
    for fact in cfg["facts"]:
        for name, cols in (
            (f"ix_{fact}_event_date", "event_date, status"),
            (f"ix_{fact}_{lead_dim}", f"{lead_dim}_id, event_date"),
        ):
            cur.execute(f"""
            IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = '{name}')
            CREATE INDEX {name} ON {sch}.{fact} ({cols})""")


def load_database(db: str, target_gb: float, quiet: bool = False) -> dict:
    cfg = DOMAINS[db]
    t0 = time.time()

    with _connect("master") as conn:
        _create_database(conn.cursor(), db, target_gb)

    with _connect(db) as conn:
        cur = conn.cursor()
        _create_objects(cur, db, cfg)
        _seed_dimensions(cur, cfg)
        _seed_lookups(cur, cfg)

        # The two secondary indexes per fact table add ~20% after the load, so
        # fill to 83% of target and let index creation bring it up to size.
        target_mb = target_gb * 1024 * 0.83
        # Round-robin across the fact tables so all three carry real volume.
        keys = dict.fromkeys(cfg["facts"], 0)
        idx = 0
        size = _db_size_mb(cur)
        while size < target_mb:
            fact = cfg["facts"][idx % len(cfg["facts"])]
            remaining_mb = target_mb - size
            # ~135 bytes/row before indexes; shrink the last batch to avoid overshoot.
            est_rows = int(remaining_mb * 1024 * 1024 / 135)
            rows = max(50_000, min(BATCH_ROWS, est_rows))
            cur.execute(_fact_insert_sql(cfg, fact, keys[fact], rows))
            keys[fact] += rows
            idx += 1
            size = _db_size_mb(cur)
            if not quiet:
                print(f"  [{db}] {size:8.0f} MB / {target_mb:.0f} MB  (+{rows:,} -> {fact})", flush=True)

        _create_secondary_indexes(cur, cfg)
        cur.execute("EXEC sp_updatestats")
        final_mb = _db_size_mb(cur)

        cur.execute("""
            SELECT COUNT(*) FROM sys.objects
            WHERE type IN ('U','V') AND OBJECTPROPERTY(object_id,'IsMSShipped') = 0""")
        objects = cur.fetchone()[0]
        cur.execute("SELECT ISNULL(SUM(row_count),0) FROM sys.dm_db_partition_stats WHERE index_id IN (0,1)")
        total_rows = cur.fetchone()[0]

    return {
        "database": db,
        "size_mb": round(final_mb, 1),
        "objects": objects,
        "rows": int(total_rows),
        "seconds": round(time.time() - t0, 1),
    }


def drop_all() -> None:
    with _connect("master") as conn:
        cur = conn.cursor()
        for db in DOMAINS:
            cur.execute(f"""
                IF DB_ID('{db}') IS NOT NULL
                BEGIN
                    ALTER DATABASE [{db}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
                    DROP DATABASE [{db}];
                END""")
            print(f"dropped {db}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target-gb", type=float, default=DEFAULT_TARGET_GB)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--only", action="append", help="load only these databases")
    ap.add_argument("--drop", action="store_true")
    args = ap.parse_args()

    if args.drop:
        drop_all()
        return

    targets = args.only or list(DOMAINS)
    bad = [d for d in targets if d not in DOMAINS]
    if bad:
        raise SystemExit(f"unknown database(s): {bad}")

    print(f"loading {len(targets)} databases @ {args.target_gb} GB "
          f"({args.workers} concurrent)", flush=True)
    t0 = time.time()
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(load_database, d, args.target_gb): d for d in targets}
        for fut in concurrent.futures.as_completed(futures):
            db = futures[fut]
            try:
                r = fut.result()
                results.append(r)
                print(f"DONE {r['database']}: {r['size_mb']} MB, {r['objects']} objects, "
                      f"{r['rows']:,} rows, {r['seconds']}s", flush=True)
            except Exception as e:
                print(f"FAILED {db}: {e}", flush=True)

    total_mb = sum(r["size_mb"] for r in results)
    print(f"\nloaded {len(results)}/{len(targets)} databases, "
          f"{total_mb / 1024:.2f} GB total, {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
