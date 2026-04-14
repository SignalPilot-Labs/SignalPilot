# SignalPilot Benchmark Agent — Continuation Prompt (Slim)

Goal: improve dbt agent pass rate on Spider2-DBT (29/65 = 44.6%). The real product is the best general-purpose dbt agent — the benchmark is a proxy.

---

## Principles (non-negotiable)

1. **Product over benchmark** — every change must improve a real dbt agent, not just Spider2 scores
2. **Never leak gold data** — gold DBs at `spider2-repo/.../gold/` are eval-only, never visible to the agent
3. **No overfitting** — no task names, gold column names, or task-specific branches in prompts/skills/tools
4. **Keep main prompt slim** — SQL patterns go in skills (`benchmark/skills/`), not the system prompt
5. **Skills for domain knowledge** — skills at `benchmark/skills/<name>/SKILL.md`, loaded on-demand via Skill tool
6. **Research before building** — use WebSearch/WebFetch to check dbt docs, agent papers, MCP servers first
7. **Run 1-3 tasks when iterating** — full 65-task sweeps only for milestones/regression checks
8. **Verify mechanism, not just score** — read turn traces, confirm the intended fix actually activated
9. **Never modify gold, eval config, or task jsonl** (one documented exception: chinook001 typo fix)
10. **Document discoveries** — update `docs/progress.md` and `docs/runs.md`

---

## Pre-flight checklist (every session)

Run ALL before any real work. Half the debugging time came from silent infra failures.

| # | Check | Command | Pass signal |
|---|-------|---------|-------------|
| 1 | Gateway alive | `curl -s http://localhost:3300/api/connections` | Returns JSON |
| 2 | dbt on PATH | `which dbt && dbt --version` | dbt-core 1.x + dbt-duckdb |
| 3 | Unit tests | `python -m pytest tests/test_dbt_project_map.py --tb=short` | 43 passed |
| 4 | **MCP handshake** | `python benchmark/_verify_mcp_sdk.py 2>&1 \| head -50` | `signalpilot: connected` + `mcp__signalpilot__*` tools in toolset |
| 5 | CLI spawns | Same as #4 — gets past SystemMessage init | AssistantMessage emitted |
| 6 | Skills on disk | `ls benchmark/test-env/<task>/.claude/skills/` | 4 dirs with SKILL.md |
| 7 | Prompt has MCP refs | `grep -c "mcp__signalpilot__dbt_project_map" benchmark/test-env/<task>/_system_prompt.md` | >= 1 |
| 8 | Agent uses Skill tool | Run chinook001, check log for `TOOL: Skill ->` | Skill calls appear |
| 9 | Agent calls dbt_project_map early | Same log — `mcp__signalpilot__dbt_project_map` in first ~6 turns | Tool invoked |
| 10 | dbt_project_map returns content | Next turn acts on project data (model names, etc.) | Agent proceeds meaningfully |
| 11 | No regressed config | `grep -n "max_turns=\|allowed_tools" benchmark/run_dbt_local.py` | Only comments/defaults |
| 12 | Docs in sync | `ls benchmark/docs/` + `grep "^## Score" benchmark/docs/runs.md` | Files present, score line exists |

**If #4 fails** (most common): check PYTHONPATH injection in `run_dbt_local.py` ~line 237, Windows fcntl shim in `store.py`, and gateway is running.

---

## Current status

- **29/65 = 44.6%** (Databao #1: 44.11%)
- Failure categories: A=Date spine(7), B=Wrong JOIN(4), C=Row count(7), D=Value errors(9), E=Broken build(3), F=Schema mismatch(3), G=Non-deterministic(2)

### Recent wins (don't redo)
- MCP tools: `dbt_project_map` + `dbt_project_validate` (43 tests passing)
- Prompt externalized to `benchmark/prompts/dbt_local_system.md` (~9k chars, down from 32k)
- Turn/budget caps lifted (max_turns=200, no budget cap)
- `allowed_tools` whitelist removed — never add back
- MCP PYTHONPATH fix + Windows fcntl shim
- Non-determinism investigation complete (see `docs/non-determinism-investigation.md`)

---

## Priority order

### P0: Category A — Date spine / CURRENT_DATE (7 tasks, highest ROI)
Tasks: salesforce001, shopify001, xero001, xero_new001, xero_new002, quickbooks003, pendo001.
**Root cause**: package models use `current_date` for spine endpoints; agent treats `dbt_packages/` as read-only.
**Fix**: teach the agent the local-override pattern (filename-shadowing). Build a `dbt-date-spines` skill + `dbt_project_map` warning for `current_date` in packages.
**Test on**: shopify001, xero001, pendo001.

### P1: Category B — Wrong JOIN type (4 tasks)
Agent has the knowledge (in dbt-workflow skill) but doesn't consistently apply it. Make `compare_join_types` part of Step 4.

### P2: Non-determinism empowerment (7 tasks)
Add ND scanner to `dbt_project_map` + `dbt-determinism` skill. Agent should proactively add tiebreakers.

### P3: Category D — Value/computation errors (9 tasks)
Hard, task-specific. Low priority until A+B done.

---

## How to run

```bash
# Single task
python -m benchmark.run_dbt_local <task_id> --model claude-sonnet-4-6

# Verify MCP after gateway changes
python benchmark/_verify_mcp_sdk.py

# Unit tests after dbt/ changes
python -m pytest tests/test_dbt_project_map.py
```

---

## Iteration loop (every change)

1. **Orient** — re-read `progress.md` + `runs.md`
2. **Pick** 1-3 tasks (1 target failure, 1 passing regression check, 1 optional generalization)
3. **Deep-read** the failing task (instruction, scaffold SQL, eval config, gold DB read-only, prior trace)
4. **Hypothesize** specifically — "agent doesn't X" not "make it try harder"
5. **Implement minimally** — prefer skill > MCP tool > prompt > infra
6. **Run** the 1-3 tasks
7. **Verify mechanism** — read trace, confirm intended fix activated; rollback if regression
8. **Update docs**

---

## Key files

| Category | Files |
|----------|-------|
| Runner | `benchmark/run_dbt_local.py`, `benchmark/run_batch.py` |
| MCP | `signalpilot/gateway/gateway/dbt/`, `signalpilot/gateway/gateway/mcp_server.py` |
| Prompts | `benchmark/prompts/dbt_local_system.md`, `benchmark/prompts/dbt_local_user.md` |
| Skills | `benchmark/skills/{dbt-workflow,dbt-verification,dbt-debugging,duckdb-sql}/SKILL.md` |
| Docs | `benchmark/docs/{progress,runs,non-determinism-investigation,continuation-prompt}.md` |
| Tests | `tests/test_dbt_project_map.py` (43 tests) |
| Scratch | `benchmark/scratch/`, `benchmark/test-env/` |

---

## Anti-patterns

Don't: modify gold, hardcode task names, add `allowed_tools` whitelist, inline examples in prompt (keep <8k), dump project context in prompt, run 65-task sweeps during iteration, call fix "done" without reading trace, lower `max_turns`, chase DuckDB versions for ND, duplicate existing MCP tools, leak benchmark awareness to agent.
