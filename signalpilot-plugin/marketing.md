# SignalPilot Plugin — What's New

The SignalPilot plugin transforms Claude into a governed, expert-level dbt developer. The original plugin shipped with a single workflow skill and a basic verification subagent. The new plugin is a complete platform: 21 skills, 2 specialized verification agents, 3 CLI diagnostic tools, 7 MCP gateway tools, and 8 domain expertise modules — all orchestrated by an 8-step workflow that consistently scores 59/61 on the ADE-bench dbt benchmark.

---

## The 8-Step Governed Workflow

Every dbt task follows a structured, auditable workflow — no shortcuts, no ad-hoc guessing.

**Step 1 — Scan.** `scan_project.py` analyzes the entire project in one call: which models need building, which are already complete, parent-child relationships, var() conventions, sibling patterns, and system column detection. The agent sees the full landscape before writing a single line.

**Step 2 — Load Skills.** The workflow loads domain expertise (e-commerce, financial, HR, healthcare, marketing, media, product) and feature skills (snapshots, testing, versioning) based on the task. Each skill injects focused context at the right moment.

**Step 3 — Validate.** Run `dbt parse`, rebuild stale upstream models with `current_date` hazards, ensure the project compiles before any changes.

**Step 4 — Discover.** Scan project macros for column-producing patterns (e.g., `generate_surrogate_key`, `normalize_timestamp`). These produce columns that don't appear in source tables.

**Step 5 — Research.** `generate_model_blueprint` returns upstream cardinalities, sibling SQL patterns, status/flag column values, key overlap detection, and a recommended driving table — all from one MCP call.

**Step 6 — Spec.** Write `technical_spec.md` — a structured plan with build order, data sources, join logic, and expected row counts. On retries, the agent reads the existing spec instead of re-researching.

**Step 7 — Build.** Write SQL following the spec. The `dbt-write` skill provides 14 sections of production rules: column naming, sibling patterns, lookup JOINs, filter scope, CTE extraction, Jinja removal, and more.

**Step 8 — Verify.** Dispatch two independent verification agents in parallel. Both are read-only — they query, report, and never touch files. The main agent only acts on verified FAILs.

---

## Dual Verification System

The original plugin had a single verification subagent. The new system splits verification into two specialized agents that run in parallel, cutting verification time in half while increasing coverage.

### Structure Verifier
Five checks, zero guesswork:
- **CHECK 1 — Table Existence.** Every YML model must be materialized.
- **CHECK 2 — Column Completeness.** `map-columns` compares upstream columns against the SQL. For new models: flag every missing column. For modified models: only verify existing columns are intact — don't prescribe additions to pre-existing code.
- **CHECK 3 — Row Count, Fan-Out & Cardinality.** `audit_model_sources` returns model rows vs source rows, fan-out ratios, NULL fractions, and distinct counts in one call. Fan-out is only flagged when duplicate lookup rows are byte-identical.
- **CHECK 4 — Non-Deterministic SQL.** Detects `ROW_NUMBER()` without `ORDER BY` or `ORDER BY NULL` — silent correctness killers.
- **CHECK 5 — Source Table Preservation.** For modified models, compares the original FROM/ref() against the agent's version. Changing a model's source table changes its meaning.

### Value Verifier
Three checks focused on data correctness:
- **CHECK 1 — Sample Spot-Check.** `SELECT * LIMIT 5` with sibling comparison and suspicious value detection. Knows that negative balances are valid in e-commerce and that NULL gap-fill values are expected in date-spine models.
- **CHECK 2 — Aggregate Cross-Validation.** Calls `verify_model_values` (MCP tool) for COUNT(*) and COUNT(DISTINCT) baselines. Compares against the model's column names — "total_X" must match COUNT(*), "unique_X" must match COUNT(DISTINCT).
- **CHECK 3 — Status Column Filtering.** Detects unfiltered status columns that inflate row counts with returns, cancellations, and refunds.

---

## Intelligent Column Mapping

`map-columns` is a 1,135-line CLI tool that makes column decisions data-driven, not heuristic.

For every upstream column, it outputs one of three statuses:
- **MAPPED** — column matches the YML contract
- **UNMAPPED-INCLUDE** — column not in YML but has data; include it
- **UNMAPPED-EXCLUDE** — column flagged for exclusion with a specific reason

Exclusion reasons are data-driven:
- `[unused_system_column]` — 100% NULL across ALL raw tables in the project (not just the current model). These are framework columns that carry no business data.
- `[sibling_skip]` — present in this table but excluded by all sibling models
- `[all_null_binary]` — BLOB/BYTEA column with no data

Additional signals surfaced as warnings:
- `[all_null]` — NULL in this table but has data elsewhere
- `[constant_value]` — single value across all rows
- `[varchar_event_date]` — date stored as VARCHAR; suggests CAST to DATE
- Collision detection when the same column name appears in multiple upstream tables

---

## Model Blueprint

`generate_model_blueprint` is a 1,304-line MCP tool that provides everything the agent needs to write a model in one call:

- **YML Contract** — column names, types, tests, descriptions
- **Upstream Cardinalities** — row counts and distinct key counts per source table
- **Sibling SQL Patterns** — existing models in the same directory for convention matching
- **Status/Flag Values** — `SELECT DISTINCT` on categorical columns with per-value entity counts
- **Driving Table Recommendation** — data-driven: entity table (unique primary key) wins over largest table
- **Key Overlap Detection** — when two upstream tables share a key but zero values overlap, the blueprint flags it as a disjoint-key warning and recommends the entity table as the FROM clause
- **Fivetran SCD-2 Detection** — identifies `_fivetran_active` tables and determines the true entity grain after active-record filtering
- **Reference Table Separation** — `_types`, `_statuses`, `_categories` tables are flagged as lookups, not driving tables
- **Lookup JOIN Suggestions** — FK columns with matching dimension tables get JOIN hints with display column recommendations

---

## Project Scanner

`scan_project.py` (836 lines) gives the agent a complete project overview at Step 1:

- **Models to Build** — YML-defined models without SQL files
- **Aggregation Driving Table** — parent-child gap detection. When parent rows have no matching children, the scanner emits a MANDATORY flag: "drive FROM parent LEFT JOIN child to preserve rows with count=0"
- **Var Aliases** — detects `dbt_project.yml` vars that resolve to refs, so the agent uses `var('X')` instead of `ref('stg_Y')` in package-convention projects
- **Stubs to Rewrite** — incomplete SQL files (empty, `SELECT *`, TODO markers)
- **Existing Complete Models** — already-built models the agent must NOT rewrite
- **SQL Files Without YML** — usable as ref() targets; the agent prefers ref() over source() when staging models exist
- **Sibling Patterns** — complete models in the same directory with column counts for convention matching
- **System Column Detection** — columns that are 100% NULL across every raw table in the project

---

## 8 Domain Expertise Modules

Each domain skill provides specialized rules that the general workflow can't cover. The agent loads the appropriate domain skill at Step 2 based on the project's data.

| Domain | Key Rules |
|--------|-----------|
| **E-commerce** | Transaction lifecycle filtering (exclude returns/cancellations), calendar spine exceptions, fact-drives-FROM rule |
| **Financial** | Grain consistency for balance sheets, double-entry ledger handling, fiscal year boundaries, running balance windows |
| **Healthcare** | Encounter-based grain, clinical coding hierarchies (ICD/CPT), cost allocation, NULL = "not assessed" semantics |
| **HR & Operations** | SCD current-record filtering with COALESCE(_fivetran_active), issue resolution metrics, parent-child spine exception |
| **Marketing** | Attribution model grain, engagement funnel ordering, campaign-to-conversion linking |
| **Media** | Content catalog vs participation tables, ranking determinism for leaderboards |
| **Product** | Calendar spine cross-joins with date caps, event type pivoting, first-run NULL behavior for rolling windows |

---

## Driving Table Check

`check-driving-table` (147 lines) is a post-build diagnostic that catches wrong FROM clause selection:

- **Auto-detect mode**: checks if ALL timestamp columns in a model are NULL. If every timestamp is NULL across all rows, the data isn't sourced from the current driving table.
- **Targeted mode**: checks a specific column (e.g., `conversation_created_at`) for ALL-NULL.
- Output: `PASS` (data present), `FAIL` (ALL NULL — wrong driving table), or `SKIP` (not materialized).

---

## Post-Grade Review

When a task fails evaluation, the agent automatically generates a `failure_report.html` — a self-contained HTML report with:

- **Executive Summary** — task, result, root cause in one sentence
- **Decision Trace** — every major decision with "What I Did" vs "What Gold Does"
- **Tool Output Analysis** — what each tool told the agent and whether the interpretation was correct
- **Prompting Report** — traces every wrong decision to the EXACT prompt rule that caused it. Flags "PROMPT CONTRADICTS GOLD" when a skill rule led to the wrong answer, "NO RULE COVERED THIS" for gaps, and "TOOL GAVE WRONG SIGNAL" for tool issues
- **Prompt Suggestions** — exact rule text changes that would fix each issue
- **Wishes** — actionable tool improvements from the agent itself ("I wish map-columns had told me X")
- **Diff Summary** — line-by-line comparison between agent output and gold

These reports create a feedback loop: every failure produces specific, implementable improvements to tools and skills.

---

## SQL Dialect Support

Four dialect skills ensure correct SQL generation across databases:

| Dialect | Key Patterns |
|---------|-------------|
| **DuckDB** | LIST/STRUCT types, `EPOCH()` for timestamps, `||` for concat, case-sensitive identifiers |
| **BigQuery** | `UNNEST` for arrays, `STRUCT`, backtick-quoted tables, `EXCEPT/REPLACE` in SELECT, partitioned tables |
| **Snowflake** | `QUALIFY` for window filtering, `LATERAL FLATTEN`, `VARIANT` semi-structured data, time travel |
| **SQLite** | `substr/instr`, `strftime`, no FULL OUTER JOIN, `GROUP_CONCAT`, `typeof()` |

---

## Feature Skills

### dbt Snapshots
Strategy selection is data-driven: the agent queries `COUNT(DISTINCT updated_at)` before choosing. A frozen timestamp (single constant value) always gets `strategy='check'`. No more "rationalize a broken timestamp as valid data."

### dbt Unit Tests
Full YAML `given/expect` format support. Edge case patterns for rolling windows (boundary dates), ratios (zero denominator), and categorical data (sparse test seeds).

### dbt Model Versioning
v2 creation, `defined_in` for co-locating versions, `latest_version` management, and ref() with version pins for backward compatibility.

---

## Numbers

| Metric | Original Plugin | New Plugin |
|--------|----------------|------------|
| Skills | 2 | 21 |
| Verification agents | 1 | 2 (parallel) |
| CLI tools | 0 | 3 |
| MCP gateway tools | 7 | 7 (all enhanced) |
| Domain skills | 0 | 8 |
| SQL dialect skills | 0 | 4 |
| Total prompt lines | ~200 | ~690 (core) + ~1,500 (domain/feature) |
| ADE-bench score | N/A | 59/61 |
| Post-grade feedback | No | Automatic HTML reports with prompting analysis |
