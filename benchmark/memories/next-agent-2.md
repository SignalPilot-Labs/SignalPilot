# Benchmark Session State — Active Work

## Current Score
- **Benchmarking branch**: 43/64 (67.2%) — tpch001, hive001, twilio001 flipped
- **RLM branch** (autofyn/signalpilot-rlm-e691de): KB system proven working
- HEAD: d01424f

## KB System — Proven Working
- **reddit001**: PASS with KB (macros discovered, no regressions)
- **shopify001**: PASS with KB (stale calendar rebuilt, COALESCE applied)
- Parallel isolation via SP_ORG_ID — tested, no cross-contamination
- KB entries are non-prescriptive (facts only, no instructions)

### How to run KB generation + benchmark:
```bash
# 1. Clear old entries (optional)
docker exec signalpilot-db-1 psql -U signalpilot -d signalpilot \
  -c "DELETE FROM gateway_knowledge_edits; DELETE FROM gateway_knowledge_docs WHERE org_id='<task>';"

# 2. KB generation
SP_ORG_ID=<task> python -m benchmark.run_kb <task> --model claude-sonnet-4-6

# 3. Benchmark run (reads KB, skips blueprint if KB covers all models)
SP_ORG_ID=<task> python -m benchmark.run_direct <task> --model claude-sonnet-4-6

# Docker needs these env vars:
# SP_DISABLE_SANDBOX=1, DATABASE_URL, SP_DATA_DIR=/sp-data, SP_ORG_ID=<task>
# Mount: signalpilot_signalpilot-data:/sp-data:ro
```

### Key fixes this session:
1. **Non-prescriptive KB**: entries state facts, never instructions. "NEVER write instructions in entries"
2. **Step 3 MANDATORY stale rebuild**: current_date models rebuilt before use. "Do NOT skip even if KB has entries"
3. **Calendar-spine exception**: domain-ecommerce driving table rule doesn't apply to date spine models. COALESCE metrics to 0.
4. **Step 4 always runs**: macros produce required columns regardless of KB

### Known remaining issue:
- Agent sometimes still dismisses macro columns despite Step 4 finding them — needs stronger "ADDITIONAL columns beyond YML" enforcement

## Files (RLM branch):
- `benchmark/runners/kb_generator.py` — KB gen runner
- `benchmark/run_kb.py` — entry point
- `benchmark/prompts/kb_generation_system.md` — system prompt (Steps 1-5 inlined)
- `benchmark/signalpilot-plugin/skills/dbt-knowledgebase/SKILL.md` — 8-category taxonomy
- `signalpilot/gateway/gateway/mcp/tools/knowledge.py` — 3 MCP tools
- `signalpilot/gateway/gateway/mcp/server.py` — SP_ORG_ID for isolation
- `benchmark/core/mcp.py` — SP_ORG_ID for connection registration

## Benchmarking branch flips (from run6→run7):
- **tpch001**: knowledge-base skill forced spec with ref decisions
- **hive001**: fan-out rule preserved lookup duplicates
- **twilio001**: single vs multi-source spend sign convention

## Running
- benchmark/.env has CLAUDE_KEY_1 and KEY_4
- Spider2 path: C:/Users/kiwi0/Desktop/SPEcosystem/spider2-repo
- Docker compose: signalpilot stack running (db, gateway, sandbox, web)
- Postgres encryption key at signalpilot_signalpilot-data:/sp-data/.encryption_key
