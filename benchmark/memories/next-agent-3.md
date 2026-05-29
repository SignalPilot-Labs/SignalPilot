# Benchmark + Knowledge Base Session State — Full Context

## Branches
- **benchmarking** (HEAD: 3ecf26b): benchmark skills + prompt fixes, 43/64 (67.2%)
- **autofyn/signalpilot-rlm-e691de** (HEAD: 134c91a): merged benchmarking + KB system
  - KB generation, parallel isolation, enhanced audit tool, all prompt fixes

## Benchmark Score
- **43/64 (67.2%)** projected — up from 40/64 (62.5%) in run6
- Run4 baseline was 33/64 (51.6%)
- Flips: tpch001, hive001, twilio001 (from benchmarking branch)
- dbt-consistent dir has 40/64 — needs updating with 3 new flips

## How to Run Benchmarks

### Prerequisites
- Docker compose stack running: `docker compose up -d` (db, gateway, sandbox, web)
- Spider2 repo at: `C:/Users/kiwi0/Desktop/SPEcosystem/spider2-repo`
- API keys in `benchmark/.env`: CLAUDE_KEY_1 and CLAUDE_KEY_4 (KEY_2 dead, KEY_3 rate limited)
- Encryption key on volume: `signalpilot_signalpilot-data:/.encryption_key`

### Build the image
```bash
MSYS_NO_PATHCONV=1 docker build -t sp-dbt-benchmark-agent -f benchmark/Dockerfile.dbt-agent .
```

### Run a benchmark task (WITHOUT KB)
```bash
set -a; source benchmark/.env; set +a
SPIDER2_PATH="C:/Users/kiwi0/Desktop/SPEcosystem/spider2-repo"
T=reddit001
TASK_DATE=$(python3 -c "import json; print(json.load(open('benchmark/gold_build_dates.json')).get('$T', '$(date +%Y-%m-%d)'))")

docker rm -f sp-spec-$T 2>/dev/null; docker volume rm sp-workdir-spec-$T 2>/dev/null
docker volume create sp-workdir-spec-$T > /dev/null

MSYS_NO_PATHCONV=1 docker run -d \
  --name "sp-spec-$T" --entrypoint bash --network signalpilot_default \
  -e SP_GATEWAY_URL=http://signalpilot-gateway-1:3300 \
  -e SPIDER2_DBT_DIR=/spider2/spider2-dbt \
  -e BENCHMARK_AUDIT_DIR=/audit \
  -e BENCHMARK_WORK_DIR=/workdir/dbt \
  -e CLAUDE_CODE_OAUTH_TOKEN="$CLAUDE_KEY_1" \
  -e FAKETIME="$TASK_DATE 12:00:00" \
  -v "$SPIDER2_PATH:/spider2:ro" \
  -v sp-benchmark-audit:/audit \
  -v sp-workdir-spec-$T:/workdir \
  sp-dbt-benchmark-agent -c "
    mkdir -p /workdir/dbt /audit /home/agentuser/.claude
    chown -R agentuser:agentuser /workdir /audit /home/agentuser/.claude
    echo '{\"claudeAiOauth\":{\"accessToken\":\"'\${CLAUDE_CODE_OAUTH_TOKEN}'\",\"expiresAt\":9999999999999}}' > /home/agentuser/.claude/.credentials.json
    chown agentuser:agentuser /home/agentuser/.claude/.credentials.json
    gosu agentuser env PYTHONPATH=/app python -m benchmark.run_direct $T --model claude-sonnet-4-6
  " > /dev/null 2>&1
```

### Run WITH Knowledge Base (RLM branch only)
Requires extra env vars and volume mount:
```bash
DB_URL="postgresql+asyncpg://signalpilot:changeme_dev_only@signalpilot-db-1:5432/signalpilot"

# Add these to docker run:
-e DATABASE_URL="$DB_URL" \
-e SP_DATA_DIR=/sp-data \
-e SP_DISABLE_SANDBOX=1 \
-e SP_ORG_ID="$T" \
-v signalpilot_signalpilot-data:/sp-data:ro \

# And pass to gosu command:
gosu agentuser env PYTHONPATH=/app DATABASE_URL='$DB_URL' SP_DATA_DIR=/sp-data SP_DISABLE_SANDBOX=1 SP_ORG_ID='$T' python -m benchmark.run_direct $T
```

### KB Generation (before benchmark)
Same docker run but use `python -m benchmark.run_kb $T` instead of `run_direct`.
KB gen explores the project and proposes entries via `propose_knowledge` MCP tool.
System prompt: `benchmark/prompts/kb_generation_system.md` (Steps 1-5 inlined from dbt-workflow).

### Clear KB entries
```bash
docker exec signalpilot-db-1 psql -U signalpilot -d signalpilot \
  -c "DELETE FROM gateway_knowledge_edits WHERE doc_id IN (SELECT id FROM gateway_knowledge_docs WHERE org_id='$T'); DELETE FROM gateway_knowledge_docs WHERE org_id='$T';"
```

### Parallel isolation
Each task uses `SP_ORG_ID=<task_name>` — KB entries scoped per org_id. Tested with reddit001 + shopify001 running simultaneously, zero cross-contamination.

### Monitor a running task
```bash
docker logs sp-spec-$T 2>&1 | grep "Turn " | tail -1
docker logs sp-spec-$T 2>&1 | grep -E "RESULT|PASS|FAIL" | tail -5
```

### Download results
```bash
mkdir -p "benchmark/results/dbt-run7/$T"
MSYS_NO_PATHCONV=1 docker run --rm \
  -v sp-benchmark-audit:/data:ro -v "$(pwd)/benchmark/results/dbt-run7:/out" \
  alpine sh -c "RUN=\$(ls -t /data/runs/ | grep $T | head -1); mkdir -p /out/$T; cp /data/runs/\$RUN/tasks/$T.json /out/$T/task_result.json 2>/dev/null; cp /data/runs/\$RUN/run_metadata.json /out/$T/ 2>/dev/null; cp /data/runs/\$RUN/traces/$T.json /out/$T/trace.json 2>/dev/null"
```

## Knowledge Base System

### Architecture
- MCP tools: `get_knowledge`, `search_knowledge`, `propose_knowledge` (knowledge.py)
- Storage: PostgreSQL via gateway store (knowledge.py)
- Isolation: `SP_ORG_ID` env var → `mcp_org_id_var` in server.py
- Categories: understanding, conventions, decisions, domain-rules, debugging, quirks
- Scopes: org, project, connection

### KB Generation Skill
File: `benchmark/signalpilot-plugin/skills/dbt-knowledgebase/SKILL.md`
- 8-category checklist (org:understanding, org:conventions, project:understanding, project:conventions, project:decisions, project:domain-rules, project:debugging, connection:quirks)
- Non-prescriptive: entries state facts, never instructions
- Body format: WHAT + EVIDENCE (no IMPACT — removed because it invited prescriptive statements)
- Rule: "NEVER write instructions in entries (Do not, Always, Use X) — state facts only"

### KB in Workflow
File: `benchmark/signalpilot-plugin/skills/dbt-workflow/SKILL.md` — "Knowledge Base Check" section
- KB INFORMS but does NOT skip steps. Always run full 8-step workflow.
- Agent loads KB at start for context, then verifies everything via blueprint/verifiers.
- Key lesson: KB saying "macros not used" caused agent to skip required columns. Fixed by making KB non-prescriptive and always running Step 4 (macros).

### Known KB Issues Fixed
1. **Prescriptive entries**: KB said "Do not add macro columns" → agent skipped them. Fixed: removed IMPACT field, added BAD/GOOD examples.
2. **Stale calendar**: Pre-existing shopify__calendar had 2083 rows (built with old current_date). Fixed: Step 3 MANDATORY rebuild of current_date hazard models.
3. **Calendar-spine COALESCE**: domain-ecommerce "entities with zero activity MUST NOT appear" conflicted with calendar spine needing all dates. Fixed: explicit exception in domain-ecommerce.
4. **Skip logic**: Original KB Check said "skip Step 5 if KB has decisions." This caused regressions. Fixed: KB never skips steps.

## The 8-Step Workflow (dbt-workflow/SKILL.md)
1. **Map** — scan_project.py
2. **Load skills** — dbt-write + SQL + domain skill
3. **Validate + rebuild stale** — validate_project.py + MANDATORY dbt run for current_date models
4. **Discover macros** — ALWAYS runs, produces ADDITIONAL columns beyond YML
5. **Research** — generate_model_blueprint per model
6. **Write technical spec** — knowledge-base skill writes technical_spec.md
7. **Write + build** — SQL from spec, dbt run --select (NO + prefix)
8. **Verify + fix** — dispatch structure verifier + value verifier subagents

## Prompt Rules (all verified by bm-prompting.md subagent)

### dbt-write (13 sections)
- §2: Sibling patterns + exceptions (Section 4 conditional agg + Section 6 grain override)
- §3: Lookup fan-out — query duplicates, preserve if different values, update spec row count
- §4: LEFT JOIN COALESCE + conditional aggregations (SUM CASE not COUNT_IF for NULL semantics)
- §5: No filters unless explicit
- §12: Percentage 0-100 scale
- §13: Boolean flag columns

### dbt-workflow
- not_null tests cannot override JOIN type or driving table
- Step 3: MANDATORY stale upstream rebuild (current_date/now() hazards)
- Step 4: macros ALWAYS run
- KB Check: inform don't skip

### Domain skills
- domain-ecommerce: return filtering decision tree, calendar-spine exception, driving table
- domain-marketing: report population exception, spend sign convention (single vs multi-source)
- domain-media: ALL ranking window functions need integer ID tiebreaker (not name)

### Verifier agents (recently optimized)
- Structure verifier: 4 checks (was 6 — merged 3+4+5 into single audit_model_sources call)
- Value verifier: 3 checks (CHECK 2 uses verify_model_values MCP tool)
- Both: parallel tool calls for multi-model, no TodoWrite overhead
- Enhanced audit_model_sources: now returns sample rows, low-cardinality values, grain detection

## Performance Analysis (shopify001)

### Turn counts
| Run | Turns | Time | Notes |
|-----|-------|------|-------|
| Run6 (no KB, old verifier) | 173 | 797s | Baseline |
| KB-Run (old 6-check verifier) | 165 | 772s | KB helped slightly |
| KB-Run (4-check streamlined) | 131 | ~530s est | Best measured |
| KB-Run (4-check + parallel) | 138 | 688s | Non-determinism |

### Tool call breakdown (138-turn run)
- query_database: 23 calls (22%) — mostly verifiers
- TodoWrite: 17 calls (17%) — task tracking
- Bash: 15 calls (15%) — scan, validate, dbt run
- Read: 12 calls (12%)
- ToolSearch: 7 calls (7%) — deferred tool fetching
- Skill: 6 calls (6%)
- Rest: MCP tools, Write, Glob, Agent

### Infrastructure overhead: 29% of calls are non-work (ToolSearch + TodoWrite + Skill)

### Enhanced audit_model_sources eliminates ~9-11 verifier queries
Covers: row count, source ratios, sample rows, per-column distinct+nulls, low-card values, grain key.
Does NOT cover: MIN/MAX, filtered samples, cross-table JOINs, source table column stats.
Net: 23 queries → ~12 queries (saves ~11 LLM thinking turns)

## Remaining Optimizations (not yet implemented)
1. Add MIN/MAX per column to audit_model_sources (closes partial gap)
2. Reduce ToolSearch calls (pre-fetch MCP tool schemas)
3. Reduce main agent TodoWrite frequency (update at step boundaries only)
4. Consider faster model (haiku) for verifier subagents

## Impossible Tasks (4)
- nba001: random seed lost
- quickbooks001: cross-platform MD5
- netflix001: VARCHAR formatting
- social_media001: gold duplicate columns

## Investigated Failures (not fixable with general prompting)
- f1001: gold internally inconsistent (COUNT_IF vs NULL for different columns)
- scd001: fct_jafflegaggle PASSES but rpt_corporate_accounts SCD merge wrong
- playbook002: agent's not_null semantic prior too strong (3 attempts)
- tickit002: gold uses INNER JOIN for orphan events
- flicks001/provider001: agent ignores domain driving table rules
- inzight001: 4x unit conversion (energy metering)
- recharge001: complex UNION ALL amount mapping
- twilio001: gold inconsistent signs (number_overview negative, account_overview positive) — FIXED with single/multi-source rule

## Git State
- RLM branch: autofyn/signalpilot-rlm-e691de at 134c91a
- Benchmarking branch: at 3ecf26b
- All changes committed, no push to GitHub

## Running Infrastructure
- benchmark/.env: CLAUDE_KEY_1 + KEY_4
- Spider2: C:/Users/kiwi0/Desktop/SPEcosystem/spider2-repo
- Docker compose: signalpilot stack (db, gateway, sandbox, web)
- Postgres encryption key: signalpilot_signalpilot-data volume
- KB data: signalpilot_signalpilot-pg-data volume
- Existing KB entries: reddit001 (8 entries), shopify001 (13 entries) — may need regeneration after code changes
