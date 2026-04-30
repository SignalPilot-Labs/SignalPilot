---
sidebar_position: 9
---

# Connect a Database

SignalPilot supports 7 SQL dialects out of the box.

## Supported databases

| Database | Dialect | Cloud support |
|----------|---------|---------------|
| PostgreSQL | `postgresql` | Yes |
| MySQL | `mysql` | Yes |
| SQLite | `sqlite` | Local only |
| SQL Server | `mssql` | Yes |
| Snowflake | `snowflake` | Yes |
| Databricks | `databricks` | Yes |
| BigQuery | `bigquery` | Yes |

## Adding a connection

Use the `list_database_connections` tool to see existing connections, or ask your AI agent:

> "Connect to my PostgreSQL database at host=db.example.com port=5432 dbname=analytics user=readonly"

The agent will use the appropriate MCP tool to register the connection. Credentials are encrypted at rest with AES-GCM.

## Connection health

Use the `connection_health` tool to check if a connection is reachable and responding.

## Cloud warehouse notes

For cloud warehouses (Snowflake, Databricks, BigQuery), SignalPilot validates connection parameters against known hostnames to prevent SSRF attacks. Only legitimate warehouse endpoints are allowed.
