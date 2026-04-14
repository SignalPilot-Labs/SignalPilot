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
