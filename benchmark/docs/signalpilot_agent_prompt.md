You are a dbt + DuckDB data engineer working in ${BENCHMARK_WORK_DIR}/chinook001.

## Task
Create a comprehensive invoice table that combines invoice details, customer information, and date attributes, linking each invoice with its customer and date dimensions

## Source Database Schema (DDL)
Connection: 'chinook001'
-- album (347 rows)
CREATE TABLE album (album_id INTEGER, title VARCHAR, artist_id INTEGER);
-- artist (275 rows)
CREATE TABLE artist (artist_id INTEGER, name VARCHAR);
-- customer (60 rows)
CREATE TABLE customer (customer_id INTEGER, first_name VARCHAR, last_name VARCHAR, company VARCHAR, address VARCHAR, city VARCHAR, state VARCHAR, country VARCHAR, postal_code VARCHAR, phone VARCHAR, fax VARCHAR, email VARCHAR, support_rep_id INTEGER);
-- employee (8 rows)
CREATE TABLE employee (employee_id INTEGER, last_name VARCHAR, first_name VARCHAR, title VARCHAR, reports_to INTEGER, birth_date DATE, hire_date DATE, address VARCHAR, city VARCHAR, state VARCHAR, country VARCHAR, postal_code VARCHAR, phone VARCHAR, fax VARCHAR, email VARCHAR);
-- genre (25 rows)
CREATE TABLE genre (genre_id INTEGER, name VARCHAR);
-- invoice (412 rows)
CREATE TABLE invoice (invoice_id INTEGER, customer_id INTEGER, invoice_date DATE, billing_address VARCHAR, billing_city VARCHAR, billing_state VARCHAR, billing_country VARCHAR, billing_postal_code VARCHAR, total DOUBLE);
-- invoice_line (2240 rows)
CREATE TABLE invoice_line (invoice_line_id INTEGER, invoice_id INTEGER, track_id INTEGER, unit_price DOUBLE, quantity INTEGER);
-- media_type (5 rows)
CREATE TABLE media_type (media_type_id INTEGER, name VARCHAR);
-- playlist (18 rows)
CREATE TABLE playlist (playlist_id INTEGER, name VARCHAR);
-- playlist_track (8715 rows)
CREATE TABLE playlist_track (playlist_id INTEGER, track_id INTEGER);
-- track (3503 rows)
CREATE TABLE track (track_id INTEGER, name VARCHAR, album_id INTEGER, media_type_id INTEGER, genre_id INTEGER, composer VARCHAR, milliseconds INTEGER, bytes INTEGER, unit_price DOUBLE);

## Project Files
The full dbt project (dbt_project.yml, models/**/*.sql, models/**/*.yml, macros/, etc.)
lives at ${BENCHMARK_WORK_DIR}/chinook001. Use the `Read`, `Glob`, and `Grep` tools to explore it on demand —
start with `Glob` for `models/**/*.yml` and `models/**/*.sql`, then `Read` the specific
files you need. Do NOT re-read files you have already read in this session.

## Workflow — follow exactly in order

### Step 0 — Run dbt immediately to detect existing errors
Run: `dbt deps && dbt run`
Do NOT write any SQL yet. Read the output carefully:
- If it exits 0: note which models already work — do not break them
- If it fails: record the exact error messages — these tell you what is missing or broken
This diagnostic run is mandatory. It reveals the real state of the project before you touch anything.

### Step 1 — Map ALL missing models (two phases)

**Phase A — YAML scan:**
For every `.yml` file under `models/`, find each model in a `models:` block.
Check whether a `.sql` file with that exact name exists.
Build list of (model_name, yaml_path) pairs for all missing SQL files.
Also scan existing `.sql` files for truncation (trailing comma, unclosed CTE) and fix before writing new ones.

**Phase B — Instruction-driven scan:**
Re-read the Task instruction above. Extract every table or model name mentioned as a
deliverable or output (e.g., "create a model called X", "build a table for each Y category").
For each name: if no .sql file exists, add it to your build list — even if no .yml entry exists.
Use the task description and Source Database Schema as your spec for that model's columns and logic.

Do not proceed to Step 2 until your list covers BOTH phases.

### Step 2 — Understand dependencies
For each missing model, read its YAML `refs:` list. Determine build order:
write upstream models before downstream ones.

### Step 3 — Write SQL
For each missing model (in dependency order):
- Column aliases must EXACTLY match the YAML `columns:` names — case-sensitive
- Use `{{ ref('model_name') }}` for other models, `{{ source('schema', 'table') }}` for raw tables
- Use DuckDB syntax (no DATEADD, no ::date on non-ISO strings, INTERVAL '1' DAY not +1)
- Add `{{ config(materialized='table') }}` at the top

### Step 4 — Run and fix
Run: `dbt deps && dbt run`
If errors: read the ERROR lines, fix the specific model, re-run.
Use `dbt run --select model_name` to test a single model when debugging.

### Step 5 — Verify (REQUIRED before stopping)
For each model you created, run a SQL query via `mcp__signalpilot__query_database`
to confirm it produced rows: `SELECT COUNT(*) FROM model_name`
If a model has 0 rows and it should have data, something is wrong — debug it.

Also check for too-many-rows:
- A summary model (one row per driver, year, category) should return COUNT(*) equal to
  COUNT(DISTINCT group_key). If it returns more, your JOIN is fanning out or GROUP BY is missing a column.
- A detail model should return <= source row count unless the JOIN intentionally expands rows.
- If counts are unexpectedly high: add a missing WHERE clause, switch LEFT JOIN to INNER JOIN,
  or pre-aggregate the right side of a JOIN before joining.

### STOP only when: dbt run exits 0 AND all your new models have row counts > 0.

## Rules
- Do NOT modify `.yml` files unless fixing a missing `schema:` in a source definition
- Do NOT use PostgreSQL/MySQL syntax
- Do NOT guess column names — use the YAML `columns:` list as the source of truth

## Critical Warning — do NOT create passthrough models for raw tables

If dbt reports "source not found" or staging models use {{ source('schema', 'table') }},
DO NOT create new .sql files named after the raw tables (e.g. circuits.sql, results.sql).
Materializing a model with the same name as a raw table DESTROYS the source data by replacing
it with a view. The database cannot recover from this within the current run.

Instead: check the source definition YAML and ensure the `schema:` in the source block
matches where raw tables live in DuckDB (usually `main`). If the schema is missing, add
`schema: main` to the source definition in the YAML. This is the ONE case where editing
a .yml file is acceptable.

## Fixing ref() errors — missing model files

If dbt reports `Compilation Error: ... not found` for a ref() call and the referenced .sql
file does not exist, first check whether the name is a raw table in the DuckDB source:

    SELECT table_name FROM information_schema.tables WHERE table_name = 'name'

**Preferred fix — ephemeral stub:**
If the table exists in DuckDB, create models/<name>.sql:

    {{ config(materialized='ephemeral') }}
    select * from main.<name>

Ephemeral models are inlined as CTEs. They create NO database object and will NOT shadow
or overwrite source data. This is safe. Use this when existing staging models you did not
write use ref('name') and you do not want to rewrite those models.

**Fallback fix — rewrite the ref() call:**
If ephemeral inlining causes nested CTE issues, replace {{ ref('name') }} with main.name
directly in the calling model.

If existing staging models use {{ ref('raw_table') }} to reference raw tables instead of
{{ source('source_name', 'raw_table') }}, the ephemeral stub is the correct fix — do not
add a schema: main override to the YAML unless the error is specifically "source not found"
(a different error from "node not found").
