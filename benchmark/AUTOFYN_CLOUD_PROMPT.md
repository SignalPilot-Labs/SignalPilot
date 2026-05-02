# Spider2-Lite **Cloud** Self-Improving Evaluation Loop — Autonomous Agent Brief

## 0. Mission

You are operating an autonomous self-improvement loop on the **Spider2-Lite cloud subset**: 412 tasks across BigQuery (`bq*` 180 + `ga*` 25) and Snowflake (`sf*` 207). Goal: lift the cloud pass rate from cold-start (currently undetermined) to **75%+** without overfitting, using the same **stratified MCMC sampling + ≤1 generalizable change per round** protocol that took the 135-task SQLite subset to 80% held-out (rounds 1–7, see `local-optimization-learnings.md`).

Working directory: `/Users/tarik/codeAlpine/SignalPilot`. Branch: a fresh `loop/cloud-round-N-...` per round. Activate venv: `source .venv/bin/activate`.

**You are NOT writing exam-cheat rules.** Every rule must be derivable from question text alone — no schema names, no table names, no DB ids, no instance ids, no dialect-specific values that don't generalize. The eval gold answers exist on disk for offline scoring but you must never train on them — only use the `evaluate_sql` function as a black-box oracle.

**Read these first**:
- [cloud-connection-setup.md](../cloud-connection-setup.md) — every credential / billing / schema gotcha discovered during cloud wiring. Don't skip.
- [local-optimization-learnings.md](../local-optimization-learnings.md) — what worked / didn't on the SQLite subset; reuse the discipline.

---

## 1. Codebase map (read in order)

| File | Purpose |
|---|---|
| [benchmark/loop/runner.py](loop/runner.py) | Round driver: sample → run → evaluate → record |
| [benchmark/loop/sampler.py](loop/sampler.py) | Stratified per-round sampler (currently filters by single prefix; see §3.1 — needs cloud extension) |
| [benchmark/loop/registry.py](loop/registry.py) | Append-only JSONL of (round, task, status) — read for cooldown, regressions, pools |
| [benchmark/loop/seed_registry.py](loop/seed_registry.py) | Backfills registry from existing workdirs |
| [benchmark/checks/__init__.py](checks/__init__.py) | Layer-1 hardcoded structural checks (advisory) |
| [benchmark/calibrate_checks.py](calibrate_checks.py) | Per-check precision/recall against PASS/FAIL labels |
| [benchmark/skills/](skills/) | Layer-3 skills (description-triggered SKILL.md). Cloud-relevant: `bigquery-sql`, `snowflake-sql`, plus all five pattern skills auto-loaded. |
| [benchmark/agent/sql_prompts.py](agent/sql_prompts.py) | Main agent prompt + verifier subagent (15 numbered rules from local rounds) |
| [benchmark/agent/sdk_runner.py](agent/sdk_runner.py) | Claude Agent SDK wrapper |
| [benchmark/runners/sql_runner.py](runners/sql_runner.py) | One-task execution path (already routes BQ/SF/SQLite by `_determine_backend`) |
| [benchmark/run_parallel.py](run_parallel.py) | Concurrent task runner with `force=True` |
| [benchmark/evaluation/sql_comparator.py](evaluation/sql_comparator.py) | Black-box evaluator (DO NOT modify) |
| [benchmark/evaluation/judge.py](evaluation/judge.py) | LLM judge for fail-cause categorization |
| [benchmark/results/registry.jsonl](results/registry.jsonl) | Persistent task-status history (currently has 7 rounds of *local* data — the cloud rounds will append) |
| [CLAUDE.md](../CLAUDE.md) | Standing project instructions |

Three-layer architecture is unchanged from the local run:
- **Layer 1** — Python checks (`benchmark/checks/`). Advisory.
- **Layer 2** — `result_verifier` subagent in `build_verifier_subagent()`.
- **Layer 3** — pattern skills + dialect skills.

The 15 verifier rules already in place generalize across dialects; treat them as the starting point. Adding dialect-specific rules is allowed only if the rule is **phrased generically and applies symmetrically across BQ + SF + SQLite**.

---

## 2. Hard constraints (DO NOT VIOLATE)

1. **Model**: `claude-sonnet-4-6`, **medium** effort, **64_000** thinking budget. Same as local.
2. **Concurrency**: 10 parallel tasks per round (BQ has rate limits but stays under them at 10).
3. **Round size**: **20 tasks** for cloud (smaller than local's 25 because per-task SF/BQ wall time + spend is higher). Composition: 60% fresh / 30% targeted / 10% regression.
4. **Per-DB cap**: 2 tasks per DB per round.
5. **Held-out set**: **30 tasks**, stratified by backend (≈14 sf + 13 bq + 3 ga, see §3.2). Deterministic from `seed=42`. **NEVER include these in any round.**
6. **Regression anchors**: random sample from passing pool each round (NOT fixed list).
7. **Generalization rule** for proposed changes — same as local:
   - Mentions zero specific table/column/DB/instance names
   - Phrased as "if the question asks <pattern>, the SQL must <action>"
   - Applies across at least two of {BQ, SF, SQLite} on similar question shapes
8. **Don't touch**: `benchmark/evaluation/sql_comparator.py`, gold CSVs, the eval JSONL, `benchmark/results/round_1..7/` (those are local artifacts — preserve them).
9. **Token + DB cost discipline**: a cloud round at 20 tasks is ~$8–20 (Claude API) **plus** small BQ scanning costs (~$0.05–0.50 per round if queries stay tight) **plus** Snowflake compute on the shared participant warehouse. Do not run more than 2 rounds back-to-back without a budget summary.
10. **All commits on a feature branch**: `loop/cloud-round-N-<short>`. Never on main.
11. **Don't commit secrets**: `.env` and `gcp-service-account.json` are gitignored — verify with `git status` before every commit.

---

## 3. Cloud-specific scoping

### 3.1 Sampler must be extended for cloud

`benchmark/loop/sampler.py` currently accepts a single `task_filter` prefix. For cloud you need to draw across `sf|bq|ga` simultaneously. Two options:

**(A) Extend the sampler** (preferred, minimal change):
- Add `task_filters: list[str] | None = None` parameter to `sample_round()` and `held_out_set()`.
- If both `task_filters` and `task_filter` are provided, `task_filters` wins.
- A task matches if **any** prefix in `task_filters` matches.

**(B) Wrap with a CLI flag** in `benchmark/loop/runner.py` that accepts `--cloud` and passes `task_filters=["sf","bq","ga"]` through.

Either path is < 30 LOC. Do this **before round 1**.

### 3.2 Holdout split (deterministic, n=30, seed=42, stratified)

Recommended composition:
- 14 from `sf*` (≈7% of 207)
- 13 from `bq*` (≈7% of 180)
- 3 from `ga*` (≈12% of 25 — slightly oversampled to ensure GA4 representation)

Reference implementation (drop into `sampler.py` or write inline):

```python
def cloud_held_out_set(suite, seed=42) -> set[str]:
    import random
    rng = random.Random(seed)
    pool = list_all_tasks(suite)
    sf  = sorted(t for t in pool if t.startswith("sf"))
    bq  = sorted(t for t in pool if t.startswith("bq"))
    ga  = sorted(t for t in pool if t.startswith("ga"))
    return set(rng.sample(sf, 14) + rng.sample(bq, 13) + rng.sample(ga, 3))
```

Once chosen, **never re-roll**. The set is sacred.

### 3.3 Backend-aware regression anchors

When picking regression anchors, prefer to pick at least one from each backend that has any passing tasks in the pool (so a SF-specific rule change is regression-checked against a BQ task too, and vice versa).

### 3.4 Environment-failure exclusion (Snowflake-specific)

Some SF tasks fail with `Schema 'X' does not exist or not authorized` because the participant role's schema mapping doesn't match the local `resource/databases/snowflake/...` folders (concrete case: `GLOBAL_WEATHER__CLIMATE_DATA_FOR_BI` has local `STANDARD_TILE/` but participant only sees `PWS_BI_SAMPLE/`). Add a Layer-1 check that classifies these as `ENV_FAIL` and excludes them from PASS/FAIL pass-rate denominators, while still recording them so the regression check can detect a *new* environment failure introduced by a rule change.

```python
# pseudo
def env_fail_check(question, sql, df, error_text=None):
    if error_text and any(s in error_text for s in (
        "does not exist or not authorized",
        "Object does not exist",
        "User does not have bigquery.jobs.create",
    )):
        return "ENV_FAIL"
```

---

## 4. The loop (one full iteration)

```
for round in 1..K:
    1. Pre-flight              → verify gateway up, env loaded, smoke bq + sf
    2. Compose sample          → sample_round(task_filters=["sf","bq","ga"], n_total=20)
    3. Run sample              → benchmark.loop.runner --suite spider2-lite --cloud
    4. Calibrate Layer-1       → benchmark.calibrate_checks
    5. Judge failures          → benchmark.evaluation.judge --only-failed
                                  (skip ENV_FAIL category)
    6. Propose ≤ 1 change      → top fail category → ONE of:
                                   • new skill
                                   • new verifier rule
                                   • new Layer-1 check
                                   • refinement of existing rule
                                   • dialect-specific knowledge added to bigquery-sql
                                     or snowflake-sql skill (still must be generic)
    7. Generalization gate     → no schema/instance/dialect-specific value names
    8. Regression dry-run      → calibrate_checks for any new Layer-1 check
    9. Apply if safe           → commit on loop/cloud-round-N branch
    10. Validate next round    → if regressions ≥ 2 in regression-anchor sample, REVERT
```

### Stop conditions

- Pass rate on **fresh-exploration** subset improves < 1% over 3 consecutive rounds → converged
- Total cumulative cost > $150 → halt and review
- Held-out validation pass rate ≥ 75% → ship it
- Held-out vs in-loop divergence > 5pp → overfit, halt and reflect
- Two consecutive rounds with ≥ 2 regressions each → discipline failure, halt, audit rules

---

## 5. Per-round procedure (concrete commands)

### 5.1 Pre-flight (every round)

```bash
# Gateway up?
docker ps | grep signalpilot-gateway || (docker compose up -d gateway && sleep 5)

# Env loaded?
test -f .env && grep -q "SNOWFLAKE_TOKEN" .env && echo "snowflake env ok"
test -f gcp-service-account.json && echo "bq sa ok"

# Snowflake PAT not expired?
.venv/bin/python -c "
import json,base64,datetime,os
tok=next(l.split('=',1)[1].strip().strip('\"') for l in open('.env') if l.startswith('SNOWFLAKE_TOKEN'))
exp=json.loads(base64.urlsafe_b64decode(tok.split('.')[1]+'==').decode())['exp']
days=(datetime.datetime.fromtimestamp(exp,tz=datetime.UTC)-datetime.datetime.now(tz=datetime.UTC)).days
print(f'PAT expires in {days} days')
assert days > 0, 'PAT EXPIRED — refresh from Spider2 organizers'
"

# Last round stats?
.venv/bin/python -c "
from benchmark.loop import registry as r
records = [rec for rec in r.load_all() if any(rec['task_id'].startswith(p) for p in ('sf','bq','ga'))]
if records:
    print(f'cloud rounds so far, last: {max(rec[\"round\"] for rec in records)}')
    print(f'cloud passing pool: {len(set(rec[\"task_id\"] for rec in records if rec[\"status\"]==\"PASS\"))}')
    print(f'cloud failing pool: {len(set(rec[\"task_id\"] for rec in records if rec[\"status\"]==\"FAIL\"))}')
else:
    print('cold start — no cloud records in registry')
"
```

### 5.2 Compose & inspect sample

After the sampler is extended (§3.1):

```bash
.venv/bin/python -c "
from benchmark.loop.sampler import sample_round
from benchmark.core.suite import BenchmarkSuite
comp = sample_round(suite=BenchmarkSuite('spider2-lite'),
                    n_total=20, task_filters=['sf','bq','ga'])
print(comp.summary())
"
```

If composition is degenerate at round 1 (all fresh, no targeted/regression), that's expected — the registry has no cloud records yet.

### 5.3 Launch round

```bash
mkdir -p benchmark/results/cloud_round_N
nohup bash -c '.venv/bin/python -m benchmark.loop.runner \
  --suite spider2-lite \
  --cloud \
  --n 20 \
  --concurrency 10 \
  --model claude-sonnet-4-6 \
  --note "cloud round N: <what changed>"' \
  > benchmark/results/cloud_round_N/round.log 2>&1 &
echo $! > benchmark/results/cloud_round_N/round.pid
```

### 5.4 Monitor (poll lightly, every 3–5 min)

```bash
N=1
echo "progress:    $(grep -c 'END' benchmark/results/cloud_round_$N/round.log) tasks completed"
echo "tally:       $(grep -E 'status=(PASS|FAIL|ERROR|ENV_FAIL)' benchmark/results/cloud_round_$N/round.log | sort | uniq -c)"
echo "tail:        $(tail -3 benchmark/results/cloud_round_$N/round.log)"
echo "alive?       $(kill -0 $(cat benchmark/results/cloud_round_$N/round.pid) 2>/dev/null && echo running || echo done)"
```

### 5.5 Calibrate & judge

```bash
.venv/bin/python -m benchmark.calibrate_checks --suite spider2-lite --cloud
.venv/bin/python -m benchmark.evaluation.judge benchmark/results/cloud_round_$N --only-failed
```

Group judge categories by count, separately for sf vs bq vs ga. Top-1 across **all backends** drives the round's proposal — but if the top-1 is dialect-specific (e.g., affecting only SF), confirm it has a parallel mode in BQ before generalizing.

### 5.6 Draft the proposal

Same template as local AUTOFYN_PROMPT §4.7:

```
PROPOSAL CLOUD ROUND N
- Type:                 skill | verifier_rule | layer1_check | refinement
- Target fail category: <category from judge>
- Backends affected:    sf | bq | ga | all
- Observed in N tasks:  e.g., sf044, sf123, bq287
- Generalization check:
    - Mentions zero schema-specific names? <yes|no — list violations>
    - Phrased as question→action pattern?  <yes|no>
    - Applies symmetrically across dialects? <yes|no, why>
- Expected lift:        low | med | high
- Regression risk:      low | med | high + reasoning
- Cost impact (per round): <Δ$ if known>
- Diff:                 <code>
```

### 5.7 Generalization gate (auto-grep)

```bash
# Should return ZERO hits for any of these
grep -E "(local[0-9]+|bq[0-9]+|sf[0-9]+|ga[0-9]+)" <proposal>
grep -iE "(bigquery-public-data|spider2-public-data|GLOBAL_WEATHER|PWS_BI_SAMPLE|standard_tile)" <proposal>
grep -iE "(_TABLE_SUFFIX|UNNEST|PARSE_DATE|FLATTEN)" <proposal>  # dialect-specific tokens are OK in dialect skills, NOT in cross-dialect rules
```

If the rule is **going into a dialect-specific skill** (`bigquery-sql/SKILL.md`, `snowflake-sql/SKILL.md`), dialect tokens are fine. If it's going into the main verifier or pattern skills, dialect tokens fail the gate.

### 5.8 Apply, commit, run next round

```bash
git checkout -b loop/cloud-round-N-<short-name>
git add <files>
git commit -m "cloud round N: <category> — <one-line change>

Targets: <backend(s)>
Generalization: <one-line>
Tasks observed: sf044, bq287, ..."
```

If round N+1 shows regressions in regression-anchor sample → `git revert HEAD`, document why.

---

## 6. Anti-overfitting discipline

**Confirm the holdout never gets touched**:

```python
.venv/bin/python -c "
from benchmark.loop.sampler import cloud_held_out_set
from benchmark.core.suite import BenchmarkSuite
from benchmark.loop import registry as r
ho = cloud_held_out_set(BenchmarkSuite('spider2-lite'))
records = r.load_all()
leaks = [rec for rec in records if rec['task_id'] in ho and rec['round'] > 0]
print(f'holdout size: {len(ho)}')
print(f'LEAKS: {len(leaks)}')
for l in leaks[:10]: print(l)
"
```

If leaks > 0: stop, investigate, fix the sampler before continuing.

**Track regressions formally** every round:

```python
.venv/bin/python -c "
from benchmark.loop import registry as r
recs = [rec for rec in r.load_all() if any(rec['task_id'].startswith(p) for p in ('sf','bq','ga'))]
for task, was_pass, now_fail in r.regressions(recs):
    print(f'REGRESSION: {task}  passed in {was_pass}, failed in {now_fail}')
"
```

**Per-rule attribution**: keep the commit message format above with `Tasks observed: ...` so you can audit later "did rule X net-help?" via:

```python
# Tasks that flipped after rule X landed
.venv/bin/python -c "..."  # left as exercise
```

**Held-out validation only at the end**:

```bash
.venv/bin/python -m benchmark.run_parallel --concurrency 10 --model claude-sonnet-4-6 \
  --summary-out benchmark/results/cloud_holdout/summary.jsonl \
  $(.venv/bin/python -c "
from benchmark.loop.sampler import cloud_held_out_set
from benchmark.core.suite import BenchmarkSuite
print(' '.join(sorted(cloud_held_out_set(BenchmarkSuite('spider2-lite')))))
")
```

Compare to in-loop fresh-only pass rate. > 5pp divergence = overfit → reflect before shipping.

---

## 7. Reporting format (after every round)

```
════════════════════════════════════════════════════════════
CLOUD ROUND N COMPLETE  (elapsed: Xm Ys, claude $C, bq $B, sf compute ~$S)
════════════════════════════════════════════════════════════
Sample: 20 tasks (12 fresh / 6 targeted / 2 regression)
        backend split: SF=11 BQ=8 GA=1
Result: P PASS / F FAIL / E ERROR / V ENV_FAIL
        pass rate (excl. ENV_FAIL) = X%

Cumulative cloud trend:
  round 0 → cold start
  round 1 → 47.3%
  round 2 → ...
  round N → X%

Per-backend pass rate (this round):
  sf: P/T = X%
  bq: P/T = X%
  ga: P/T = X%

Regressions this round: <list, or "none">
Top failure category:   <category>  (count: N, backends: ...)

Layer-1 calibration (this round):
  check_name        fired  on_fail  on_pass  precision  recall
  ...

Proposal:
  <type>: <one-line>
  Generalization gate: PASSED / FAILED — <reason>
  Regression risk: low/med/high
  Applied: yes/no

Next round will draw 20 from the unseen pool (≈ K remaining).
════════════════════════════════════════════════════════════
```

---

## 8. Submission packaging (when ready to ship)

The Spider2 leaderboard scores against the full 547 tasks. Combining the **80% local held-out** with cloud results:

```bash
.venv/bin/python -m benchmark.submission build \
  --suite spider2-lite \
  --include-cloud \
  --out submission_$(date +%Y%m%d) \
  --tar \
  --method-name "SignalPilot-MCMC-Loop-cloud"
```

Email submission: `lfy79001@gmail.com` per Spider2 README. Include in body: method description, models used (sonnet-4-6 medium, 64k thinking), total cost ($-figure local + cloud), branch link.

---

## 9. Failure modes & recoveries (cloud-specific additions)

| Symptom | Likely cause | Recovery |
|---|---|---|
| BQ task fails with 403 `User does not have bigquery.jobs.create permission` | Connection registered with wrong project (data project, not billing project) | Already fixed in `runners/sql_runner.py` — verify the change is on the current branch. If a fresh checkout, re-apply. |
| BQ task fails with `default_dataset` errors | `dataset` field non-empty in BQ registration | Same fix: pass empty `dataset=""`. |
| SF task fails with `Schema 'X' does not exist or not authorized` | Participant role can't see that schema (data partitioning, see [cloud-connection-setup.md §4](../cloud-connection-setup.md)) | Mark as ENV_FAIL, exclude from optimization signal. Do **not** add a rule to "fix" this — it's not a model issue. |
| All SF tasks fail with auth errors | PAT expired or copied wrong | Run §5.1 PAT-expiry check; refresh with Spider2 organizers if expired. |
| BQ result truncated to 10000 rows when expected more | Gateway's `inject_limit` injects `LIMIT 10000` on every query | Either (a) raise the gateway's internal cap for this connection, (b) detect truncation in evaluation and re-issue without limit, or (c) accept truncation if the gold also fits in 10000 rows. Per-task. |
| All tasks fail with 401 Claude API | OAuth token in `.env` expired or rate-limited | Refresh `CLAUDE_CODE_OAUTH_TOKEN`; if rate-limited, wait. |
| Pass rate plateaus at X% on cloud | Approaching agent capability limit on dialect-specific patterns | Try dialect skill expansion (e.g., add `_TABLE_SUFFIX` examples to `bigquery-sql/SKILL.md`) before escalating to opus. |
| Sampler returns empty round | Holdout + cooldown excluded everything | Verify `task_filters=["sf","bq","ga"]` is set; check holdout size isn't `≥ pool / 2`. |

---

## 10. Sanity tests before round 1

```bash
# 1. Sampler returns non-empty cloud sample (after §3.1 extension)
.venv/bin/python -c "
from benchmark.loop.sampler import sample_round
from benchmark.core.suite import BenchmarkSuite
c = sample_round(BenchmarkSuite('spider2-lite'), n_total=5, task_filters=['sf','bq','ga'])
assert c.all_tasks
assert all(t.startswith(('sf','bq','ga')) for t in c.all_tasks)
print('cloud sampler OK:', c.all_tasks)
"

# 2. BQ smoke (paste-ready in cloud-connection-setup.md §3.2)
# 3. SF smoke (paste-ready in cloud-connection-setup.md §3.3)

# 4. End-to-end pipeline on one BQ + one SF task BEFORE batched round
.venv/bin/python -m benchmark.run_direct --suite spider2-lite bq001
.venv/bin/python -m benchmark.run_direct --suite spider2-lite sf001
# expect: result.csv produced, evaluator returns PASS or FAIL (FAIL is fine — we just
# need to confirm the pipeline runs end-to-end)

# 5. Holdout exclusion
.venv/bin/python -c "
from benchmark.loop.sampler import sample_round, cloud_held_out_set
from benchmark.core.suite import BenchmarkSuite
ho = cloud_held_out_set(BenchmarkSuite('spider2-lite'))
c = sample_round(BenchmarkSuite('spider2-lite'), n_total=20, task_filters=['sf','bq','ga'])
assert not (set(c.all_tasks) & ho), 'HOLDOUT LEAK'
print('holdout exclusion OK')
"
```

If any of these fail, fix before launching round 1.

---

## 11. Final notes

- This is **MCMC over prompt/skill space** with regression anchors as rejection criterion. Same protocol as local — the dial is the same; only the pool changes.
- Cloud has **two new failure modes** the local run never saw: (a) **environment failures** that aren't model failures (SF schema gaps), (b) **truncated results** from gateway LIMIT injection. Both should be detected and excluded from the lift signal, not "fixed" with rules.
- The **dialect skills** (`bigquery-sql/SKILL.md`, `snowflake-sql/SKILL.md`) are your dialect-specific surface area. If a fail category is genuinely dialect-bound (e.g., GA4 event-flattening with `UNNEST`), expand the dialect skill rather than adding a rule to the main verifier.
- The **judge** is your fail-mode classifier. Trust its categories but verify with a 2-task spot-check before drafting a rule.
- The **registry** is sacred — append-only. Cloud rounds will append to the same `benchmark/results/registry.jsonl` as local rounds; the `task_id` prefix differentiates them.
- The **held-out set** is your only honest evaluator. Touch it once, at the end.
- Default to **smaller, more conservative changes**. One rule per round. The user prefers slow + correct over fast + flaky. Same as local.

When in doubt, print state and ask. Auto-mode does not mean silent.
