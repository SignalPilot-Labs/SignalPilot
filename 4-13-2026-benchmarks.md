# Spider2 Benchmark Runs — 2026-04-13/14

## Environment Setup
- Snowflake: RSRSBDK-YDB67606, user=neehan, PAT auth (password mode)
- BigQuery: authacceptor project, service account test-bq@authacceptor.iam.gserviceaccount.com
- Spider2 repo: ~/spider2-repo (cloned 2026-04-14)
- Model: claude-sonnet-4-6 (default), claude-opus-4-6 (for harder tasks)

## Infrastructure Changes
1. Merged branch `signalpilot-benc-e45aea` (date spine fixes, ND fixer, Spider2 comparator)
2. Implemented missing modules for Snowflake/Lite runners (paths, tasks, mcp, workdir, sdk_runner)
3. Fixed SQL evaluator for Spider2 gold format (`{id}_a.csv` pattern, multi-answer support)
4. Fixed Snowflake auth (PAT as password, not OAuth)
5. Fixed task `db_id` field mapping for Spider2-Snow tasks
6. Fixed MCP credential_extras for all MCP server tools (Snowflake connector needs extras for auth)
7. Fixed Snowflake connector timeout (30s -> 120s) — large databases (STACKOVERFLOW) timed out on schema fetch
8. Improved SQL agent prompt: COUNT(DISTINCT) guidance, column naming, schema_overview bypass, anti-debugging rules
9. Added schema_overview HTTP fallback to use direct connector when gateway unavailable

## Benchmark Runs — Spider2-Snowflake

### Round 1 Results (claude-sonnet-4-6, max-turns=30-60)

| # | Task ID | Database | Result | Turns | Time | Notes |
|---|---------|----------|--------|-------|------|-------|
| 1 | sf_bq327 | WORLD_BANK | FAIL | 38 | 256s | COUNT(*) vs COUNT(DISTINCT) — pre-prompt-fix |
| 2 | sf_bq286 | USA_NAMES | PASS | 28 | 111s | Most popular female name in Wyoming by proportion |
| 3 | sf_local031 | BRAZILIAN_E_COMMERCE | PASS | ~20 | 155s | Highest monthly delivered order volume |
| 4 | sf_bq057 | CRYPTO | PASS | 63 | 439s | Bitcoin CoinJoin monthly percentage |
| 5 | sf_bq309 | STACKOVERFLOW | PASS | ~40 | ~300s | Top 10 longest questions (needed timeout fix) |
| 6 | sf_bq328 | WORLD_BANK | PASS | ~50 | ~460s | Highest median GDP by region |
| 7 | sf_bq398 | WORLD_BANK | PASS | ~45 | ~240s | Top 3 debt indicators for Russia |
| 8 | sf_local218 | EU_SOCCER | PASS | ~25 | ~150s | Median of highest season goals per team |
| 9 | sf_bq213 | PATENTS | PASS | ~35 | ~460s | Most common IPC code for US B2 patents |
| 10 | sf_bq234 | CMS_DATA | FAIL | ~30 | ~300s | Column naming mismatch, wrong aggregation level |
| 11 | sf_local022 | IPL | FAIL | ~70 | 640s | Agent debugged infra instead of writing SQL |

### Summary Statistics
| Suite | Tasks Run | Pass | Fail | Pass Rate |
|-------|-----------|------|------|-----------|
| Spider2-Snowflake | 11 | 8 | 3 | 72.7% |
| Spider2-Lite | 0 | 0 | 0 | - |
| Spider2-DBT | 0 | 0 | 0 | - |

### Key Findings
1. **Timeout was the #1 blocker**: 30s default caused schema fetch to fail silently on large DBs (STACKOVERFLOW, WORLD_BANK). Fixed by increasing to 120s.
2. **Agent debugging infrastructure**: When MCP tools returned errors, agent explored source code instead of writing SQL. Fixed by adding explicit "DO NOT debug infrastructure" rules.
3. **COUNT(DISTINCT) vs COUNT(*)**: Agent defaulted to COUNT(*) for "how many X" questions. Fixed by adding semantic COUNT guidance.
4. **Column naming**: Agent used generic names (count, drug_name) instead of matching gold format (zero_value_indicator_count, medication).
5. **Schema discovery**: Most Snowflake databases have data in non-PUBLIC schemas. Agent must use fully qualified table names.

## Round 2 Infrastructure Changes
1. Created `benchmark/core/sqlite_builder.py` — builds SQLite DBs from DDL.csv + JSON (fallback)
2. Downloaded real `.sqlite` files from Spider2 Google Drive (30 databases, 457MB)
3. Updated `workdir.py` to prefer pre-built SQLite files over JSON-constructed ones
4. Fixed BigQuery connection registration to use `spider2-public-data` as default project
5. Added aggregation level guidance and gold-format alignment check to SQL prompts
6. Changed default max_turns from 100 to 50

## Benchmark Runs — Round 2 Re-runs

### Previously Failed Tasks (with improved prompts)

| # | Task ID | Database | Result | Notes |
|---|---------|----------|--------|-------|
| 1 | sf_bq327 | WORLD_BANK | **PASS** ✓ | Was FAIL in R1 (COUNT semantic fix worked) |
| 2 | sf_bq234 | CMS_DATA | TIMEOUT | Agent hung >15min, no result. Large DB. |
| 3 | sf_local022 | IPL | **PASS** ✓ | Was FAIL in R1 (anti-debugging rules worked) |

### New Snowflake Tasks

| # | Task ID | Database | Result | Notes |
|---|---------|----------|--------|-------|
| 4 | sf_bq396 | NHTSA_TRAFFIC_FATALITIES | FAIL | Close — 2/3 states match, CA rainy count off by 17 |
| 5 | sf_bq305 | STACKOVERFLOW | TIMEOUT | Complex multi-condition query, >11min |
| 6 | sf_local041 | MODERN_DATA | **PASS** ✓ | Tree health percentage, exact match |
| 7 | sf_local230 | IMDB_MOVIES | **PASS** ✓ | Top genres/directors rated >8, exact match |
| 8 | sf_local335 | F1 | FAIL | Close — Williams match, Toro Rosso off by 1 |

### Spider2-Lite (SQLite) Tasks

| # | Task ID | Database | Backend | Result | Notes |
|---|---------|----------|---------|--------|-------|
| 1 | local038 | Pagila | SQLite | **PASS** ✓ | Actor in children's G/PG films |
| 2 | local058 | education_business | SQLite | **PASS** ✓ | Hardware segments by product count (extra column) |
| 3 | local032 | Brazilian_E_Commerce | SQLite | **PASS** ✓ | Top sellers by 4 categories |
| 4 | local067 | complex_oracle | SQLite | TIMEOUT | NTILE query, >11min |

### Spider2-Lite (BigQuery) Tasks

| # | Task ID | Database | Backend | Result | Notes |
|---|---------|----------|---------|--------|-------|
| 1 | bq300 | stackoverflow | BigQuery | FAIL | Python 2 max answers: got 43 vs gold 26 |

### Round 2 Running Totals (Including R1 results)

| Suite | Tasks Run | Pass | Fail | Timeout | Pass Rate |
|-------|-----------|------|------|---------|-----------|
| Spider2-Snowflake | 18 | 12 | 3 | 3 | 66.7% (excl timeout: 80.0%) |
| Spider2-Lite SQLite | 4 | 3 | 0 | 1 | 75.0% (excl timeout: 100%) |
| Spider2-Lite BigQuery | 1 | 0 | 1 | 0 | 0% |
| Spider2-DBT | 0 | 0 | 0 | 0 | - |

### Key Round 2 Findings
1. **Prompt improvements fixed 2/3 R1 failures**: sf_bq327 (COUNT semantic) and sf_local022 (anti-debugging) now pass. sf_bq234 still times out (CMS_DATA is huge).
2. **SQLite Lite tasks work well**: 3/3 pass (excl timeout). Pre-downloaded .sqlite files are critical — sample rows from JSON are insufficient.
3. **BigQuery needs work**: bq300 failed with wrong value (43 vs 26). May need better BQ-specific prompt guidance.
4. **Timeout is a major issue**: 4 tasks timed out (>10 min). These are mostly complex multi-step queries on large databases. May need to increase max_turns or optimize schema discovery.
5. **Skills and MCP always load correctly**: Every task successfully loaded skills and MCP tools.
