---
sidebar_position: 1
---

# dbt Model Build Walk-through

An end-to-end example of building a dbt model with SignalPilot.

## The scenario

You want to build `shopify__daily_shop` — a mart model that aggregates orders, abandoned checkouts, and fulfillment counts by day.

## Step 1 — Describe the task

In Claude Code:

> "Build `shopify__daily_shop` — orders, abandoned checkouts, fulfillment counts by day."

The `dbt-workflow` skill auto-loads. Claude reads the YML description to infer output shape before touching the database:

- **ENTITY**: one row per day
- **TEMPORAL SCOPE**: daily grain
- No rank constraint, no period-over-period

## Step 2 — Scan the project

Claude calls `get_project` to find the dbt project, then `list_tables` to enumerate the available sources:

```
Tool: list_tables
→ shopify.orders (48,291 rows)
→ shopify.order_items (182,044 rows)
→ shopify.checkouts (61,203 rows)
→ shopify.fulfillments (45,882 rows)
```

Then `describe_table` on each relevant source to understand column types and nullability. Claude checks for date hazards — any model using `current_date` or `now()` will be flagged by the `dbt-date-spines` skill.

## Step 3 — Validate before executing

Before running any query against the warehouse, Claude calls `validate_sql`:

```
Tool: validate_sql
SQL: SELECT order_date, COUNT(*) as order_count FROM shopify.orders GROUP BY 1
→ valid: true
→ estimated rows: 365
```

For expensive Snowflake or BigQuery queries, `estimate_query_cost` runs first:

```
Tool: estimate_query_cost
→ estimated_cost: $0.003
→ bytes_processed: 12.4 MB
```

## Step 4 — Generate the SQL skeleton

```
Tool: generate_sql_skeleton
project: shopify
model: shopify__daily_shop
→ Returns a SQL template with CTEs for each declared column in the YML
```

Claude fills in the CTE logic using the schema information from Step 2. The `dbt-write` skill enforces:

- Column aliases match YML exactly (case-sensitive)
- Types preserved from source tables
- LEFT JOINs by default (unless YML description implies INNER)

## Step 5 — Build and verify

Claude runs `dbt run` (via the terminal, not MCP — dbt CLI runs locally). Then the verifier agent kicks in:

```
Tool: check_model_schema    → 12/12 columns match YML
Tool: validate_model_output → 365 rows, no fan-out
Tool: audit_model_sources   → sources stable
Tool: analyze_grain         → 1.00 rows per order_date
```

**Verifier receipt:**

```
duration:          18.2s
agent turns:       6
governed queries:  12
queries blocked:   0
models built:      1
columns validated: 12
```

## Cross-links

- [How It Works](/docs/how-it-works) — the full 5-stage lifecycle
- [`generate_sql_skeleton`](/docs/reference/tools-dbt#generate_sql_skeleton) — SQL template generation
- [`validate_model_output`](/docs/reference/tools-dbt#validate_model_output) — row count + fan-out check
- [Verifier agent](/docs/plugin/verifier-agent) — full 7-check receipt
