# Spider2-Lite Self-Improving Evaluation Loop — Autonomous Agent Brief

## 0. Mission

You are operating an autonomous self-improvement loop on the **Spider2-Lite SQL benchmark**. Goal: get the pass rate from current ~60% to **80%+** without overfitting to the eval, using a stratified MCMC-style sampling loop that proposes generalizable rules and skills based on observed failures, then validates them on a fresh held-out set.

Working directory: `/Users/tarik/codeAlpine/SignalPilot`. Branch: `chore/spider2-lite-setup` (or current). Activate venv: `source .venv/bin/activate`.

**You are NOT writing exam-cheat rules.** Every rule you propose must be derivable from the question text alone (no schema-specific names, no DB-specific traps, no instance IDs). The eval gold answers exist on disk for offline scoring but you must never train on them — only use the `evaluate_sql` function as a black-box oracle.

---

## 1. Codebase Map (read these first, in order)

| File | Purpose |
|---|---|
| [benchmark/loop/runner.py](benchmark/loop/runner.py) | Round driver: sample → run → evaluate → record |
| [benchmark/loop/sampler.py](benchmark/loop/sampler.py) | Stratified per-round sampler (fresh/targeted/regression) |
| [benchmark/loop/registry.py](benchmark/loop/registry.py) | Append-only JSONL of (round, task, status) — read for cooldown, regressions, pools |
| [benchmark/loop/seed_registry.py](benchmark/loop/seed_registry.py) | Backfills registry from existing workdirs |
| [benchmark/checks/__init__.py](benchmark/checks/__init__.py) | Layer-1 hardcoded structural checks (advisory, logged in `harness_checks.json`) |
| [benchmark/calibrate_checks.py](benchmark/calibrate_checks.py) | Computes per-check precision/recall against PASS/FAIL labels |
| [benchmark/skills/](benchmark/skills/) | Layer-3 skills (description-triggered SKILL.md files) |
| [benchmark/agent/sql_prompts.py](benchmark/agent/sql_prompts.py) | Main agent prompt + verifier subagent prompt |
| [benchmark/agent/sdk_runner.py](benchmark/agent/sdk_runner.py) | Claude Agent SDK wrapper (model, thinking budget, etc.) |
| [benchmark/runners/sql_runner.py](benchmark/runners/sql_runner.py) | One-task execution path |
| [benchmark/run_parallel.py](benchmark/run_parallel.py) | Concurrent task runner with `force=True` for fresh re-execution |
| [benchmark/evaluation/sql_comparator.py](benchmark/evaluation/sql_comparator.py) | Black-box evaluator (DO NOT modify) |
| [benchmark/evaluation/judge.py](benchmark/evaluation/judge.py) | LLM judge for fail-cause categorization |
| [benchmark/submission.py](benchmark/submission.py) | Builds Spider2 submission folder (sql/, csv/, reasoning_traces/) |
| [benchmark/results/registry.jsonl](benchmark/results/registry.jsonl) | Persistent task-status history |
| [CLAUDE.md](CLAUDE.md) | Standing project instructions |

Three layers of correctness enforcement:

- **Layer 1** — hardcoded Python checks (`benchmark/checks/`). Advisory-only. Logged to `harness_checks.json`. Toggle via `CHECK_REGISTRY[name] = (fn, enabled)`.
- **Layer 2** — `result_verifier` subagent built in `build_verifier_subagent()`. Returns OK or FIX before save. Has 13 numbered rules.
- **Layer 3** — pattern skills the main agent invokes when the question matches: `temporal-comparison`, `entity-with-metrics`, `ranking-with-position`, `classification-with-score`. Loaded from `benchmark/skills/<name>/SKILL.md`.

---

## 2. Hard Constraints (DO NOT VIOLATE)

1. **Model**: `claude-sonnet-4-6` for SDK runs. **Effort**: `medium`. **Thinking budget**: 32_000 tokens. These live in [benchmark/agent/sdk_runner.py](benchmark/agent/sdk_runner.py) — do not change unless the user explicitly says so.
2. **Concurrency**: 10 parallel tasks per round.
3. **Round size**: 25 tasks (default). Compose 60% fresh / 30% targeted / 10% regression.
4. **Per-DB cap**: 2 tasks per DB per round (avoids within-DB redundancy).
5. **Held-out set**: 20 tasks chosen deterministically by `held_out_set(seed=42)`. **NEVER include these in any round**. They are the final unbiased validation set.
6. **Regression anchors**: random sample from the passing pool each round (NOT a fixed list).
7. **Generalization rule for proposed changes**: Every new rule, skill, or check you write must pass these tests:
   - Mentions zero specific table names, column names, DB names, or instance IDs
   - Phrased as "if the question asks <pattern>, the SQL must <action>"
   - Would apply to similar questions on a different schema
8. **Don't touch**: `benchmark/evaluation/sql_comparator.py`, gold CSVs in `/Users/tarik/spider2-repo/...`, the eval JSONL.
9. **Token cost discipline**: a single round at 25 tasks costs ~$5–15. Do not run more than 2 rounds back-to-back without showing summary stats.
10. **All commits must be on a feature branch**, not `main`.

---

## 3. The Loop (one full iteration)

```
for round in 1..K:
    1. Compose sample          → benchmark.loop.sampler.sample_round(n=25)
    2. Run sample              → benchmark.loop.runner.run_round(...)
                                  - force=True so each task runs fresh
                                  - records status/checks per task in registry
                                  - prints regression alerts inline
    3. Calibrate Layer-1       → benchmark.calibrate_checks
    4. Judge failures          → benchmark.evaluation.judge --only-failed
    5. Propose ≤ 1 change      → analyze top fail category, draft ONE of:
                                   • a new skill SKILL.md
                                   • a new verifier rule (in sql_prompts.py)
                                   • a new Layer-1 check (in checks/__init__.py)
                                   • a refinement to an existing rule
    6. Generalization gate     → confirm proposal contains no schema-specific names
    7. Regression dry-run      → if change is a NEW Layer-1 check, run calibrate_checks
                                   on existing registry data to estimate precision
    8. Apply if safe           → commit on feature branch
    9. Validate next round     → next round will re-run targeted (failing pool)
                                   tasks AND draw fresh regression anchors. If
                                   regressions appear, ROLLBACK the change.
```

### Stop conditions

- Pass rate on **fresh-exploration** subset improves < 1% over 3 consecutive rounds → converged
- Total budget exceeded (set a $/round cap; default $20)
- Held-out validation pass rate ≥ 80% → ship it
- Held-out validation pass rate diverges from in-loop rate by > 5% → overfit signal, halt and reflect

---

## 4. Per-Round Procedure (concrete commands)

### 4.1 Pre-flight

```bash
# Sanity: gateway running, env loaded
docker ps | grep signalpilot-gateway || echo "WARN: gateway not running"
test -f .env && echo "env ok"

# Inspect last round's stats (if any)
.venv/bin/python -c "
from benchmark.loop import registry as r
records = r.load_all()
if records:
    print(f'Last round: {max(rec[\"round\"] for rec in records)}')
    print(f'Passing pool size: {len(r.passing_pool(records))}')
    print(f'Failing pool size: {len(r.failing_pool(records))}')
else:
    print('Empty registry — first run')
"
```

### 4.2 Compose & inspect sample

```bash
.venv/bin/python -c "
from benchmark.loop.sampler import sample_round
from benchmark.core.suite import BenchmarkSuite
comp = sample_round(suite=BenchmarkSuite('spider2-lite'), n_total=25)
print(comp.summary())
"
```

If composition looks degenerate (e.g., 25 fresh / 0 targeted), explain why in the round notes (probably early-round cooldown — natural).

### 4.3 Launch round

```bash
mkdir -p benchmark/results/round_N
nohup bash -c '.venv/bin/python -m benchmark.loop.runner \
  --suite spider2-lite \
  --n 25 \
  --concurrency 10 \
  --model claude-sonnet-4-6 \
  --note "round N: <what changed>"' \
  > benchmark/results/round_N/round.log 2>&1 &
echo $! > benchmark/results/round_N/round.pid
```

### 4.4 Monitor (every 3–5 minutes)

Use a non-blocking monitor pattern. Do NOT poll-sleep aggressively (that burns cache). Print these every check:

```bash
# Progress
grep -c "END local" benchmark/results/round_N/round.log
# Pass/fail tally
grep -E "status=(PASS|FAIL|ERROR)" benchmark/results/round_N/round.log | sort | uniq -c
# Most recent activity
tail -3 benchmark/results/round_N/round.log
# Process alive?
kill -0 $(cat benchmark/results/round_N/round.pid) 2>/dev/null && echo running || echo done
```

When done, print a one-paragraph summary: pass rate, regressions, top failure categories.

### 4.5 Calibrate Layer-1 checks

```bash
.venv/bin/python -m benchmark.calibrate_checks --suite spider2-lite
```

Look for: any check with **precision < 50%** is a false-positive generator; flag it for refinement or disable. Any check with **0 fires** over multiple rounds is dead weight; remove it.

### 4.6 Judge failures

```bash
.venv/bin/python -m benchmark.evaluation.judge \
  benchmark/results/round_N \
  --only-failed
```

Parse the resulting `judge.jsonl`. Group by `category`. Identify the top-1 category by count.

### 4.7 Draft ≤ 1 proposal

You must propose **exactly one** change per round (never two — keeps attribution clean). Choose the format that best fits the failure pattern:

- **New skill** — when the failure category corresponds to a recognizable solution pattern not yet covered. SKILL.md must follow the existing structure (frontmatter → when this applies → required output → anti-patterns → SQL pattern → verification checklist).
- **New verifier rule** — when the failure is a structural shape that an LLM can detect from question + SQL + result preview. Add as a numbered rule to `VERIFIER_SUBAGENT_PROMPT` in [benchmark/agent/sql_prompts.py](benchmark/agent/sql_prompts.py).
- **New Layer-1 check** — only when the failure is detectable from the result_df alone via deterministic regex/pandas — and only if you can predict precision > 70%. Add to `CHECK_REGISTRY`.
- **Refinement of existing rule** — when calibration shows an existing check has high false-positive rate.

Print the proposal to the user (or commit message body if running fully autonomous), with this format:

```
PROPOSAL ROUND N
- Type: skill | verifier_rule | layer1_check | refinement
- Targets failure category: <category from judge>
- Observed in N tasks this round (e.g., local263, local355)
- Generalization check: <enumerate why it doesn't depend on specific schemas>
- Expected lift: rough estimate (low/med/high)
- Regression risk: low/med/high + reasoning
- Diff: <code>
```

### 4.8 Generalization gate (auto-check)

Before committing, run grep on the proposal text:

```bash
# Should return zero hits for any of these
grep -E "(local[0-9]+|bq[0-9]+|sf_bq[0-9]+|sf[0-9]+)" <proposal>
grep -iE "(batsman|director|olist|pizza|payment|customer_id|product_id)" <proposal>
```

If a specific schema term shows up, rephrase to the generic pattern.

### 4.9 Apply, commit, run next round

```bash
git checkout -b loop/round-N-<short-name>
git add <files>
git commit -m "round N: <category> — <one-line change>"
# Next round picks up the change automatically
```

If round N+1 shows regressions in the regression-anchor sample → revert with `git revert HEAD` and document why.

---

## 5. Anti-Overfitting Discipline

**Never optimize on the held-out set.** Confirm before any final claim:

```python
.venv/bin/python -c "
from benchmark.loop.sampler import held_out_set
from benchmark.core.suite import BenchmarkSuite
print(sorted(held_out_set(BenchmarkSuite('spider2-lite'), n=20)))
"
```

If any of those task IDs appear in your registry with `round > 0`, you have leaked. Stop, investigate.

**Track regressions formally.** Every round, run:

```python
from benchmark.loop import registry as r
for task, was_pass, now_fail in r.regressions(r.load_all()):
    print(f"REGRESSION: {task}  passed in {was_pass}, failed in {now_fail}")
```

If the latest round introduced ≥ 2 new regressions, the latest change is suspect → revert.

**Per-rule attribution.** When you commit a rule, record it with the round number in commit message. After 2 rounds, query: "tasks that transitioned PASS→FAIL after this rule was added vs FAIL→PASS." Net negative → flag for removal.

**Re-run the held-out only at the end.** Use this one-liner once you believe you're converged:

```bash
.venv/bin/python -m benchmark.run_parallel --concurrency 10 --model claude-sonnet-4-6 \
  --summary-out benchmark/results/holdout/summary.jsonl \
  $(.venv/bin/python -c "from benchmark.loop.sampler import held_out_set; from benchmark.core.suite import BenchmarkSuite; print(' '.join(sorted(held_out_set(BenchmarkSuite('spider2-lite'), n=20))))")
```

Compare in-loop pass rate to held-out pass rate. Divergence > 5 percentage points = overfit.

---

## 6. Reporting Format (after every round)

Print this block at the end of each round so the user gets a consistent feed:

```
════════════════════════════════════════════════════════════
ROUND N COMPLETE  (elapsed: Xm Ys, cost: $Z)
════════════════════════════════════════════════════════════
Sample: 25 tasks (15 fresh / 8 targeted / 2 regression)
Result: P PASS / F FAIL / E ERROR / S SKIP   (P/(P+F+E) = X%)

Pass rate trend (round → rate):
  0 → 59.6%
  1 → 64.0%
  2 → ...
  N → X%

Regressions this round: <list, or "none">
Top failure category:   <category>  (count: N)

Layer-1 calibration (this round only):
  check_name        fired  on_fail  on_pass  precision  recall
  ...

Proposal:
  <type>: <one-line>
  Generalization gate: PASSED / FAILED — <if failed, why>
  Regression risk: low/med/high
  Applied: yes/no

Next round will draw 25 from the unseen pool (≈ K remaining).
════════════════════════════════════════════════════════════
```

---

## 7. Submission Packaging (when ready to ship)

```bash
# Build folder structure required by Spider2 maintainers
.venv/bin/python -m benchmark.submission build \
  --suite spider2-lite \
  --out submission_$(date +%Y%m%d) \
  --tar \
  --method-name "SignalPilot-MCMC-Loop"
```

Produces `submission_DATE.tar.gz` containing `sql/`, `csv/`, `reasoning_traces/`. Submission email: `lfy79001@gmail.com` (per Spider2 README). Include in the email body: method description, model used, total cost, link to repo branch.

---

## 8. Failure Modes & Recoveries

| Symptom | Likely cause | Recovery |
|---|---|---|
| All tasks fail with 401 errors | OAuth token expired or rate-limit rejection | Check `.env` `CLAUDE_CODE_OAUTH_TOKEN`; wait for `resets_at` if rate-limited |
| Tasks hang on "no result.csv" | Agent ran out of turns or MCP gateway crashed | Restart `signalpilot-gateway-1` Docker container; bump `_DEFAULT_MAX_TURNS` if consistent |
| `evaluate_sql` raises `out-of-bounds` | `condition_cols` index larger than result columns | Pred is missing required columns — agent didn't include them, that's a real FAIL |
| Sampler returns empty | Held-out + cooldown excluded everything | Check `cooldown_rounds=2` is right; reset registry if testing |
| Regression count exploded after a rule change | Rule too aggressive | `git revert HEAD`, propose narrower version, re-run round |
| Pass rate plateaus at X% | Approaching capability limit of the agent + skills | Try Layer-3 skill for the most stuck failure category, or escalate to opus on a sample |

---

## 9. Sanity Tests Before Launching

Run these before round 1 to make sure plumbing works:

```bash
# 1. Sampler returns non-empty
.venv/bin/python -c "from benchmark.loop.sampler import sample_round; from benchmark.core.suite import BenchmarkSuite; c=sample_round(BenchmarkSuite('spider2-lite'),n_total=5); assert c.all_tasks; print('sampler OK')"

# 2. Registry append-load roundtrip
.venv/bin/python -c "from benchmark.loop import registry as r; rs=r.load_all(); print(f'registry has {len(rs)} records')"

# 3. Layer-1 checks compile and run on a known-good task
.venv/bin/python -m benchmark.calibrate_checks --suite spider2-lite --tasks-file benchmark/results/lite-strat50/tasks.txt 2>&1 | tail -10

# 4. Agent SDK auth (one-shot, no MCP)
.venv/bin/python -c "
import asyncio
from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, TextBlock
async def main():
    async for msg in query(prompt='reply only OK', options=ClaudeAgentOptions(model='claude-sonnet-4-6', max_turns=1, permission_mode='bypassPermissions')):
        if isinstance(msg, AssistantMessage):
            for b in msg.content:
                if isinstance(b, TextBlock): print('SDK reply:', b.text[:50])
asyncio.run(main())
"
```

If any of these fail, fix before launching a real round.

---

## 10. Final Notes

- This is **MCMC over prompt/skill space** with regression anchors as the rejection criterion. Each round mutates the system; bad mutations are rolled back via the regression check.
- The **judge** is your fail-mode classifier. Trust its categories but verify with a 2-task spot-check before drafting a rule.
- The **registry** is sacred — it's the only ground-truth record of what the system has done. Append, never edit retroactively. If you need to delete a bad round's entries, do it explicitly with a comment in `round_notes.jsonl`.
- The **held-out set** is your only honest evaluator. Touch it once, at the end.
- Default to **smaller, more conservative changes**. One rule per round. The user prefers slow + correct over fast + flaky.

When in doubt, print state and ask. The user is reachable; auto-mode does not mean silent.
