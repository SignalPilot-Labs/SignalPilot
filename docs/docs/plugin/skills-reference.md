---
sidebar_position: 3
---

# Skills Reference

Complete reference for all 23 SignalPilot plugin skills plus the 2 verifier agents. Each skill is a markdown knowledge file whose frontmatter `description` is its load trigger. Skills run on both the Claude Code plugin and the Codex plugin.

## Skills

| Skill | When it loads | What it covers |
|-------|---------------|----------------|
| `signalpilot` | FIRST tool call when a message mentions dbt, SQL, database, or data pipeline (blocking requirement). | The SignalPilot MCP tools, the available skills, and the governed workflow for dbt projects, SQL queries, schema discovery, and database access. |
| `dbt-workflow` | FIRST, before any dbt project work. | The full 8-step dbt workflow: project scanning, skill loading, validation, macro discovery, research, technical spec, SQL writing, verification. Plus output-shape inference, incremental model handling, and what to trust in YML. |
| `dbt-write` | Step 2 of the workflow (always). | Column naming, type preservation, JOIN defaults, lookup joins, sibling models, materialization, packages, and filtering rules. |
| `dbt-debugging` | When `dbt run` or `dbt parse` fails. | YML duplicate patches, ref errors, passthrough model warnings, `current_date` fixes, DuckDB error messages, and zero-row diagnosis. |
| `dbt-testing` | When the task mentions tests/unit tests, or the scan finds `unit_tests:` in YML. | `unit_tests` YAML format, given/expect blocks, edge-case coverage, and the difference between unit tests and schema tests. |
| `dbt-snapshots` | When the task involves snapshots, SCD Type 2, or change tracking, or a `snapshots/` dir exists. | Strategy selection, column casing, verification, and common pitfalls. |
| `dbt-versioning` | When the task involves versioning / v2 / backward-compatible changes, or YML has `versions:`. | `versions` YAML config, `defined_in`, `latest_version`, and `ref()` with version pins. |
| `dbt-knowledgebase` | When populating the knowledge base from dbt project research. | Proposes entries across all 6 categories at org, project, and connection scopes. |
| `knowledge-base` | Step 6 of the workflow. | Writing the per-task `technical_spec.md`: distills research into structured decisions. Retries read the existing spec instead of re-researching. |
| `duckdb-sql` | When hitting DuckDB syntax errors or writing DuckDB SQL. | DuckDB gotchas that differ from PostgreSQL/MySQL. |
| `snowflake-sql` | When writing Snowflake SQL or hitting Snowflake errors. | `QUALIFY`, `LATERAL FLATTEN`, semi-structured `VARIANT`, `ILIKE`, date functions, and time travel. |
| `bigquery-sql` | When writing BigQuery SQL. | `UNNEST`, `STRUCT`, `ARRAY_AGG`, `DATE_DIFF`/`DATE_ADD`, backtick-quoted refs, `EXCEPT`/`REPLACE` in `SELECT`, approximate aggregation, partitioned/wildcard tables. |
| `sqlite-sql` | When writing SQLite SQL. | `substr`/`instr`, `||` concatenation, `LIKE` (no `ILIKE`), `date()`/`strftime()`, `CAST`, no `FULL OUTER JOIN`, `GROUP_CONCAT`, `typeof()`, `COALESCE`/`IFNULL`, `printf()`. |
| `domain-ecommerce` | Step 2, for orders/products/discounts/returns/charges/spend tasks. | Transaction lifecycle, driving tables, status filtering. |
| `domain-financial` | Step 2, for revenue/invoices/ledgers/fiscal tasks. | Grain consistency, balance sheets, double-entry ledgers, fiscal-year boundaries, period-over-period calculations. |
| `domain-healthcare` | Step 2, for clinical/patients/encounters/diagnoses/costs tasks. | Encounter-based grain, clinical coding hierarchies, cost allocation, NULL semantics in clinical data. |
| `domain-hr` | Step 2, for employees/hiring/issues/SCD/tickets tasks. | SCD current-record filtering, issue-resolution metrics. |
| `domain-marketing` | Step 2, for campaigns/clicks/email/SMS/attribution tasks. | Attribution models, engagement funnel order. |
| `domain-media` | Step 2, for movies/sports/credits/rankings/content tasks. | Content catalogs, participation tables, ranking determinism. |
| `domain-product` | Step 2, for events/sessions/features/guides/analytics tasks. | Calendar spine cross-joins, date boundary caps, event-type pivoting, first-run NULL behavior. |
| `sql-workflow` | Before writing any standalone (non-dbt) SQL query. | Output-shape inference, efficient schema exploration, iterative CTE building, a structured verification loop (row count, NULL audit, fan-out, sample inspection), error recovery, saving to `result.sql`/`result.csv`, turn budget, and common benchmark traps. |
| `write-report` | Only when explicitly requested (model invocation disabled). | Generates an HTML report of dbt project work: decisions, SQL, queries, verifier results, and visual charts. |

## Agents

Both agents are dispatched in parallel in Step 8 of `dbt-workflow`. Both are strictly read-only: they return reports and fix nothing.

| Agent | Role | Checks |
|-------|------|--------|
| `verifier` | Structure verification (read-only). | CHECK 1 table existence; CHECK 2 column completeness via `map-columns` + `check_model_schema`; CHECK 3 row count, fan-out, and cardinality via `audit_model_sources`; CHECK 4 non-deterministic SQL (`ORDER BY NULL`, ROW_NUMBER/RANK without ORDER BY); CHECK 5 source-table preservation for modified models. |
| `value-verifier` | Aggregate value verification (read-only). | CHECK 1 sample value spot-check vs siblings; CHECK 2 aggregate cross-validation via `verify_model_values` (COUNT(*) vs COUNT(DISTINCT) aligned to the column name); CHECK 3 status-column filtering (returns/cancellations/refunds excluded per the domain skill). Prescribes exact `CHANGE:` fixes on FAIL but never edits files. |
