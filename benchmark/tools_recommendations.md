# Tool Recommendations for Spider2-DBT Benchmark

## Current Score: 27/65 = 41.5% (Databao: 30/68 = 44.11%)

## Implemented Tools (Round 1)

### 1. check_model_schema — Schema Diff Tool
**Status**: IMPLEMENTED
**Impact**: Targets ~8 tasks with schema/column mismatches
**How it works**: Compares materialized DuckDB table columns against expected YML column list. Returns missing, extra, and case-mismatched columns.
**Tasks it should help**: reddit001 (missing hour_comment_created_at), social_media001 (column names), playbook002, jira001, danish_democracy_data001, xero_new001
**Measured impact**: TBD (running tests)

### 2. dbt_error_parser — Error Parser Tool  
**Status**: IMPLEMENTED
**Impact**: Saves 2-3 turns per dbt error across all tasks
**How it works**: Parses raw dbt stderr/stdout, extracts model name, error type, line number, and suggests a fix from a lookup table.
**Tasks it should help**: All tasks — reduces turn waste on error parsing

### 3. generate_sql_skeleton — SQL Template Generator
**Status**: IMPLEMENTED  
**Impact**: Targets ~5 tasks where agent exhausts turns
**How it works**: Generates a SQL template from model name + column list + ref tables. Agent fills in transformation logic instead of boilerplate.
**Tasks it should help**: f1001, tpch002, analytics_engineering001

### 4. analyze_grain — Cardinality Oracle
**Status**: IMPLEMENTED
**Impact**: Targets ~6 tasks with row count mismatches  
**How it works**: Analyzes table cardinality — total rows, unique columns, fan-out factors.
**Tasks it should help**: tpch001 (fan-out), recharge002 (extra rows), airbnb001, netflix001

### 5. validate_model_output — Post-Build Validator
**Status**: IMPLEMENTED
**Impact**: Targets ~4 tasks with fan-out/filter issues
**How it works**: Checks model row count, compares to source table, detects fan-out warnings.
**Tasks it should help**: tpch001, apple_store001, flicks001

## Failure Category Analysis

| Category | Count | Tool That Helps | Expected Flip Rate |
|----------|-------|----------------|-------------------|
| A - Date spine/CURRENT_DATE | 7 | get_date_boundaries (existing) | 50-70% with better prompting |
| B - Wrong JOIN type | 4 | analyze_grain, validate_model_output | 25-50% |
| C - Row count/aggregation | 7 | analyze_grain, validate_model_output | 30-50% |
| D - Value/computation error | 9 | check_model_schema (for schema), limited for logic | 10-20% |
| E - Missing/broken build | 3 | dbt_error_parser, generate_sql_skeleton | 50% |
| F - Schema/column mismatch | 3 | check_model_schema | 70-90% |
| G - Non-deterministic | 2 | None (fundamental issue) | 0% |

## Competitor Analysis (Databao - #1 at 44.11%)

From their blog post:
1. **Restricted tools** — narrow set: dbt run, dbt build, file writes locked to .sql only
2. **Upfront context injection** — full project files + DB overview before starting
3. **Enforced inspect-build-verify loop** — never submit unless final dbt run succeeds
4. Key quote: "stability beats cleverness"

We already implement most of their patterns. Our gap is likely in:
- Consistency of tool usage (agent doesn't always use the tools we give it)
- Date spine override (the #1 failure category)
- Agent turn efficiency

## Next Tool Ideas (Not Yet Implemented)

### 6. Deterministic Surrogate Key Macro
**Effort**: Low | **Impact**: Fixes superstore001 + similar
Would replace ROW_NUMBER() non-determinism with content-hash-based keys.

### 7. Pre-flight Model Validator (before eval)
**Effort**: Medium | **Impact**: Catches 3-5 more tasks  
Run the full eval comparison logic (minus gold data) as a self-check.

### 8. Source-to-Target Column Mapper
**Effort**: Medium | **Impact**: Helps with value/computation errors
Traces which source columns should feed into each target column based on naming patterns.

## Test Results Log

| Task | Before Tools | After Tools | Flipped? | Notes |
|------|-------------|-------------|----------|-------|
| airport001 | PASS | PASS | - | Baseline verification |
| shopify001 | FAIL (2083 vs 2077) | TBD | TBD | Date spine issue |
| reddit001 | FAIL (missing cols) | TBD | TBD | Schema mismatch |
| xero001 | FAIL (1194 vs 1170) | TBD | TBD | Date spine |
| playbook002 | FAIL (5 vs 2) | TBD | TBD | JOIN type |
