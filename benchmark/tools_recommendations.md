# Tool Recommendations for Spider2-DBT Benchmark

## Current Score: 29/65 = 44.6% (Databao: 30/68 = 44.11%)

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

## Round 3 Results (per-model verification loop + expanded current_date scan)

**Key Change**: Restructured prompt from "build all models then verify" to "per-model loop: build → verify → fix → next". Also expanded `current_date` scanner to catch `current_timestamp`, `current_timestamp_backcompat`, `getdate()`.

**New Flips**:
| Task | Before | After | Root Cause Fixed |
|------|--------|-------|-----------------|
| quickbooks003 | FAIL (1536/4224 rows) | PASS | Date spine capped by get_date_boundaries |
| f1003 | FAIL (wrong ages) | PASS | current_date in age calc replaced with get_date_boundaries max |

**Improvements Without Flipping**:
| Task | Before | After | Gold | Notes |
|------|--------|-------|------|-------|
| xero001 | 1194 rows | 1174 rows | 1170 | Down from 24 off to 4 off |

**Verification Tool Usage** (per-model loop):
- ~60% of tasks now call validate_model_output and check_model_schema
- Previously: 0% called any verification tools
- Tasks that use verification: playbook002, reddit001, provider001, netflix001, xero001, zuora001, pendo001, recharge002
- Tasks that skip verification: flicks001, quickbooks003, synthea001, twilio001

**No Regressions**: airport001, retail001, tickit001 all still PASS

### Key Finding: Skills don't work in -p mode
Slash commands like `/dbt-verification` are never invoked in non-interactive `-p` mode. Fixed by inlining verification MCP tool calls directly into the per-model build loop. The structural change (verification as a sub-step of building) is more effective than prompt warnings ("DO NOT STOP").

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
| 1 | Improve current_date replacement guidance | zuora001, recharge002, f1003-related | Low — scan works, agent needs stronger replacement guidance |
| 2 | Ensure agent replaces ALL current_timestamp variants | xero_new001, xero_new002, shopify001 | Medium — agent partially fixes but misses some files |
| 3 | Better column discovery (agent reads incomplete YML) | reddit001, social_media001, nba001, scd001 | Medium — need tool to compare against actual table columns |
| 4 | Per-table date boundary (not just global max) | shopify001, pendo001 | Medium — new MCP tool |
| 5 | Increase max_turns for complex tasks | f1001, tpch002, social_media001, jira001 | Config change |

## Competitor Analysis (Databao - #1 at 44.11%)

From their approach:
1. Restricted tools — narrow set: dbt run, dbt build, file writes locked to .sql only
2. Upfront context injection — full project files + DB overview before starting
3. Enforced inspect-build-verify loop — never submit unless final dbt run succeeds
4. "Stability beats cleverness"

## Root Cause Analysis Updates

| Task | Category | Root Cause | Fix Strategy |
|------|----------|-----------|-------------|
| xero001 | A | 1174 rows vs gold 1170 (down from 1194). Calendar spine still slightly over-extends. | Cap spine tighter at max(journal_date) |
| shopify001 | A | Calendar uses global max (Sep 12) not order max (Sep 7) | Per-table date boundary tool |
| playbook002 | B | INNER JOIN in cpa_and_roas drops sources without spend | LEFT JOIN or FULL OUTER JOIN |
| reddit001 | F+C | Missing hour_comment_created_at + prod_tables_joined | Agent must read YML more carefully |
| apple_store001 | D (was B) | source_type PASSES now. territory_short values wrong | Value mapping issue |
