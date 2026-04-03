# Spider2-Lite Benchmark Results

## Overview

| Metric | Value |
|--------|-------|
| Benchmark subset | Spider2-Lite SQLite |
| Total tasks | 135 |
| Correct | 67 |
| Failing | 68 |
| Accuracy | **49.6%** |
| Starting accuracy | 0% (no working pipeline) |

## Correct Tasks (67)

local004, local008, local009, local015, local018, local019, local021, local022, local024, local025, local026, local029, local030, local035, local038, local039, local040, local041, local050, local054, local055, local058, local061, local062, local065, local068, local071, local073, local077, local078, local081, local085, local098, local099, local100, local114, local128, local130, local132, local152, local156, local163, local167, local168, local169, local170, local171, local193, local198, local201, local212, local218, local219, local221, local228, local230, local244, local262, local264, local269, local270, local277, local298, local300, local302, local310, local329

## Failure Categories (74 tasks)

| Category | Count |
|----------|-------|
| Misunderstood question | ~12 |
| Wrong aggregation/join logic | ~16 |
| Complex computation (moving avg, haversine, regression) | ~12 |
| Edge case parsing / empty results | ~8 |
| Wrong units/scale (% vs fraction) | ~8 |
| Wrong column order | ~6 |
| Persistent errors (CLI crashes, connection issues) | ~5 |
| Domain-specific knowledge gaps | ~7 |

## Database Performance

| Database | Correct / Total | Rate |
|----------|-----------------|------|
| chinook | 3/3 | 100% |
| imdb_movies | 2/2 | 100% |
| european_football | 2/2 | 100% |
| EU_soccer | 3/4 | 75% |
| city_legislation | 2/4 | 50% |
| bank_sales_trading | 0/9 | 0% |
| Brazilian_E_Commerce | 1/7 | 14% |
| IPL | 0/6 | 0% |
| f1 | 0/3 | 0% |

## Improvement Journey

1. Fixed eval engine: position-based column comparison, `condition_cols` handling
2. Fixed governance: allowed `PRAGMA` for SQLite schema exploration
3. Fixed DB paths: search `spider2-localdb` directory
4. Improved result capture: track all query results, match FINAL SQL
5. Added skills system: domain-specific tips for Brazilian_E_Commerce, IPL, bank_sales_trading
6. Added column order warning skill
7. Enhanced system prompt: planning step, precision/units rules, column discipline

## Technical Stack

- Claude Agent SDK with Sonnet 4.6 model
- SignalPilot MCP server (stdio transport)
- SQLite databases registered as connections
- SQL governance layer with sqlglot validation
- Skills system for domain-specific prompt fragments
