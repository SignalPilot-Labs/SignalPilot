---
sidebar_position: 3
---

# Skills Reference

Per-skill detail for all 9 SignalPilot plugin skills. Each skill is a markdown knowledge file that auto-loads into Claude Code's context.

---

## dbt-workflow

**When it loads:** Step 1 — before exploring any dbt project.

**What it covers:** Output shape inference from YML descriptions (cardinality clues: entity, qualifier, rank constraint, temporal scope), incremental model handling, and what to trust in YML vs. the database. Teaches Claude to read the `description:` field before writing any SQL to understand the expected output shape.

**Example prompt that activates it:**

> "Build the `shopify__daily_shop` dbt model — orders, abandoned checkouts, fulfillment counts by day."

---

## dbt-write

**When it loads:** Step 4 — when writing SQL model files.

**What it covers:** Column naming rules (aliases must match YML exactly, case-sensitive), type preservation from reference tables, JOIN defaults (use LEFT JOIN unless the YML description implies INNER), lookup join patterns, sibling model handling, and filtering rules. Prevents the most common dbt evaluation failures.

**Example prompt that activates it:**

> "Write the SQL for the `orders` model based on the YML spec."

---

## dbt-debugging

**When it loads:** When `dbt run` or `dbt parse` fails.

**What it covers:** Duplicate YML patch resolution (the most common failure), ref-not-found errors, passthrough model warnings, `current_date` hazards, DuckDB-specific error messages, and zero-row diagnosis. Provides a structured fix protocol for each error type.

**Example prompt that activates it:**

> "dbt run failed with 'Duplicate patch for model orders'. How do I fix it?"

---

## dbt-date-spines

**When it loads:** When `dbt_project_map` reports date hazards or a date-spine model produces unexpected row counts.

**What it covers:** Fixing `current_date`, `current_timestamp`, and `now()` in model SQL files by replacing them with data-driven endpoints (a subquery from the primary fact table). Covers both DuckDB and other dialects.

**Example prompt that activates it:**

> "The date spine model is generating too many rows. Fix the current_date hazard."

---

## sql-workflow

**When it loads:** Before writing any SQL query (benchmark or ad-hoc).

**What it covers:** Schema exploration order (read local schema files first, then MCP tools), CTE-based iterative query building, a structured verification loop (row count, NULL audit, fan-out check, sample inspection), error recovery protocol, turn budget management, and common benchmark traps.

**Example prompt that activates it:**

> "Write a SQL query to find the top 10 customers by revenue in the last 30 days."

---

## duckdb-sql

**When it loads:** When hitting DuckDB-specific syntax errors or writing DuckDB SQL.

**What it covers:** Integer division truncation (`5/2 = 2` — use `CAST`), `DATE_TRUNC` returning TIMESTAMP, `INTERVAL` syntax (must be quoted: `INTERVAL '1' DAY`), no `DATEADD`/`DATEDIFF`, `SUM(NULL) = NULL` behavior, and avoiding `CURRENT_DATE` in historical models.

**Example prompt that activates it:**

> "I'm getting a type error on the date truncation in my DuckDB model."

---

## snowflake-sql

**When it loads:** When writing Snowflake SQL or hitting Snowflake-specific errors.

**What it covers:** `QUALIFY` for window function filtering (avoids subquery wrapping), `LATERAL FLATTEN` for array/VARIANT expansion, semi-structured `VARIANT` data access, `ILIKE` for case-insensitive matching, Snowflake date functions, and time travel queries.

**Example prompt that activates it:**

> "Write a Snowflake query to get the latest record per customer using window functions."

---

## bigquery-sql

**When it loads:** When writing BigQuery SQL.

**What it covers:** `UNNEST` for array expansion, `STRUCT` and `ARRAY_AGG`, `DATE_DIFF`/`DATE_ADD`, backtick-quoted table references (`` `project.dataset.table` ``), `EXCEPT`/`REPLACE` in `SELECT *`, approximate aggregation functions, and partitioned/wildcard table patterns.

**Example prompt that activates it:**

> "Write a BigQuery query to unnest the order items array and aggregate by product."

---

## sqlite-sql

**When it loads:** When writing SQLite SQL.

**What it covers:** `substr()` and `instr()` for string operations (no `POSITION()` or `SPLIT_PART()`), `||` for string concatenation, `LIKE` only (no `ILIKE`), `date()`/`strftime()` for date functions, `CAST` for type coercion, no `FULL OUTER JOIN`, `GROUP_CONCAT`, `typeof()`, `COALESCE`/`IFNULL`, and `printf()` formatting.

**Example prompt that activates it:**

> "Write a SQLite query to extract the domain from an email column."
