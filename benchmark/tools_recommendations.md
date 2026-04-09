# Tool Recommendations for Spider2-DBT Benchmark

## Current Score: 27/65 = 41.5% (Databao: 30/68 = 44.11%)

## Round 2 Test Results (with consolidated skills + git init for discovery)

| Task | Before | After | Flipped? | Skills Used? | Notes |
|------|--------|-------|----------|-------------|-------|
| airport001 | PASS | PASS | - | Unknown | Baseline still works |
| reddit001 | FAIL (missing cols) | FAIL (same) | No | NO — agent didn't invoke /dbt-verification | Still missing hour_comment_created_at + prod_tables_joined |
| playbook002 | FAIL (5 vs 2 rows) | FAIL (same) | No | NO — agent used INNER JOIN despite skill | cpa_and_roas: INNER JOIN drops 3 sources without spend |
| shopify001 | FAIL (2083→2077) | FAIL (2082→2077) | No | Unknown | Improved by 1 row! Still 5 off — calendar uses Sep 12 not Sep 7 |
| xero001 | FAIL (1194→1170) | FAIL (1194→1170) | No | Unknown | Calendar spine matches gold (69 rows). BSR has 1 extra account per month for 24 months |
| apple_store001 | FAIL (both) | source_type PASS, territory FAIL | Partial | Unknown | source_type_report FLIPPED! territory_short values don't match |

### Key Finding: Agent NOT consistently invoking skills
The agent builds models quickly and finishes without running /dbt-verification. Strengthened prompt language in step 5 ("MANDATORY", "scores ZERO"). Need to confirm if subsequent runs improve.

### Key Finding: xero001 is NOT a date spine issue
Previously classified as Category A (date spine). Actual root cause: the agent includes an extra account in the balance sheet report. The calendar spine (69 rows) matches gold exactly. Reclassify as Category D (value/logic error).

### Key Finding: shopify001 needs table-specific date boundary
Global max date is Sep 12 but shopify__daily_shop should use max(order_date)=Sep 7. The get_date_boundaries tool returns global max which is wrong for this model. Need per-table date boundary guidance.

## Implemented Changes (Round 2)

### Skill Restructure
- Consolidated 8 skills → 4: dbt-workflow, dbt-verification, dbt-debugging, duckdb-sql
- Flattened skill directory structure for Claude Code auto-discovery
- Added git init to prepare_workdir() — CRITICAL for skill discovery
- Skills now appear in agent's system context and can be invoked via /skill-name
- Confirmed via testing: skills ARE discoverable and invokable

### CLAUDE.md Skills Section
Added explicit skill usage guide to CLAUDE.md with when-to-use guidance:
- /dbt-workflow — BEFORE writing SQL
- /duckdb-sql — WHEN writing DuckDB SQL
- /dbt-verification — AFTER dbt build succeeds (MANDATORY)
- /dbt-debugging — WHEN dbt fails

### Agent Output Capture
Added --output-format json and agent_output.json transcript saving for tool usage analysis.

## Implemented Tools (Round 1)

### 1. check_model_schema — Schema Diff Tool
**Status**: IMPLEMENTED
**Impact**: Targets ~8 tasks with schema/column mismatches
**Measured impact**: Agent doesn't consistently call it. When called, correctly identifies missing columns.

### 2. dbt_error_parser — Error Parser Tool  
**Status**: IMPLEMENTED
**Impact**: Saves 2-3 turns per dbt error across all tasks
**Measured impact**: Not called by agent in observed runs.

### 3. generate_sql_skeleton — SQL Template Generator
**Status**: IMPLEMENTED  
**Impact**: Targets ~5 tasks where agent exhausts turns
**Measured impact**: Not called by agent in observed runs.

### 4. analyze_grain — Cardinality Oracle
**Status**: IMPLEMENTED
**Impact**: Targets ~6 tasks with row count mismatches  
**Measured impact**: Not called by agent in observed runs.

### 5. validate_model_output — Post-Build Validator
**Status**: IMPLEMENTED
**Impact**: Targets ~4 tasks with fan-out/filter issues
**Measured impact**: Not called by agent in observed runs.

## Root Cause Analysis Updates

| Task | Category | Updated Root Cause | Fix Strategy |
|------|----------|-------------------|-------------|
| xero001 | D (was A) | Extra account included in BSR. Calendar spine is correct. | Filter accounts properly in balance_sheet_report model |
| shopify001 | A | Calendar uses global max date (Sep 12) not order-specific (Sep 7) | Need per-table date boundary, not global |
| playbook002 | B | INNER JOIN in cpa_and_roas drops 3 sources without spend | LEFT JOIN or FULL OUTER JOIN needed |
| reddit001 | F+C | Missing hour_comment_created_at column, missing prod_tables_joined model | Agent must read YML more carefully |
| apple_store001 | D (was B) | source_type_report now PASSES. territory_short values wrong | Value mapping issue in territory data |

## Next Priority Tool Ideas

### 6. Per-Table Date Boundary Tool
**Effort**: Low | **Impact**: Fixes shopify001 + similar
Instead of just global max date, return max date per table:
```
mcp__signalpilot__get_table_date_range(connection_name, table_name)
→ "Table: stg_shopify__order | date columns: created_at (min: 2019-01-01, max: 2024-09-07)"
```
This lets the agent pick the correct table-specific date for spine capping.

### 7. Force Verification via Pipeline (not agent discretion)
**Effort**: Medium | **Impact**: All tasks
Instead of hoping the agent invokes /dbt-verification, run check_model_schema and validate_model_output programmatically in the post-build pipeline (value-verify agent already exists). The value-verify agent receives pre-computed failures and fixes them.

### 8. Deterministic Surrogate Key Macro
**Effort**: Low | **Impact**: Fixes superstore001 + similar
Replace ROW_NUMBER() non-determinism with content-hash-based keys.

## Competitor Analysis (Databao - #1 at 44.11%)

From their blog post:
1. **Restricted tools** — narrow set: dbt run, dbt build, file writes locked to .sql only
2. **Upfront context injection** — full project files + DB overview before starting
3. **Enforced inspect-build-verify loop** — never submit unless final dbt run succeeds
4. Key quote: "stability beats cleverness"

## Priority Ranking (Updated)

| # | Action | Tasks it could flip | Effort |
|---|--------|-------------------|--------|
| 1 | Force verification in pipeline (not agent) | All failing (catch missing cols, wrong counts) | Medium |
| 2 | Per-table date boundary tool | shopify001, pendo001, quickbooks003, xero_new001 | Low |
| 3 | Deterministic surrogate keys | superstore001 | Low |
| 4 | Better JOIN guidance in skill | playbook002, flicks001 | Low (skill update) |
| 5 | Increase max_turns for complex tasks | f1001, tpch002 | Config change |
