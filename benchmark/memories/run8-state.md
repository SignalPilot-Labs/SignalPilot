# Run 8 State

## Score: 38/42 passed (90.5%) — 4 retrying/investigating

## Results Location
`benchmark/results/dbt-run8/` — full traces, KB entries, project files per task

## Failures (systematic, not non-det)
- **apple_store001**: grain issue — UNION ALL vs JOIN pattern, agent gets 29 rows vs gold 9
- **hive001**: fan-out regression — was our flip, now failing consistently
- **salesforce001**: date spine boundary — agent gets 96 rows vs gold 91 (NOT the CRLF bug)
- **zuora001**: complexity — runs past 200 turns, stuck in fix loops

## Key Findings

### KB Architecture Decision
- Separate KB gen agent → POISONED results (grain assertions from unverified builds)
- Inline KB gen (Step 9 after verification) → SAFE (entries from verified builds)
- BUT: agent verifiers say PASS when gold says FAIL → KB entries still wrong for failed tasks
- Fix: clear KB after gold comparison fails (implemented in run8_full.sh)

### Double Verification Waste
- Agent ALWAYS runs 2 verification rounds even when first round is all PASS
- dbt-workflow says "re-verify only if you made fixes" but agent ignores conditional
- Cost: ~2 min per task × 42 tasks = ~84 min wasted
- Fix needed: strengthen prompt to make conditional explicit

### CRLF Bug (Fixed)
- `benchmark/signalpilot-plugin/bin/map-columns` and `verify-values` had Windows line endings
- Fixed with `sed -i 's/\r$//'` — image rebuilt
- Was NOT the cause of salesforce001 failure (agent worked around it)

### Step 9 Overhead
- KB generation (Step 9) adds ~26 turns and ~94s per task
- 13 propose_knowledge calls per task
- For 42 tasks: ~1100 turns, ~66 min overhead
- Consider making Step 9 optional or limiting to 5 entries max

## Script: benchmark/run8_full.sh
- Single-phase: benchmark + inline KB gen (no separate KB gen)
- 3 retries with KB clearing between retries
- Concurrency: 4 tasks, rotating CLAUDE_KEY_1 and CLAUDE_KEY_4
- Downloads: task_result.json, trace.json, project/, sp-kb/*.md

## Image
- Rebuilt with CRLF fix at end of session
- Step 9 in dbt-workflow SKILL.md
- decisions category removed from KB gen
- grain ban in prompts (partially effective)
