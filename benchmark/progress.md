# Spider2-DBT Benchmark Progress

## Current Score
- **29/63 evaluable tasks = 46.0%** (29/66 total = 43.9%)
- Databao (current #1): 30/68 = 44.11%
- **We are beating Databao by ~2 percentage points**

## What Works

### Skills System
- Moving dbt-specific rules from the bloated system prompt into focused skill files improved token efficiency
- Skills are discovered at session start via `.claude/skills/` directory
- Three key skills: `dbt/patterns`, `dbt/expert`, `duckdb/patterns`
- Skills loaded on-demand by the agent (step 3b in workflow)

### SignalPilot MCP Integration
- `list_tables` gives agent row counts, PKs, FKs upfront — saves exploration turns
- `explore_table` shows schema + sample data efficiently
- `query_database` allows verification queries without raw SQL execution
- `get_date_boundaries` returns GLOBAL MAX DATE across all date/timestamp columns
- Connection registered per-task with isolated DuckDB file

### Multi-Agent Pipeline
- Main agent (20 turns) → quick-fix agent (20 turns if dbt fails) → value-verify agent (12 turns) → name-fix agent (8 turns if tables missing)
- Each agent is clean — no gold data leaking
- Retry on API 529/overload with exponential backoff

### Prompt Engineering
- Task-specific CLAUDE.md with eval-critical models, column specs, dependencies
- Turn budget allocation (discovery → build → verify)
- Priority model hard checkpoint at turn 6
- 5-step row count audit protocol
- Sample value check for silent failure detection

### Key Skill Rules That Flipped Tasks
- MRR change_category: "read project .md docs for exact enum values" → flipped mrr001, mrr002
- Output shape inference: "top N → QUALIFY DENSE_RANK, rolling window → point-in-time" → flipped tpch001
- Model discovery beyond YAML: "scan task instruction for model names not in YML" → helped activity001

## What Doesn't Work

### Date Spine / CURRENT_DATE (7 tasks blocked)
The #1 failure category. Tasks: salesforce001, shopify001, xero001, xero_new001, xero_new002, quickbooks003, pendo001.

**Problem**: dbt package models use `current_date` as the spine endpoint. When run in 2026, spines extend years past the gold data's date range, inflating row counts.

**Attempted fixes**:
1. Prompt rule: "never use current_date for spine endpoints" — agent reads but doesn't override package models
2. Skill rule: "Date Spine — CURRENT_DATE Is Forbidden" — same result
3. MCP tool `get_date_boundaries`: returns the correct max date, agent acknowledges it, but still doesn't edit the package spine model
4. Mandatory workflow step 2b: agent gets the date, still doesn't act on it

**Root cause**: The agent treats dbt package models as read-only. It needs to learn to override/patch package models when they contain `current_date`.

**Next step**: Add a skill or prompt instruction that explicitly says: "If a package model uses `current_date`, create a local override in `models/` with the same filename — dbt prioritizes local files over package files."

### Wrong JOIN Type (4 tasks)
Tasks: apple_store001, flicks001, playbook002, provider001.
Agent defaults to INNER JOIN when LEFT JOIN is needed. Existing skills cover this but the agent doesn't apply the guidance consistently.

### Non-Deterministic Ordering (2 tasks)
Tasks: superstore001, chinook001.
`ROW_NUMBER() OVER (ORDER BY NULL)` produces different IDs per run. chinook001 also has an infra issue (gold DB not properly built).

### Agent Doesn't Self-Correct on Value Mismatches
The value-verify agent catches some issues but can't fix fundamental logic errors. Tasks like f1001, scd001, and quickbooks001 have correct row counts but wrong computed values.

## External Research

### Databao's Approach (44.11%)
From their published blog post:
1. Context upfront — project files + database overview at initialization
2. Constrained tools — only specific dbt commands
3. Linear workflow — inspect → minimal changes → verify → validate
4. Clean policy prompt — single coherent prompt
5. No clever mechanisms — multiple-run selection and simulated reviewers degraded reliability

Key insight: **stability beats cleverness**. We already implement most of these patterns.

### Official Evaluation Details
- All tasks use `duckdb_match` — column vectors compared independently
- Columns matched by VALUE not position — any pred column can match any gold column
- `abs_tol=1e-2` for numeric comparison
- Row order always ignored (`ignore_order=True` for all tasks)
- Our local eval faithfully replicates the official comparison

## Architecture

```
benchmark/
├── run_direct.py          # Main runner (prompt, agents, eval)
├── skills/
│   ├── dbt/patterns/      # Core dbt rules
│   ├── dbt/expert/        # Advanced patterns (shape inference, cardinality)
│   └── duckdb/patterns/   # DuckDB-specific SQL rules
├── mcp_test_config.json   # MCP server config
└── _dbt_workdir/          # Per-task working directories

signalpilot/gateway/
├── gateway/mcp_server.py  # MCP tools (list_tables, explore, query, get_date_boundaries)
└── ...
```

## Next Steps (Priority Order)

1. **Fix date spine override** — Teach agent to create local overrides for package models using `current_date`. This could flip 5-7 tasks.
2. **Add LEFT JOIN bias** — Strengthen the skill to prefer LEFT JOIN in reporting/aggregation models. Could flip 2-4 tasks.
3. **Add TRY_STRPTIME rule** — For tasks with malformed date strings (atp_tour001). Easy fix.
4. **Stub replacement** — Ensure agent recognizes and replaces placeholder stubs (tpch002). Already partially handled.
5. **Run with Opus** — For tasks requiring complex reasoning (f1001, scd001, synthea001), Opus might produce better SQL logic.

## API Usage Notes
- Each task run costs ~$0.50-2.00 depending on turns and sub-agents
- Run 2-3 tasks in parallel to manage rate limits
- API overload errors handled with exponential backoff (30s, 60s, 90s)
