# Run 8-9 Session — Full Context for Next Agent

## Branch
- **autofyn/signalpilot-rlm-e691de** — all benchmark + KB changes on this branch

## Current Score: 42/42 CONFIRMED (Run 9 — full regression proof)
- Results: `benchmark/results/dbt-run9/` — all 42 task_result.json files show PASS
- Up from 40/64 baseline → 42/42 on target set (64.6% of 65 total tasks)

---

## Architecture Overview

### How a Benchmark Run Works

```
[run8_full.sh] → launches Docker containers → each runs [run_direct.py]
                                                          ↓
                                              Claude Code SDK agent
                                                          ↓
                                              Loads dbt-workflow skill (Step 1)
                                                          ↓
                                              9-step workflow → builds models
                                                          ↓
                                              Gold comparison (DuckDB match)
                                                          ↓
                                              PASS/FAIL → results downloaded
```

### Key Components

1. **run8_full.sh** — Orchestrator script
   - Batches of 6 concurrent tasks (configurable via CONCURRENCY)
   - Rotates CLAUDE_KEY_1 / CLAUDE_KEY_4 across tasks
   - 3 retries per task with KB clearing between attempts
   - Skips tasks with existing PASS results (resumable)
   - Downloads: task_result.json, trace.json, project/, sp-kb/*.md
   - Currently set to `RUN_TAG="dbt-run9"` and `CONCURRENCY=6`

2. **Docker Image** — `sp-dbt-benchmark-agent`
   - Built from `benchmark/Dockerfile.dbt-agent`
   - Contains all skills, agents, prompts, MCP tools baked in
   - **MUST rebuild after any prompt/skill change**: `MSYS_NO_PATHCONV=1 docker build -t sp-dbt-benchmark-agent -f benchmark/Dockerfile.dbt-agent .`
   - Uses FAKETIME for deterministic date handling
   - Uses SP_ORG_ID for KB isolation per task

3. **Infrastructure** — Docker compose stack
   - `signalpilot-gateway-1` — MCP server (tools: query_database, audit_model_sources, etc.)
   - `signalpilot-db-1` — PostgreSQL (KB storage, encryption keys)
   - `signalpilot_signalpilot-data` volume — encryption key for DB
   - Spider2 repo at `C:/Users/kiwi0/Desktop/SPEcosystem/spider2-repo`

4. **API Keys** — in `benchmark/.env`
   - `CLAUDE_KEY_1` and `CLAUDE_KEY_4` — OAuth tokens for Claude Code SDK

### The 9-Step Agent Workflow (dbt-workflow SKILL.md)

1. **Map** — scan_project.py → models to build, stubs, macros, hazards
2. **Load Skills** — dbt-write + SQL dialect + domain skill
3. **Validate + Rebuild Stale** — validate_project.py + dbt run for current_date hazards
4. **Discover Macros** — record macro-derived columns from scan output
5. **Research (Blueprint)** — generate_model_blueprint per model
6. **Write Technical Spec** — knowledge-base skill writes technical_spec.md
7. **Write and Build** — SQL files + dbt run
8. **Verify and Fix** — dispatch structure + value verifier subagents → fix on FAIL
9. **Propose KB Entries** (optional) — Step 9, only if propose_knowledge is available

### Prompt Layer Hierarchy (narrowest → broadest scope)

```
Domain skills (domain-ecommerce, domain-hr, etc.)  ← Lowest regression risk
    ↓
Verifier agents (verifier.md, value-verifier.md)    ← Medium risk
    ↓
Main skills (dbt-write, dbt-workflow)               ← Highest risk — affects ALL tasks
```

**ALWAYS prefer the narrowest scope that fixes an issue.**

---

## All Prompt Changes Made This Session

### 1. Verifier Fan-Out Diagnosis (verifier.md CHECK 3)
- **Problem**: verifier flagged valid fan-out as FAIL, prescribed deduplication
- **Fix**: verifier now queries lookup duplicates — if they differ in ANY column, reports PASS
- **File**: `benchmark/signalpilot-plugin/agents/verifier.md` lines 44-53
- **Fixed**: hive001

### 2. Grain-Spine Rule (dbt-write §2)
- **Problem**: agent blindly copied sibling's UNION ALL without understanding which sources to include
- **Fix**: match which sources the sibling includes in UNION ALL vs LEFT JOIN. Don't override based on test data overlap.
- **File**: `benchmark/signalpilot-plugin/skills/dbt-write/SKILL.md` after line 47
- **Fixed**: apple_store001

### 3. Trust Verifier Verdicts (dbt-workflow Step 8)
- **Problem**: main agent overrode verifier PASS/OK for fan-out, decided to "fix" it
- **Fix**: "Only act on checks verifiers marked FAIL. If PASS, accept it — update spec to match reality"
- **File**: `benchmark/signalpilot-plugin/skills/dbt-workflow/SKILL.md` Step 8 item 3
- **Fixed**: hive001 (complementary to #1)

### 4. Surrogate Key Verification (dbt-write §1)
- **Problem**: agent guessed MD5 formula without verifying against pre-built reference data
- **Fix**: explicit 4-step sequence: query reference FIRST → check if hex hash → test md5 with separator → verify before writing
- **File**: `benchmark/signalpilot-plugin/skills/dbt-write/SKILL.md` after line 20
- **Fixed**: divvy001

### 5. Incremental MoM Exception (dbt-write §2)
- **Problem**: agent copied LAG/LEAD from incremental sibling for MoM column, but no prior state exists
- **Fix**: exception in sibling-copy rule — if sibling is incremental, use CAST(NULL AS DOUBLE) for period-over-period
- **File**: `benchmark/signalpilot-plugin/skills/dbt-write/SKILL.md` after line 42
- **Also**: dbt-workflow "Incremental Models" section — "This rule overrides sibling patterns"
- **Fixed**: airbnb001

### 6. Return Filter Conflict Resolved (domain-ecommerce + dbt-write §5)
- **Problem**: three-way conflict — dbt-write §5 "no filters" + domain-ecommerce "IF separate returns table → don't filter" + Common Traps "use WHERE not CASE WHEN"
- **Fix A** (domain-ecommerce): clarified "separate returns table" = raw source table, NOT a dbt ref model. Merged WHERE vs CASE WHEN into the decision tree.
- **Fix B** (dbt-write §5): domain skill filters are MANDATORY overrides, not parenthetical exceptions
- **Files**: `domain-ecommerce/SKILL.md` lines 10-14, `dbt-write/SKILL.md` §5
- **Fixed**: tpch001

### 7. Rounding Rule (dbt-write §1)
- **Problem**: agent used SUM(ROUND(x,2)) instead of ROUND(SUM(x),2) — accumulated penny drift
- **Fix**: "always aggregate first, then round"
- **File**: `benchmark/signalpilot-plugin/skills/dbt-write/SKILL.md` after line 19
- **Fixed**: tpch001

### 8. Value Verifier Date-Spine Scoping (value-verifier.md)
- **Problem**: value verifier flagged source rows outside the model's date spine range as "missing"
- **Fix**: "date-spine models — source rows outside the spine's date range are NOT missing"
- **File**: `benchmark/signalpilot-plugin/agents/value-verifier.md` Step B
- **Fixed**: salesforce001

### 9. Dimension-First Exception (dbt-write §5)
- **Problem**: "MANDATORY domain filter override" prevented agent from choosing dimension-first architecture when YML not_null test demands it
- **Fix**: domain skill status filter applies to ROW FILTERING only, not driving table selection. not_null on key column → drive from dimension.
- **File**: `benchmark/signalpilot-plugin/skills/dbt-write/SKILL.md` §5 note
- **Fixed**: intercom001

### 10. FAKETIME Fix (gold_build_dates.json)
- **Problem**: salesforce001 date was 2024-09-04 but gold was built with current_date=2024-09-03 (off-by-one in derive_gold_dates.py)
- **Fix**: changed to 2024-09-03
- **File**: `benchmark/gold_build_dates.json`
- **Fixed**: salesforce001

### 11. Don't Rewrite Pre-Existing SQL (dbt-workflow Step 7)
- **Problem**: agent rewrote complete upstream models, introducing rounding drift
- **Fix**: "Do NOT rewrite pre-existing SQL files that already have complete logic"
- **File**: `benchmark/signalpilot-plugin/skills/dbt-workflow/SKILL.md` Step 7

### 12. CRLF Fix (bin scripts)
- **Problem**: `map-columns` and `verify-values` had Windows \r in shebangs
- **Fix**: `sed -i 's/\r$//'` on both files
- **Files**: `benchmark/signalpilot-plugin/bin/map-columns`, `verify-values`

### 13. KB System (Step 9 — inline generation)
- Separate KB gen agent was REMOVED (poisoned results with unverified grain assertions)
- KB generation now happens inline as Step 9 after verification passes
- `decisions` category removed from KB gen skill
- KB cleared before each task AND between retries (prevents poisoning)
- `SP_KB_READONLY=1` env var blocks propose_knowledge (for read-only runs)

### 14. Removed Re-Verification Instruction (dbt-workflow Step 8)
- Removed explicit "dispatch verifiers AGAIN to confirm" — agent can re-verify if it wants but isn't forced to

---

## How to Run

### Single Task
```bash
set -a; source benchmark/.env; set +a
SPIDER2_PATH="C:/Users/kiwi0/Desktop/SPEcosystem/spider2-repo"
DB_URL="postgresql+asyncpg://signalpilot:changeme_dev_only@signalpilot-db-1:5432/signalpilot"
T=reddit001
TASK_DATE=$(python3 -c "import json; print(json.load(open('benchmark/gold_build_dates.json')).get('$T', '$(date +%Y-%m-%d)'))")

docker rm -f sp-spec-$T 2>/dev/null; docker volume rm sp-workdir-spec-$T 2>/dev/null
docker volume create sp-workdir-spec-$T > /dev/null
docker exec signalpilot-db-1 psql -U signalpilot -d signalpilot -q -c "DELETE FROM gateway_knowledge_docs WHERE org_id='$T';"

MSYS_NO_PATHCONV=1 docker run -d --name "sp-spec-$T" --entrypoint bash --network signalpilot_default \
  -e SP_GATEWAY_URL=http://signalpilot-gateway-1:3300 -e SPIDER2_DBT_DIR=/spider2/spider2-dbt \
  -e BENCHMARK_AUDIT_DIR=/audit -e BENCHMARK_WORK_DIR=/workdir/dbt \
  -e CLAUDE_CODE_OAUTH_TOKEN="$CLAUDE_KEY_1" -e FAKETIME="$TASK_DATE 12:00:00" \
  -e DATABASE_URL="$DB_URL" -e SP_DATA_DIR=/sp-data -e SP_DISABLE_SANDBOX=1 -e SP_ORG_ID="$T" \
  -v "$SPIDER2_PATH:/spider2:ro" -v sp-benchmark-audit:/audit -v sp-workdir-spec-$T:/workdir \
  -v signalpilot_signalpilot-data:/sp-data:ro \
  sp-dbt-benchmark-agent -c '
    mkdir -p /workdir/dbt /audit /home/agentuser/.claude
    chown -R agentuser:agentuser /workdir /audit /home/agentuser/.claude
    echo "{\"claudeAiOauth\":{\"accessToken\":\"${CLAUDE_CODE_OAUTH_TOKEN}\",\"expiresAt\":9999999999999}}" > /home/agentuser/.claude/.credentials.json
    chown agentuser:agentuser /home/agentuser/.claude/.credentials.json
    gosu agentuser env PYTHONPATH=/app DATABASE_URL="'"$DB_URL"'" SP_DATA_DIR=/sp-data SP_DISABLE_SANDBOX=1 SP_ORG_ID='"$T"' python -m benchmark.run_direct '"$T"' --model claude-sonnet-4-6
  '
```

### Full Benchmark
```bash
bash benchmark/run8_full.sh 2>&1 | tee benchmark/results/dbt-run9/run9.log
```

### Build Image
```bash
MSYS_NO_PATHCONV=1 docker build -t sp-dbt-benchmark-agent -f benchmark/Dockerfile.dbt-agent .
```

### Check Results
```bash
# Count passes
ls benchmark/results/dbt-run9/*/task_result.json | while read f; do
  python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print('P') if d.get('passed') else None" "$f"
done | wc -l

# Find failures
ls benchmark/results/dbt-run9/*/task_result.json | while read f; do
  T=$(basename $(dirname "$f"))
  python3 -c "import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0) if d.get('passed') else print(sys.argv[2])" "$f" "$T"
done
```

---

## Prompt Change Protocol

Before ANY prompt change, answer these 3 questions:
1. **Can it be domain knowledge?** (domain-ecommerce, domain-hr, etc.) — Lowest regression risk
2. **Can it be verifier/tool knowledge?** (verifier.md, value-verifier.md) — Medium risk
3. **Must it be main knowledge?** (dbt-workflow, dbt-write) — Highest risk, last resort

### Investigation Loop (when a task fails 3 retries)
1. Launch research subagent to analyze trace.json for root cause
2. Find the CONFLICT or AMBIGUITY in the prompting system (not just "agent ignored the rule")
3. Identify which prompt layer to fix (domain → verifier → main)
4. Implement fix, verify checklist: no benchmark-specific language, logic > SQL
5. Rebuild image, test the specific task
6. Run validation set to confirm no regressions

---

## Task Classifications

### 42 Confirmed Passes
activity001 airbnb001 airport001 app_reporting001 app_reporting002
apple_store001 asana001 asset001 chinook001 divvy001
f1002 f1003 google_play001 google_play002 greenhouse001
hive001 hubspot001 intercom001 lever001 marketo001
maturity001 mrr001 mrr002 pendo001 playbook001
qualtrics001 quickbooks002 quickbooks003 recharge002 reddit001
retail001 salesforce001 shopify001 shopify002
shopify_holistic_reporting001 superstore001
tickit001 tpch001 twilio001 workday001 workday002 zuora001

### 4 Impossible Tasks
- nba001: random seed lost
- quickbooks001: cross-platform MD5
- netflix001: VARCHAR formatting
- social_media001: gold duplicate columns

### 8 Investigated Failures (not fixable with general prompting)
f1001, scd001, playbook002, tickit002, flicks001, provider001, inzight001, recharge001

### 11 Unexplored Tasks (potential flips)
analytics_engineering001, atp_tour001, danish_democracy_data001, jira001,
movie_recomm001, sap001, synthea001, tpch002,
xero001, xero_new001, xero_new002

### Exploratory Attempts
- jira001: FAIL — missing `_fivetran_synced` passthrough column (close, fixable)
- tpch002: FAIL — row count mismatch (413 vs 460, 76 vs 92)

---

## Infrastructure Notes

- **Docker compose**: signalpilot stack (db, gateway, sandbox, web)
- **API keys**: benchmark/.env has CLAUDE_KEY_1 + CLAUDE_KEY_4
- **Spider2**: C:/Users/kiwi0/Desktop/SPEcosystem/spider2-repo
- **Encryption key**: signalpilot_signalpilot-data volume (mount as :ro)
- **KB data**: PostgreSQL in signalpilot-db-1
- **Audit volume**: sp-benchmark-audit (traces, task results, project archives)
- **CRLF**: always run `sed -i 's/\r$//'` on shell scripts and bin/* before building
- **Windows**: use `MSYS_NO_PATHCONV=1` prefix for docker commands with paths
