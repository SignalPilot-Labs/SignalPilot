---
sidebar_position: 5
---

# Connect a Database

SignalPilot supports 7 SQL dialects. Connections are encrypted at rest with AES-GCM.

## Supported databases

| Database | Dialect | Cloud support | Tier |
|----------|---------|---------------|------|
| PostgreSQL | `postgresql` | Yes | 1 |
| DuckDB | `duckdb` | Local | 1 |
| Snowflake | `snowflake` | Yes | 1 |
| BigQuery | `bigquery` | Yes | 1 |
| MySQL | `mysql` | Yes | 2 |
| SQLite | `sqlite` | Local only | 2 |
| SQL Server | `mssql` | Yes | 2 |
| Databricks | `databricks` | Yes | 3 |

## Add a connection via the web UI

Go to `http://localhost:3200` → Connections → Add Connection. Fill in the connection details for your database type.

## Add a connection via API

```bash
curl -X POST http://localhost:3300/api/connections \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-warehouse",
    "db_type": "duckdb",
    "database": "/path/to/warehouse.duckdb"
  }'
```

## Connection examples by dialect

### PostgreSQL

```json
{
  "name": "prod-postgres",
  "db_type": "postgresql",
  "host": "db.example.com",
  "port": 5432,
  "database": "analytics",
  "username": "readonly",
  "password": "..."
}
```

**Recommended:** Create a read-only PostgreSQL user — the gateway enforces read-only at the SQL level, but defense-in-depth is good practice.

### MySQL

```json
{
  "name": "prod-mysql",
  "db_type": "mysql",
  "host": "db.example.com",
  "port": 3306,
  "database": "analytics",
  "username": "readonly",
  "password": "..."
}
```

### SQLite

```json
{
  "name": "local-sqlite",
  "db_type": "sqlite",
  "database": "/data/analytics.db"
}
```

SQLite connections are local-only (the gateway must have filesystem access to the `.db` file).

### SQL Server

```json
{
  "name": "prod-mssql",
  "db_type": "mssql",
  "host": "sqlserver.example.com",
  "port": 1433,
  "database": "Analytics",
  "username": "readonly",
  "password": "..."
}
```

### Snowflake

```json
{
  "name": "prod-snowflake",
  "db_type": "snowflake",
  "account": "xy12345.us-east-1",
  "database": "ANALYTICS",
  "warehouse": "COMPUTE_WH",
  "role": "ANALYST",
  "username": "...",
  "password": "..."
}
```

### Databricks

```json
{
  "name": "prod-databricks",
  "db_type": "databricks",
  "host": "adb-1234567890.azuredatabricks.net",
  "http_path": "/sql/1.0/warehouses/abcdef123456",
  "access_token": "..."
}
```

### BigQuery

```json
{
  "name": "prod-bigquery",
  "db_type": "bigquery",
  "project": "my-gcp-project",
  "dataset": "analytics",
  "credentials_json": "{...service account JSON...}"
}
```

## Environment variables for connections

For self-hosted deployments, you can pre-configure connections via environment variables instead of the API. See [Configuration](/docs/setup/configuration) for the variable names.

## SSH tunneling

For databases that are not directly reachable from the gateway container, SSH tunneling is supported:

```json
{
  "name": "tunneled-postgres",
  "db_type": "postgresql",
  "host": "db.internal.example.com",
  "port": 5432,
  "database": "analytics",
  "username": "readonly",
  "password": "...",
  "ssh_tunnel": {
    "host": "bastion.example.com",
    "port": 22,
    "username": "ec2-user",
    "private_key": "-----BEGIN OPENSSH PRIVATE KEY-----..."
  }
}
```

## SSRF allow-list (cloud mode)

In cloud mode, cloud warehouse connection parameters are validated against an allow-list of known hostnames to prevent SSRF attacks. The default allow-list covers:

- `*.snowflakecomputing.com`
- `*.databricks.com` / `*.azuredatabricks.net`
- `bigquery.googleapis.com`

Self-hosted deployments can extend this list via `SP_SSRF_ALLOW_LIST`.

## Connection health

```
Tool: connection_health
→ prod-snowflake: p50=42ms, p95=180ms, p99=450ms, error_rate=0.1%
→ dev-duckdb: p50=2ms, p95=8ms, p99=15ms, error_rate=0.0%
```

Use `connection_health` to verify all connections are reachable and responding within acceptable latency.
