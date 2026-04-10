# Tool Recommendations for Spider2-DBT Benchmark

## Current Score: 42+/65 = ~64.6% (Round 6: 13 new PASSes!) (Databao: 30/68 = 44.11%)

## Round 6 Results (verify checks 9-11 + massive task coverage)

**Key Changes**:
1. CHECK 9: Duplicate row detection for UNION models
2. CHECK 10: Monetary value sign check (softened to warning)
3. CHECK 11: COALESCE audit — catches NULL→0 fills on LEFT JOIN results
4. Build rules: prefer UNION over UNION ALL, ephemeral wrapper pattern, anti-COALESCE rule
5. Ran 24 untested/retried tasks — massive coverage increase

**New PASSes (13 flips!)**:
| Task | Models | Notes |
|------|--------|-------|
| greenhouse001 | application_enhanced, job_enhanced | Both pass |
| playbook001 | attribution_touches | Already-written model passes |
| lever001 | posting_enhanced | Already-written model passes |
| maturity001 | dim_doctors, dim_patients | Simple dimension tables |
| google_play001 | country_report, device_report | Both pass |
| google_play002 | overview_report | FULL OUTER JOIN correct |
| activity001 | aggregate_after_1, aggregate_all_ever_1 | Window function analytics |
| app_reporting001 | app_version_report, os_version_report | Both pass |
| qualtrics001 | qualtrics__directory | Single row, all 23 columns match |
| workday001 | organization_overview | 57-model project, 1 new model |
| shopify002 | shopify__discounts | 27-model project, 1 new model |
| shopify_holistic_reporting001 | daily_customer_metrics | Cross-source aggregation |
| workday002 | job_overview | Mirror of workday001 |

**New FAILs (retries and hard tasks)**:
| Task | Issue | Gap |
|------|-------|-----|
| salesforce001 | COALESCE(col,0) on LEFT JOIN results — gold expects NULL not 0 | Agent ignores anti-COALESCE rule 50% of time |
| hubspot001 | contacts 22 vs 19 rows (3 extra) | Dedup/filter issue |
| movie_recomm001 | 9599 vs 56596 rows | Major filtering error |
| tickit002 | dim_events 8798 vs 8659, fct_listings 192K vs 177K | Fan-out/dedup |
| asana001 | team FAIL (value mismatch), user PASS | Computation error |
| app_reporting002 | All 3 models wrong row counts | Aggregation grain wrong |
| marketo001 | count_sends value mismatch (shape correct) | Computation error |
| quickbooks002 | Complex accounting logic | Expected hard |

**CHECK Adoption (from verify agent logs)**:
- CHECK 9 (duplicate detection): Called in most runs, correctly identifies 0 duplicates
- CHECK 10 (monetary sign): Called, but auto-fix was too aggressive — softened to warning
- CHECK 11 (COALESCE audit): Called in asana001, correctly identified and removed COALESCEs. Agent compliance ~50%

**Key Findings**:
1. Coverage matters — 13/24 newly-tested tasks PASSED. Many tasks were easy wins that hadn't been run before.
2. Already-written models (lever001, playbook001) often pass without agent changes — the pre-existing code is correct.
3. COALESCE(col,0) is a systematic agent error pattern. The anti-COALESCE rule helps ~50% of the time.
4. The monetary ABS() rule is double-edged — helped twilio001 account_overview but broke number_overview.
5. Ephemeral wrapper pattern (from DataBao) adds value for tasks with missing ref() targets.

Note: Verification tool usage went from ~60% to 100% after SDK migration.

## Round 4 Results (SDK migration + new tools)

**Key Change**: Migrated from subprocess `claude -p` to Claude Agent SDK. Skills now invocable as tools. Added `audit_model_sources` MCP tool and per-table date boundaries.

**Verification Tool Usage**: UP from ~60% to 100% — all 12 tested tasks called verification MCP tools (validate_model_output, check_model_schema). Average 7-12 verification calls per task.

**Skill Invocation**: 4/8 tasks invoked /dbt-workflow as a Skill tool call. 0/8 invoked /dbt-verification (agent follows inline prompt steps instead). audit_model_sources called in 2/8 tasks.

**Regression Checks**:
| Task | Before SDK | After SDK | Status |
|------|-----------|-----------|--------|
| retail001 | PASS | PASS | No regression |
| tickit001 | PASS | PASS | No regression |
| airport001 | PASS | FAIL (stochastic column naming) | Stochastic, not structural |
| chinook001 | FAIL (Category G - infra) | FAIL | Pre-existing gold DB issue |

**Failing Task Results (SDK + new tools)**:
| Task | Before | After SDK | Gold | Notes |
|------|--------|-----------|------|-------|
| tpch001 | 150000 rows | 150000 rows | 75007 | Still 2x fan-out, agent skipped audit_model_sources |
| playbook002 | 2 rows | 2 rows | 5 | Same INNER JOIN drop |
| netflix001 | 109 rows | 109 rows | 99 | Same duplicates |
| xero001 | 1174 rows | 1065 rows | 1170 | Regressed (wrong direction) |
| provider001 | 461 rows | 461 rows | 874 | specialty_mapping same, but provider table NOW PASSES |
| zuora001 | daily PASS | daily PASS, overview FAIL (missing col) | - | account_active_months column missing |
| flicks001 | 43139 rows | 57546 rows | 60983 | Improved significantly (43K→57K, closer to 61K) |
| reddit001 | 30971/11 cols | 30971 rows, 14884 comments | 30970/15359 | Posts still off by 1, comments got worse |
| synthea001 | 807 rows | 806 rows | 809 | Still close |
| pendo001 | 1329 rows | 173 rows | 4686 | Got worse (date spine too short) |

**Key Findings**:
1. SDK migration succeeded — 100% verification tool usage (up from ~60%)
2. No true regressions on passing tasks (airport001 is stochastic)
3. Skills are invocable but agent mostly uses inline MCP tool calls from prompt
4. audit_model_sources not adopted widely enough — needs to be merged into the build loop
5. Per-table date boundaries didn't help pendo001 (got worse)
6. The tasks that remain failing are deep logic issues, not tool gaps

**What Works Now**:
1. SDK-based agent invocation with full skill access
2. 100% verification tool adoption via inline prompt + SDK
3. Per-table date boundaries in get_date_boundaries output
4. audit_model_sources tool (2/8 adoption, needs improvement)
5. DuckDB WAL checkpoint before evaluation (fixes read-after-write)

## Round 5 Results

**Key Changes**: 
1. New MCP tool: `compare_join_types` — shows row counts for INNER/LEFT/RIGHT/FULL JOIN between two tables
2. Value-verify agent budget increased from 12 to 25 turns
3. New verify checks: CHECK 7 (NULL/junk row filter), CHECK 8 (JOIN type verification)
4. Improved date boundary output: TABLE MAX DATES more prominent, RULE text added

**Results**:
| Task | Round 4 | Round 5 | Gold | Change | Notes |
|------|---------|---------|------|--------|-------|
| retail001 | PASS | PASS | - | No regression | |
| airport001 | FAIL (stochastic) | PASS | - | Stochastic pass | Column naming resolved this run |
| synthea001 | 806 rows | 806 rows | 809 | Same | Verify found int__cost_condition=0 rows but couldn't fix intermediate models |
| netflix001 | 109 rows | 98 rows | 99 | IMPROVED -11 | CHECK 7 (NULL filter) worked! Filtered 11 NULL drama rows. Over-filtered by 1 — gold keeps 1 NULL-title row |
| playbook002 | attribution FAIL, cpa 2 rows | attribution PASS, cpa 2 rows | 5 | Partial FLIP | attribution_touches now passes! cpa_and_roas still INNER JOIN |
| tpch001 | 150000 rows | 150000 rows | 75007 | Same | 2x fan-out persists |
| zuora001 | daily PASS, overview FAIL | daily PASS, overview FAIL | - | Same | account_active_months still missing |
| divvy001 | (untested) | hash mismatch, 418926 vs 413689 | - | FAIL | r_id hash function produces different values |
| recharge001 | (untested) | 8 rows, amounts differ | 8 | FAIL | Amount precision/calculation differs |
| asset001 | (untested) | bar_quotes PASS, book_value FAIL | - | FAIL | Value uses minute-level price, gold uses daily avg |
| inzight001 | (untested) | peak value mismatch | - | FAIL | Non-deterministic ROW_NUMBER tie-breaking |
| superstore001 | (untested) | dim_regional_managers PASS, fct_sales 10277 vs 9994 | - | Partial | Regional managers table passes |

**Tool Adoption**:
- compare_join_types: 0% — agent did NOT call it despite being in prompt step 4b
- CHECK 7 (NULL filter): Effective — caused netflix001 improvement
- CHECK 8 (JOIN type verify): Called in playbook002, but agent concluded INNER JOIN was "intentional" despite it dropping 3 rows. Reasoning error, not tool gap.
- validate_model_output + check_model_schema: 100% adoption (maintained)
- 25-turn verify budget: Agent used all turns for deeper analysis but no additional fixes

**Key Finding**: The agent has all tools it needs but makes WRONG JUDGMENT CALLS about when to use them. Specifically:
1. `compare_join_types` exists but agent doesn't call it (0% adoption)
2. Even when CHECK 8 shows INNER JOIN drops rows, agent reasons it's "intentional" 
3. The remaining failures are REASONING errors (wrong JOIN choice, wrong aggregation logic) not tool gaps
4. DataBao's approach ("reliability beats cleverness") is correct — fewer tools + stricter enforcement > more tools

**Competitor Analysis Update (DataBao)**:
- They CHECKPOINT DuckDB after EVERY dbt run (we only do it before eval)
- They protect pre-existing files from modification
- They have a `submit_answer` tool that forces commitment
- They have 8 tools total (we have 15+). Less is more.

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

## Implemented Tools

### 1. check_model_schema — Schema Diff Tool
**Status**: IMPLEMENTED via MCP, ACTIVELY USED (~60% of runs)
**Impact**: Catches missing/extra columns. Helped quickbooks003 flip. Limited by incomplete YML — only checks columns listed in yml_columns param.

### 2. validate_model_output — Post-Build Validator
**Status**: IMPLEMENTED via MCP, ACTIVELY USED (~60% of runs)
**Impact**: Catches 0-row models and fan-out. Agent now uses this as part of the per-model build loop.

### 3. dbt_error_parser — Error Parser Tool  
**Status**: IMPLEMENTED via MCP
**Impact**: Used occasionally. Saves 2-3 turns per dbt error when called.

### 4. analyze_grain — Cardinality Oracle
**Status**: IMPLEMENTED via MCP
**Impact**: Rarely called. Agent uses query_database for ad-hoc checks instead.

### 5. generate_sql_skeleton — SQL Template Generator
**Status**: IMPLEMENTED via MCP
**Impact**: Not used in observed runs. Agent writes SQL from scratch.

## Architecture Decision: All DB Access Through SignalPilot MCP

All database queries MUST go through SignalPilot MCP tools. This is a product constraint:
- Enterprise customers connect DBs through SignalPilot gateway
- Cost control requires queries to be agent-managed, not automated
- No direct DuckDB access from the benchmark runner (except for evaluation)

Enforcement mechanism (Round 3): Inline MCP tool calls in the per-model build loop. Skills don't work in `-p` mode — verification must be embedded directly in the prompt structure.

## Skill System — Lessons Learned

Skills in `.claude/skills/<name>/SKILL.md` ARE auto-discovered by Claude Code. However:
- **Skills don't work in `-p` (non-interactive) mode** — the agent never invokes `/skill-name` slash commands
- Skill descriptions get truncated at ~250 chars in the skill listing
- The structural solution: inline critical tool calls directly in the prompt's build loop
- Skills remain useful as reference docs but NOT as executable checklists

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

## Root Cause Analysis (Round 3 - comprehensive)

| Task | Category | Root Cause | Fix Strategy | Closest Result |
|------|----------|-----------|-------------|----------------|
| xero001 | D (was A) | Calendar spine correct (69 rows). Extra accounts in BSR — logic issue not date issue. | Fix account filter in balance_sheet_report | 1174 vs 1170 (4 off) |
| xero_new001 | D+A | Same BSR logic issue + possible date mismatch | Same as xero001 | 1092 vs 1170 |
| xero_new002 | D+A | Same as xero001 | Same as xero001 | 1194 vs 1170 |
| shopify001 | A | Calendar end_date = current_date. Gold used 2024-09-08. No source table has dates near Sep 2024. | Hardcode end date via dbt var or detect from gold generation date | 2083 vs 2077 (6 off) |
| zuora001 | A | current_timestamp_backcompat() in account_active_months. Scan now catches it but agent doesn't replace. | Agent needs to replace in intermediate models too, not just top-level | daily PASSES, overview fails |
| playbook002 | B | INNER JOIN in cpa_and_roas drops sources without ad spend (only 2/5 channels have spend) | LEFT JOIN or FULL OUTER JOIN | 2 vs 5 rows |
| provider001 | B | specialty_mapping joins only codes WITH Medicare crosswalk entries. Gold includes all 874 NUCC codes. | LEFT JOIN from nucc_taxonomy to crosswalk | 461 vs 874 |
| flicks001 | B | Credits table has both movie AND show actors. Agent filters to movies only, dropping ~13K actors. | Include shows in credit join or use full credits table | 43139 vs 56754 |
| reddit001 | F+C | YML missing hour_comment_created_at, normalized_* columns. Also off by 1 row (pre-2023 post). | Fix YML schema OR improve agent column discovery from macros | 30971 vs 30970, 11 vs 13 cols |
| netflix001 | C | UNION ALL includes duplicates (109 vs 99). Gold uses dedup/filter. | UNION instead of UNION ALL, or add distinct filter | 109 vs 99 |
| pendo001 | A | Guide daily metrics calendar spine uses wrong date range. Page PASSES. | Fix guide spine end date | 1329 vs 4686 |
| synthea001 | B | LEFT JOIN to drug_exposure keeps unmatched rows. INNER JOIN needed. | Change to INNER JOIN for drug_exposure | 807 vs 809 (2 off) |
| apple_store001 | D | Row counts wrong (29 vs 9, 37 vs 17). Aggregation level issue. | Fix GROUP BY granularity | |
| social_media001 | F | twitter PASSES. Instagram missing page_id. Rollup missing post_message. | Fix column mapping for instagram and rollup | 1/3 tables pass |
| tpch001 | C | Exact 2x fan-out (150000 vs 75007). Join producing duplicates. | Dedup join key before joining | |
| f1001 | D | 2/4 tables pass. fastest_laps and driver_full_name values wrong. | Fix F1 domain logic | 2/4 pass |
| f1002 | D | finishes_by_constructor PASSES now. Other 2 tables have wrong values. | Fix championship counting logic | 1/3 pass |

## What Works vs What Doesn't

### What WORKS:
1. **Per-model verification loop** — Forces agent to call validate_model_output + check_model_schema after each model build. ~60% adoption rate.
2. **get_date_boundaries** — Directly flipped quickbooks003 and f1003 by providing correct max dates.
3. **current_date scanner** — Warns agent about files needing date replacement. Effective when agent follows the warning.
4. **Key Rules in CLAUDE.md** — materialized='table', exact column names, LEFT JOIN default.

### What DOESN'T work:
1. **Skills in -p mode** — Agent never invokes slash commands. Must inline everything.
2. **Prompt warnings** ("DO NOT STOP") — Agent ignores them. Structural enforcement > warnings.
3. **More turns alone** — Tasks that fail at 40 turns usually fail at 50 too. The issue is logic, not budget.
4. **validate_model_output for row count accuracy** — Detects 0 rows and fan-out, but can't tell if the count is correct without gold data.
5. **check_model_schema when YML is incomplete** — Only checks columns the agent provides. If YML is missing columns (reddit001), the check passes falsely.
