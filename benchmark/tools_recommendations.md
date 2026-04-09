# Tool Recommendations for Spider2-DBT Benchmark

## Current Score: 27/65 = 41.5% (Databao: 30/68 = 44.11%)

## Round 2 Test Results (with consolidated skills + auto-discovery)

| Task | Before | After | Flipped? | Notes |
|------|--------|-------|----------|-------|
| airport001 | PASS | PASS | - | Baseline still works |
| reddit001 | FAIL (missing cols) | FAIL (same) | No | Agent didn't invoke /dbt-verification |
| playbook002 | FAIL (5 vs 2) | FAIL (same) | No | INNER JOIN in cpa_and_roas drops 3 sources |
| shopify001 | FAIL (2083 vs 2077) | FAIL (2082 vs 2077) | No | Improved by 1 row. Calendar uses Sep 12 not Sep 7 |
| xero001 | FAIL (1194 vs 1170) | FAIL (same) | No | Calendar spine correct! Extra account in BSR |
| apple_store001 | FAIL (both) | source_type PASS | Partial | source_type_report FLIPPED! territory values wrong |

### Key Finding: Agent NOT consistently invoking /dbt-verification
Skills are discoverable (confirmed via testing) but agent skips step 5. Strengthened prompt language.

### Key Finding: xero001 reclassified
Previously Category A (date spine). Actual: Category D (logic error). Calendar spine matches gold (69 rows). Extra account included for 24 months.

### Key Finding: shopify001 needs table-specific dates
Global max date (Sep 12) != order max date (Sep 7). Agent uses global, should use table-specific.

## Implemented Tools (Round 1)

### 1. check_model_schema — Schema Diff Tool
**Status**: IMPLEMENTED via MCP
**Impact**: Agent doesn't consistently call it yet. When called, correctly identifies missing columns.

### 2. dbt_error_parser — Error Parser Tool  
**Status**: IMPLEMENTED via MCP
**Impact**: Saves 2-3 turns per dbt error. Not called in observed runs.

### 3. generate_sql_skeleton — SQL Template Generator
**Status**: IMPLEMENTED via MCP
**Impact**: Not called in observed runs.

### 4. analyze_grain — Cardinality Oracle
**Status**: IMPLEMENTED via MCP
**Impact**: Not called in observed runs.

### 5. validate_model_output — Post-Build Validator
**Status**: IMPLEMENTED via MCP
**Impact**: Not called in observed runs.

## Architecture Decision: All DB Access Through SignalPilot MCP

All database queries MUST go through SignalPilot MCP tools. This is a product constraint:
- Enterprise customers connect DBs through SignalPilot gateway
- Cost control requires queries to be agent-managed, not automated
- No direct DuckDB access from the benchmark runner (except for evaluation)

The agent must learn to use the MCP verification tools on its own. We enforce this through:
1. Strong skill descriptions that auto-surface at the right time
2. Mandatory step 5 in the prompt with /dbt-verification
3. CLAUDE.md skill usage guide listing when to invoke each skill

## Skill System (Round 2)

### Structure
4 skills in flat directories for Claude Code auto-discovery:
- `dbt-workflow/SKILL.md` — Before writing SQL: JOIN selection, output shape, column contracts
- `dbt-verification/SKILL.md` — After dbt build: MCP tool checklist (check_model_schema, validate_model_output, analyze_grain)
- `dbt-debugging/SKILL.md` — When dbt fails: error parsing, fan-out/over-filter diagnosis
- `duckdb-sql/SKILL.md` — DuckDB syntax: date functions, type casting, gotchas

### Key Technical Discovery
- Claude Code only discovers skills 1 level deep in `.claude/skills/<name>/SKILL.md`
- Nested paths like `.claude/skills/dbt/expert/SKILL.md` are INVISIBLE to discovery
- Each workdir needs `git init` to be recognized as a project root
- Skill descriptions are the discovery trigger — must be specific about WHEN to use

## Next Priority Actions

| # | Action | Tasks it could flip | Effort |
|---|--------|-------------------|--------|
| 1 | Get agent to reliably invoke /dbt-verification | All failing with schema/count issues | Prompt tuning |
| 2 | Per-table date boundary MCP tool | shopify001, pendo001, quickbooks003 | Low |
| 3 | Deterministic surrogate key macro | superstore001 | Low |
| 4 | Better JOIN guidance in workflow skill | playbook002, flicks001 | Skill update |
| 5 | Increase max_turns for complex tasks | f1001, tpch002 | Config change |

## Competitor Analysis (Databao - #1 at 44.11%)

From their approach:
1. Restricted tools — narrow set: dbt run, dbt build, file writes locked to .sql only
2. Upfront context injection — full project files + DB overview before starting
3. Enforced inspect-build-verify loop — never submit unless final dbt run succeeds
4. "Stability beats cleverness"

## Root Cause Analysis Updates

| Task | Category | Root Cause | Fix Strategy |
|------|----------|-----------|-------------|
| xero001 | D (was A) | Extra account in BSR. Calendar spine correct. | Filter accounts in balance_sheet_report |
| shopify001 | A | Calendar uses global max (Sep 12) not order max (Sep 7) | Per-table date boundary tool |
| playbook002 | B | INNER JOIN in cpa_and_roas drops sources without spend | LEFT JOIN or FULL OUTER JOIN |
| reddit001 | F+C | Missing hour_comment_created_at + prod_tables_joined | Agent must read YML more carefully |
| apple_store001 | D (was B) | source_type PASSES now. territory_short values wrong | Value mapping issue |
