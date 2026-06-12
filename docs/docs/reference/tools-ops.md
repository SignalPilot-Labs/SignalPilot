---
sidebar_position: 5
---

# Operational Tools

Connections (3), Workspaces (2), Knowledge Base (3), and Notion (4) tools.

> `check_budget` lives on the [Query Intelligence](/docs/reference/tools-query) reference.

---

## Connections

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

## Workspaces

### list_workspace_projects

List the dbt and notebook projects available in the user's workspace.

**Parameters:** None (uses current auth context to scope to the user/org).

**Returns:** List of workspace projects with name and type.

---

### run_notebook

Run a `.py` notebook in a sandboxed cloud Kubernetes pod. Writes the notebook into the user's notebook workspace and executes it with `sp export session`.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `filename` | string | Yes | Name of the `.py` file (e.g. `analysis.py`), relative path inside the workspace |
| `code` | string | Yes | Full contents of the `.py` notebook file |
| `agent_branch` | string | No | Deprecated legacy label; ignored for project routing |

**Returns:** stdout/stderr from the run plus a URL to view the notebook in the browser.

**Sandboxing:** Notebook pods run under gVisor with per-org NetworkPolicy isolation, read-only rootfs, and blocked IMDS egress. See [Security](/docs/security).

---

## Knowledge Base

### get_knowledge

Load baseline knowledge docs plus task-relevant entries for a session.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `task_description` | string | No | Task text used to surface relevant entries |

**Returns:** Baseline docs (understanding, conventions) plus matching task-relevant docs.

---

### search_knowledge

Agent-directed search across the knowledge base.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | Yes | Search query (max 200 chars) |
| `scope` | string | No | Scope filter |
| `scope_ref` | string | No | Scope reference (e.g. project name) |
| `category` | string | No | Category filter |
| `limit` | integer | No | Max results (default: 20, capped at 50) |

**Returns:** Matching docs: ID, scope, category, title, and a snippet.

---

### propose_knowledge

Propose a new knowledge entry after a run. Entries are auto-accepted.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `scope` | string | Yes | Scope (e.g. `org`, `project`) |
| `scope_ref` | string | No | Scope reference |
| `category` | string | Yes | One of: understanding, conventions, decisions, domain-rules, debugging, quirks |
| `title` | string | Yes | Entry title |
| `body` | string | Yes | Entry body |
| `supersedes` | string | No | ID of a doc this entry replaces |

**Returns:** Confirmation with the new doc ID.

---

## Notion Integration

### list_notion_integrations

List configured Notion integrations with their search scope and report destination.

**Parameters:** None.

**Returns:** Per-integration: name, search scope, report destination.

---

### notion_search

Search Notion pages visible to an integration's access token.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `integration_name` | string | Yes | Configured Notion integration name |
| `query` | string | Yes | Search query |

**Returns:** Matching Notion pages with IDs and titles.

---

### notion_fetch_page

Fetch the full content of a Notion page by ID.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `integration_name` | string | Yes | Configured Notion integration name |
| `page_id` | string | Yes | Notion page ID |

**Returns:** Full page content.

---

### notion_create_page

Create a page under the integration's configured report destination.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `integration_name` | string | Yes | Configured Notion integration name |
| `title` | string | Yes | Page title |
| `content` | string | Yes | Page content |

**Returns:** Created page ID and URL.
