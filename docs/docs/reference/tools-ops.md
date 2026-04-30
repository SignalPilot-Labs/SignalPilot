---
sidebar_position: 5
---

# Operational Tools

4 operational tools and 2 project-management tools.

---

## Operational

### list_database_connections

List all configured database connections in the gateway.

**Parameters:** None (uses current auth context to scope to the org).

**Returns:** List of connections: name, database type, host/database, status, last-seen.

**When to use:** First call in any session. Confirm which connections are available before calling any other tool.

---

### connection_health

Latency percentiles and error rates for all or a specific connection.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `connection` | string | No | Connection name (omit for all connections) |

**Returns:** Per-connection: p50/p95/p99 latency, error rate (last 100 queries), current status (healthy/degraded/unreachable).

---

### connector_capabilities

Connector tier classification and feature availability for a connection.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `connection` | string | Yes | Connection name |

**Returns:** Tier (1/2/3), available features (cost estimation, explain plan, schema stats, etc.), dialect.

**Tier breakdown:**

| Tier | Connectors | Features |
|------|-----------|---------|
| 1 | PostgreSQL, DuckDB, Snowflake, BigQuery | Full: cost estimation, explain, schema stats, FK discovery |
| 2 | MySQL, SQLite, SQL Server | Partial: explain and schema stats, limited cost estimation |
| 3 | Databricks | Basic: query execution and schema, limited explain |

---

### check_budget

Remaining query budget for the current session.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `connection` | string | Yes | Connection name |

**Returns:** Budget cap (USD), amount spent this session, amount remaining. Applies to warehouses that report scan cost (BigQuery, Snowflake).

---

## Project Management

### list_projects

List all registered dbt projects.

**Parameters:** None.

**Returns:** List of dbt projects: name, path, last-scanned timestamp, model count.

---

### get_project

Get details of a specific dbt project.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project` | string | Yes | Project name |

**Returns:** Project path, dbt version, adapter, model count, source count, test count, last-scanned timestamp.
