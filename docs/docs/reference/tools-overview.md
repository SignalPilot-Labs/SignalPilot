---
sidebar_position: 1
---

# Tools Reference

All 40 SignalPilot MCP tools across 9 categories. The catalog below groups every tool by category (click a category for full parameter and example documentation). The [Tools by workflow stage](#tools-by-workflow-stage) section then maps the same tools onto the four stages of a governed dbt/SQL run — Scan/Map, Explore/Research, Write, and Verify.

## Tools by workflow stage

The dbt-workflow skill's steps collapse into four stages. Some scan/map and value-check operations run as bundled plugin CLI scripts (`scan_project.py`, `validate_project.py`, `map-columns`, `verify-values`) rather than MCP tools; the tables below list the MCP tools used at each stage by exact name. A tool can appear in more than one stage.

### Scan / Map

Establish the shape of the database and project before writing anything: connections, table inventory, FK map, and data-driven date boundaries.

| Tool | Role in this stage |
|------|--------------------|
| `get_knowledge` | Load baseline org/project knowledge before the scan |
| `list_database_connections` | Confirm the target connection exists by name |
| `connection_health` | Confirm the connection is reachable before querying |
| `list_tables` | Enumerate available tables in the connection |
| `schema_overview` | High-level shape: table count, rows, FK density, hub tables |
| `schema_statistics` | Aggregate table sizes and FK connectivity |
| `get_relationships` | FK/ERD map of the project |
| `get_date_boundaries` | Data-driven date floor/ceiling (replaces `current_date` hazards) |

Plugin CLI in this stage: `scan_project.py`, `validate_project.py`.

### Explore / Research

Confirm grain, discover categorical vocabularies, derive join paths, and preview JOIN behavior before committing to SQL.

| Tool | Role in this stage |
|------|--------------------|
| `query_database` | `COUNT(*)` / `COUNT(DISTINCT key)` for grain; `SELECT DISTINCT` on status/flag columns |
| `explore_table` | Deep-dive an upstream table's columns, FK refs, and samples |
| `explore_columns` | Inspect specific columns' types, stats, and samples |
| `explore_column` | Distinct values for a single categorical column (drives `CASE WHEN` vocabulary) |
| `describe_table` | Column types and nullability for an upstream |
| `schema_link` | Find tables relevant to the task question (NL → schema) |
| `find_join_path` | Derive multi-table join paths |
| `analyze_grain` | Confirm candidate-key uniqueness / fan-out on upstreams |
| `compare_join_types` | Preview INNER/LEFT/RIGHT/FULL row counts to choose the JOIN |
| `query_history` | Reuse prior successful query patterns |
| `search_knowledge` | Pull task-relevant prior research |

### Write

Scaffold the model, validate and cost-check SQL against the live schema, and parse build errors while iterating.

| Tool | Role in this stage |
|------|--------------------|
| `generate_sql_skeleton` | Scaffold a model's SQL shape from its YML column list |
| `validate_sql` | Syntax/semantic check against live schema before materializing |
| `explain_query` | Plan check before running |
| `estimate_query_cost` | Dry-run cost guardrail on expensive queries |
| `check_budget` | Remaining session query budget |
| `query_database` | Spot-check intermediate logic while building |
| `debug_cte_query` | Localize errors inside a `WITH` query during build |
| `dbt_error_parser` | Turn `dbt run`/`parse` stderr into a structured fix |

Plugin CLI in this stage: `map-columns`, then `dbt run --select <models>`.

### Verify

Post-build checks against YML contract and source data: column match, row counts, aggregate values, grain, and JOIN diagnosis.

| Tool | Role in this stage |
|------|--------------------|
| `check_model_schema` | Actual vs YML columns (missing/extra/case) |
| `validate_model_output` | Post-build row count vs source/expected (fan-out, empty model) |
| `audit_model_sources` | Full cardinality + NULL/constant column + grain audit |
| `verify_model_values` | Model aggregates vs independent `COUNT(*)`/`COUNT(DISTINCT)` on sources |
| `analyze_grain` | Re-confirm output grain/uniqueness |
| `compare_join_types` | Diagnose a row-count FAIL traced to JOIN choice |
| `query_database` | Verifier subagents' read-only cross-checks |
| `dbt_error_parser` | Parse errors from rebuilds triggered by FAILs |
| `propose_knowledge` | Record learnings after the run |

Plugin CLI in this stage: `verify-values`. Subagents: verifier, value-verifier.

### Reporting / Notebooks (outside the four stages)

Used when the task asks for a notebook deliverable or a published report. `connector_capabilities` is a feature-flag probe usable at any stage.

| Tool | Role |
|------|------|
| `list_workspace_projects` | List notebook workspace projects |
| `run_notebook` | Execute an analysis notebook in a sandboxed cloud pod |
| `list_notion_integrations` | List configured Notion integrations |
| `notion_search` | Search Notion source pages |
| `notion_fetch_page` | Fetch full content of a Notion page |
| `notion_create_page` | Publish a report page under the configured destination |
| `connector_capabilities` | Connector tier / feature-flag probe (any stage) |

---

## Full catalog by category

## Query Intelligence (7 tools)

See [Query Intelligence tools](/docs/reference/tools-query).

| Tool | Description |
|------|-------------|
| `query_database` | Execute governed, read-only SQL with auto-LIMIT, DDL blocking, dangerous function blocking, audit, PII redaction |
| `validate_sql` | Syntax + semantic validation via EXPLAIN (no execution, no budget charge) |
| `explain_query` | Execution plan with row estimates and cost warnings |
| `estimate_query_cost` | Dry-run cost estimate before executing (BigQuery: exact bytes) |
| `debug_cte_query` | Break CTE query into steps, validate each independently |
| `check_budget` | Remaining query budget for a session |
| `query_history` | Recent successful queries for a connection (session memory) |

## Schema & Exploration (10 tools)

See [Schema & Exploration tools](/docs/reference/tools-schema).

| Tool | Description |
|------|-------------|
| `list_tables` | Compact one-line-per-table overview: columns, PKs, FKs, row counts |
| `describe_table` | Full column details: types, nullability, PKs, annotations, PII flags |
| `explore_table` | Deep-dive: column details + FK refs + sample values + referenced tables |
| `explore_column` | Distinct values with counts, NULL stats, optional LIKE filter |
| `explore_columns` | Multi-column stats: distinct counts, uniqueness, min/max/avg, samples |
| `schema_overview` | Database-wide summary: table count, total rows, FK density, hub tables |
| `schema_ddl` | Full schema as CREATE TABLE DDL with FK constraints |
| `schema_statistics` | High-level stats: table sizes, FK connectivity (sorted by row count) |
| `schema_diff` | Compare current schema against last cached version (DDL changes) |
| `get_date_boundaries` | MIN/MAX dates across all DATE/TIMESTAMP columns |

## Relationships (3 tools)

See [Schema & Exploration tools](/docs/reference/tools-schema).

| Tool | Description |
|------|-------------|
| `get_relationships` | Full ERD: all FK relationships as arrows or adjacency list |
| `find_join_path` | FK-based join path discovery between two tables (1–6 hops) |
| `schema_link` | Find tables relevant to a natural-language question (NL → schema) |

## dbt & Verification (8 tools)

See [dbt tools](/docs/reference/tools-dbt).

| Tool | Description |
|------|-------------|
| `dbt_error_parser` | Parse raw dbt error output into structured diagnosis + fix suggestion |
| `generate_sql_skeleton` | Generate a SQL template from YML column spec + ref tables |
| `check_model_schema` | Compare materialized columns vs YML-declared columns |
| `validate_model_output` | Row count validation + fan-out detection + empty model detection |
| `verify_model_values` | Cross-validate model aggregate values against raw source data |
| `audit_model_sources` | Upstream audit: source row counts, fan-out/over-filter ratios, NULL scan |
| `analyze_grain` | Cardinality analysis: per-key distinct counts, fan-out factors |
| `compare_join_types` | Compare row counts across INNER/LEFT/RIGHT/FULL OUTER JOIN |

## Workspaces (2 tools)

See [Operational tools](/docs/reference/tools-ops).

| Tool | Description |
|------|-------------|
| `list_workspace_projects` | List the dbt/notebook projects in the user's workspace |
| `run_notebook` | Run a `.py` notebook in a sandboxed cloud pod, return output + view URL |

## Knowledge Base (3 tools)

See [Operational tools](/docs/reference/tools-ops).

| Tool | Description |
|------|-------------|
| `get_knowledge` | Load baseline docs + task-relevant knowledge entries |
| `search_knowledge` | Agent-directed search across the knowledge base |
| `propose_knowledge` | Propose a new knowledge entry, or edit one in place with `overwrite=true` |
| `archive_knowledge` | Archive (soft-delete) a knowledge entry by ID |
| `manage_report` | Create or permanently delete a rendered HTML report |

## Notion Integration (4 tools)

See [Operational tools](/docs/reference/tools-ops).

| Tool | Description |
|------|-------------|
| `list_notion_integrations` | List configured Notion integrations with search scope and report destination |
| `notion_search` | Search Notion pages visible to an integration's access token |
| `notion_fetch_page` | Fetch full content of a Notion page by ID |
| `notion_create_page` | Create a page under the configured report destination |

## Connections (3 tools)

See [Operational tools](/docs/reference/tools-ops).

| Tool | Description |
|------|-------------|
| `list_database_connections` | List all configured database connections |
| `connection_health` | Latency percentiles (p50/p95/p99), error rates, status per connection |
| `connector_capabilities` | Connector tier classification (Tier 1/2/3) and available features |

---

## Removed tools

The following tools were removed because the gateway runs in Docker and cannot access local filesystems. Their functionality is available via standalone scripts in the plugin:

- `execute_code` / `sandbox_status` — sandbox disabled in cloud
- `dbt_project_map` / `dbt_project_validate` — use `scan_project.py` and `validate_project.py` in the plugin
- `fix_date_spine_hazards` / `fix_nondeterminism_hazards` — use the `dbt-date-spines` skill
- `create_project` — use the web UI or API
