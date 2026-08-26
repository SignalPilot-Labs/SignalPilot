"""Seed the dockerized SQL Server with a small analytics schema for connector e2e tests."""
import sys
import time

import pymssql

HOST, PORT, USER, PWD = "127.0.0.1", 1434, "sa", "Str0ng!Passw0rd"

# ── wait for readiness ──────────────────────────────────────────────────────
deadline = time.time() + 300
last = None
while time.time() < deadline:
    try:
        c = pymssql.connect(server=HOST, port=str(PORT), user=USER, password=PWD,
                            database="master", login_timeout=5)
        c.close()
        print("SQL Server ready")
        break
    except Exception as e:
        last = e
        time.sleep(5)
else:
    print(f"NOT READY: {last}")
    sys.exit(1)

conn = pymssql.connect(server=HOST, port=str(PORT), user=USER, password=PWD,
                       database="master", autocommit=True)
cur = conn.cursor()
cur.execute("IF DB_ID('sp_test') IS NULL CREATE DATABASE sp_test")
cur.close()
conn.close()

conn = pymssql.connect(server=HOST, port=str(PORT), user=USER, password=PWD,
                       database="sp_test", autocommit=True)
cur = conn.cursor()

DDL = [
    "IF SCHEMA_ID('analytics') IS NULL EXEC('CREATE SCHEMA analytics')",
    """IF OBJECT_ID('analytics.customers') IS NULL
       CREATE TABLE analytics.customers (
           customer_id INT IDENTITY(1,1) PRIMARY KEY,
           name NVARCHAR(100) NOT NULL,
           region VARCHAR(50) NULL,
           lifetime_value DECIMAL(12,2) NULL DEFAULT 0,
           created_at DATETIME2 NULL
       )""",
    """IF OBJECT_ID('analytics.orders') IS NULL
       CREATE TABLE analytics.orders (
           order_id INT IDENTITY(1,1) PRIMARY KEY,
           customer_id INT NOT NULL,
           amount DECIMAL(10,2) NOT NULL,
           status VARCHAR(20) NULL,
           ordered_at DATETIME2 NULL,
           CONSTRAINT fk_orders_customer FOREIGN KEY (customer_id)
               REFERENCES analytics.customers(customer_id)
       )""",
    """IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='ix_orders_customer')
       CREATE INDEX ix_orders_customer ON analytics.orders(customer_id, status)""",
    """IF OBJECT_ID('analytics.v_customer_totals') IS NULL
       EXEC('CREATE VIEW analytics.v_customer_totals AS
             SELECT c.customer_id, c.name, SUM(o.amount) AS total_amount
             FROM analytics.customers c
             LEFT JOIN analytics.orders o ON o.customer_id = c.customer_id
             GROUP BY c.customer_id, c.name')""",
]
for stmt in DDL:
    cur.execute(stmt)

# extended properties -> exercised as column/table comments in schema introspection
cur.execute("""
IF NOT EXISTS (SELECT 1 FROM sys.extended_properties ep
               JOIN sys.objects o ON ep.major_id=o.object_id
               WHERE o.name='customers' AND ep.minor_id=0 AND ep.name='MS_Description')
EXEC sys.sp_addextendedproperty @name=N'MS_Description',
    @value=N'Customer master table',
    @level0type=N'SCHEMA', @level0name=N'analytics',
    @level1type=N'TABLE',  @level1name=N'customers'
""")
cur.execute("""
IF NOT EXISTS (SELECT 1 FROM sys.extended_properties ep
               JOIN sys.columns c ON ep.major_id=c.object_id AND ep.minor_id=c.column_id
               WHERE c.name='region' AND ep.name='MS_Description')
EXEC sys.sp_addextendedproperty @name=N'MS_Description',
    @value=N'Sales region code',
    @level0type=N'SCHEMA', @level0name=N'analytics',
    @level1type=N'TABLE',  @level1name=N'customers',
    @level2type=N'COLUMN', @level2name=N'region'
""")

cur.execute("SELECT COUNT(*) FROM analytics.customers")
if cur.fetchone()[0] == 0:
    cur.executemany(
        "INSERT INTO analytics.customers (name, region, lifetime_value, created_at) "
        "VALUES (%s, %s, %s, %s)",
        [("Acme Corp", "NORTH", 15000.50, "2024-01-15"),
         ("Globex", "SOUTH", 8200.00, "2024-02-20"),
         ("Initech", "NORTH", 42100.75, "2024-03-10"),
         ("Umbrella", "WEST", 500.00, "2024-04-05"),
         ("Stark Ind", "EAST", 99000.00, "2024-05-01")],
    )
    cur.executemany(
        "INSERT INTO analytics.orders (customer_id, amount, status, ordered_at) "
        "VALUES (%s, %s, %s, %s)",
        [(1, 250.00, "shipped", "2024-06-01"), (1, 1300.50, "pending", "2024-06-05"),
         (2, 75.25, "shipped", "2024-06-07"), (3, 9000.00, "shipped", "2024-06-09"),
         (3, 120.00, "cancelled", "2024-06-11"), (4, 60.00, "pending", "2024-06-12"),
         (5, 15000.00, "shipped", "2024-06-15")],
    )

# force stats so dm_db_stats_properties returns rows
cur.execute("UPDATE STATISTICS analytics.customers")
cur.execute("UPDATE STATISTICS analytics.orders")

cur.execute("SELECT COUNT(*) FROM analytics.customers")
print("customers:", cur.fetchone()[0])
cur.execute("SELECT COUNT(*) FROM analytics.orders")
print("orders:", cur.fetchone()[0])

# read-only login used to prove governance is not the only defense
cur.execute("""
IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name='sp_reader')
BEGIN
    CREATE LOGIN sp_reader WITH PASSWORD='R3ader!Pass', CHECK_POLICY=OFF;
END
""")
cur.execute("""
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name='sp_reader')
BEGIN
    CREATE USER sp_reader FOR LOGIN sp_reader;
    ALTER ROLE db_datareader ADD MEMBER sp_reader;
    GRANT VIEW DEFINITION TO sp_reader;
END
""")
print("seed complete")
cur.close()
conn.close()
