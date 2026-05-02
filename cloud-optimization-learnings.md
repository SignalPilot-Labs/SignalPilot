# Spider2-Lite **Cloud** Self-Improvement Loop — Per-Round Learnings

Mirror of `local-optimization-learnings.md` but for the 412-task cloud subset
(BigQuery `bq*` 180 + GA4 `ga*` 25 + Snowflake `sf*` 207). Sacred 30-task
holdout (14 sf / 13 bq / 3 ga, seed=42) excluded from every round.

## Bootstrap (pre round 1)
**Branch:** `loop/cloud-round-1-bootstrap`
**Commits:**
- `74d32f3` sampler/runner cloud extension + carry-forward setup
- `2120d35` `_determine_backend` uses instance_id prefix as primary signal
  (was incorrectly routing all `bq*` tasks with `noaa_data`-style overlap to
  Snowflake because directory inference checked snowflake first)
- `<round-1>` judge regex extended for cloud prefixes; verifier rule 15

**Sampler changes:**
- `task_filters: list[str] | None` parameter on `sample_round` and `held_out_set`
- `cloud_held_out_set()` — n=30, stratified 14sf/13bq/3ga, seed=42
- targeted/regression candidate filters now respect `task_filters` so
  registry's local-only pool can't leak into a cloud round
- runner `--cloud` flag passes `task_filters=["sf","bq","ga"]`

**Backend resolver fix:**
Before: `_determine_backend` used directory-existence check; `noaa_data`,
`ga360`, etc. exist under both `resource/databases/snowflake/` AND
`resource/databases/bigquery/`. Loop checked snowflake first → all `bq*` tasks
with overlap silently misrouted to Snowflake (first round 1 launch killed at
2 min when this surfaced).
After: instance_id prefix is primary — `bq*`/`ga*` → BigQuery, `sf*`/`sf_bq*`
→ Snowflake, `local*` → SQLite. Directory inference kept as fallback.

**Run-flow gotchas:**
- `asyncio.gather` blocks forever on a hung task — round.log shows 19/20 ENDs
  but registry never gets written. If a task hangs past ~14min, kill the
  parent process and seed the registry manually with `seed_registry --round N`,
  then append the timeout task as ERROR.
- Per-task wall time on cloud is highly bimodal: simple BQ queries finish in
  ~100s/$0.25, but TCGA-grade joins (e.g. bq046, ~37 case_barcodes × per-case
  pagination) blew past the 900s timeout banner.
- Layer-1 checks were tuned on local SQLite shapes — caught 0 of 6 fails on
  cloud round 1. Expected; observe for 2–3 rounds before re-calibrating.

## Round 1 — Cold-start baseline (no rule changes)
**Sample (n=20):** 11 BQ + 9 SF + 0 GA (per-DB cap squeezed GA out)

**Result:** 12 PASS / 6 FAIL / 2 ERROR
- Pass rate excl. ERROR: **66.7%**
- Pass rate raw: **60.0%**
- BQ: 7/9 = 77.8%
- SF (`sf_bq*`): 5/9 = 55.6%

**Cost:** ~$10 Claude API + minimal BQ scan + SF compute on participant warehouse

**Judge fail-category tally:**
- `wrong_filter_predicate` (2): bq090 fabricated `LIKE 'LUCKY%'/'MOMO%'` for
  domain terms instead of probing actual values; sf_bq295 used `SAMPLE_*`
  tables instead of full sibling tables.
- `wrong_value_calc` (2): bq202 used BigQuery default DAYOFWEEK convention
  (1=Sunday) when expected output was Monday=1; sf_bq160 wrapped a raw
  microsecond integer in `TO_DATE(TO_TIMESTAMP(...))` when the question
  expected the raw integer.
- `missing_column` (1): bq053 dropped derived percentage columns the
  question implied.
- `result_excess` (1): sf_bq291 returned 30 daily rows when only 1
  creation-date row existed in the data.
- `wrong_aggregation` (1): sf_bq215 used wrong dedup grain on patent
  citations.

**Proposal applied:** Rule 15 — UNREQUESTED OUTPUT TRANSFORMATION (verifier).
Targets `wrong_value_calc` (2/7). Generalizes across all three dialects
(BQ DAYOFWEEK convention, SF TO_DATE wrapping, hypothetical SQLite `strftime`
analogs). No schema/table/db names; phrased as question→action.

**Why this rule over the alternatives:**
- vs. refining rule 14 to broaden domain-term match: rule 14a already
  partially covers literal-filter fabrication; expanding it would help bq090
  but the table-choice case (sf_bq295, `SAMPLE_*` vs full) is structurally
  different. Defer.
- vs. dialect-specific skill addition: BQ DAYOFWEEK and SF TO_DATE are not
  dialect bugs — they're agent assumptions. Right place is the verifier, not
  bigquery-sql/snowflake-sql skills.

**Watch for round 2:**
- `wrong_value_calc` should drop to ≤1 if rule fires correctly.
- Regressions to monitor: bq119 (uses legitimate date math), sf_bq012/167/251
  (already-passing SF cases that exercise output formatting).
- If `wrong_filter_predicate` (bq090, sf_bq295) repeats, propose rule 14
  refinement in round 3.

## Round 2 — Rule 15 active, registry round=9
**Branch:** `loop/cloud-round-2`
**Sample (n=20):** 11 BQ + 9 SF + 0 GA (per-DB cap; same as round 1)

**Result:** 11 PASS / 6 FAIL / 3 ERROR
- Pass rate excl. ERROR: **64.7%** (vs 66.7% round 1 — within stochastic noise)
- Pass rate raw: **55.0%**
- BQ: 6/10 = 60.0% (vs 77.8%)
- SF (`sf_bq*` + `sf*`): 5/8 = 62.5% (vs 55.6%)
- GA4: 0 again

**ERROR breakdown:** bq115 (401 retry burst at start, eval re-ran clean → judge says spurious_pass);
bq002 (evaluator delta from runtime — workdir present); sf_bq460 (Snowflake compute
on word-vector tokenization, killed parent at 24min, seeded as `timeout_15min_no_save`).

**Cost:** ~$11 Claude API + cloud compute (sf_bq325 ate ~$1.65 alone in iterative debugging;
sf_bq052 reached $1.57 before timing out without final write).

**Rule 15 verdict — EFFECTIVE, KEEP:**
- `wrong_value_calc`: 2 → **0**
- No regressions on round-1 PASS cases that exercised raw output (bq030, bq103, sf_bq091,
  sf_bq349 all PASSed again).
- Adjacent fail bq002 (DATE_TRUNC week-start vs ISOWEEK) is conceptually similar but the
  judge categorized it as `wrong_aggregation`. Rule 15 (b) covers calendar *extraction*
  (EXTRACT, DAYOFWEEK); bucketing/truncation isn't covered. Candidate for round 4 if the
  pattern repeats.

**Judge fail-category tally:**
- `wrong_filter_predicate` (4): sf012 (community name exact-match — borough variants),
  sf013 (quadkey exact-match — finer-grained stored), sf_bq325 (DENSE_RANK pre-filter
  pruned the true minima), bq008 (filter scope + unit conversion mixed).
- `wrong_aggregation` (1): bq002 (default WEEK = Sunday-start vs gold's ISOWEEK).
- `missing_column` (1): bq425 (dropped MOLECULE_ID/COMPANY_NAME).
- `wrong_join_or_fanout` (1): sf_bq052 (citation direction reversed —
  `patent_id = pa.patent_id` instead of `citation_id = pa.patent_id`).
- `result_truncated` (1): bq360 (LIMIT 1 instead of 10-row + flag column).

**Proposal applied — rule 14(a) extension:**
Broadens 14(a) from "status value not looked up" to "any literal value, identifier, or
string pattern not verified against the actual column". Generalization gate PASSED.
Targets sf012 + sf013 (2 of 4 wrong_filter_predicate). bq008 + sf_bq325 are structurally
different and not addressed by this round.

**Why this over alternatives:**
- vs. new rule for granularity-of-stored-keys (sf013): too narrow, would not generalize.
- vs. rule 15(e) for bucketing/truncation (bq002): only n=1 evidence in round 2;
  defer to round 4 if it repeats.
- vs. rule on directional-relationship verification (sf_bq052 citation direction):
  also n=1; defer.
- Per "≤1 generalizable change per round" discipline.

**Run-flow note:** Killing the parent process when 1 task hangs past 22min and seeding
the registry manually is becoming routine. If this happens 1 more time on cloud (round
3 or 4), worth adding a per-task wall-clock kill in the runner instead of the cooperative
timeout banner.

**Watch for round 3:**
- `wrong_filter_predicate` should drop from 4 → ≤2 if rule 14(a) refinement fires.
- Regressions to monitor: round-2 PASS tasks that used direct equality filters
  (sf_bq091, sf_bq349, bq103, bq030) — should not start over-probing trivial filters.
- If `wrong_aggregation` (bq002) or `wrong_join_or_fanout` (sf_bq052) recurs,
  those are next round's candidates.
- If GA still n=0 across rounds 3–4, lift per-DB cap from 2 → 3 for GA stratum only.

## Round 3 — Rule 14(a) refined active, registry round=10
**Branch:** `loop/cloud-round-3`
**Sample (n=20):** 11 BQ + 9 SF + 0 GA again

**Result (post-retry):** 11 PASS / 8 FAIL / 1 ERROR
- Pass rate excl. ERROR: **57.9%** (R1 66.7% → R2 64.7% → R3 57.9%)
- Pass rate raw: **55.0%**
- BQ: 5/9 = 55.6%
- SF: 6/10 = 60.0%

**Trajectory note:** 3 rounds in, still in the n≈18 stochastic-noise band. Categorical
distribution is shifting more decisively than the raw rate.

**Retry workflow now standard:**
- 4 tasks ERRORed at exactly 5.1s (SDK startup-wave timeout — all in batch 2 of
  concurrency-10). 1 ERRORed at 162s. Re-ran via `python -m benchmark.run_parallel
  ... --concurrency 5 --summary-out`.
- 4/5 retries finished cleanly (sf_bq214 PASS, sf006/sf_bq118/bq234 FAIL); sf_bq450
  hung again (turn 128 / 1075s in iterative verifier loop) — left as ERROR.
- Registry round=10 patched in-place: replaced ERROR rows with retry-derived
  PASS/FAIL via `evaluate_sql` on the post-retry workdir.

**Cost:** ~$10 main + ~$3 retries.

**Rule 14(a) verdict — EFFECTIVE:**
- `wrong_filter_predicate`: 4 (R2) → 1 (R3). Refinement caught the literal-vs-stored
  class. The remaining R3 case (sf006) is a different sub-pattern: "all 50 states"
  scope check (DC inclusion). Coverage-probe rule could target this in R5+.

**Rule 15 verdict — STILL EFFECTIVE for original target:**
- R3 saw 2 `wrong_value_calc` (bq038 fixed-bucket boundary, bq393 DATE_DIFF
  off-by-2), but BOTH are arithmetic-shift cases, NOT the unrequested-transformation
  pattern rule 15 targets. So rule 15 is still correctly scoped; arithmetic-shift
  is a separate emerging anti-pattern (candidate for R5).

**Judge fail-category tally (n=9 real non-PASS):**
- `wrong_value_calc` (2): bq038, bq393 — arithmetic-shift sub-pattern
- `wrong_aggregation` (2): bq234 (drug-name normalization), sf_bq118 (collapsed to
  scalar instead of per-age-group)
- `wrong_join_or_fanout` (2): bq457 (direct name-match where dependencies edge
  needed), sf_bq420 (pre-grant pubs instead of granted patents)
- `wrong_filter_predicate` (1): sf006 (DC-vs-50-states scope)
- `numeric_precision` (1): bq035 (geodesic float diffs)
- `missing_artifacts` (1): sf_bq450 (retry timeout)

**Cumulative wrong_join_or_fanout: R1=0, R2=1 (sf_bq052 citation direction),
R3=2 (bq457, sf_bq420). Rising trend → highest-priority rule target.**

**Proposal applied — rule 16 (RELATIONSHIP DIRECTION & HOP COUNT):**
New verifier rule. If question contains a relational verb (depends on, cited by,
derived from, owned by, etc.), the join structure must match the direction AND hop
count. Three sub-clauses: (a) direct name-match where edge table needed,
(b) wrong direction on a directional edge, (c) near-name table choice (pgpub vs
granted). Generalization gate PASSED — no schema names, dialect-symmetric, no
gold-token leak.

**Why this over alternatives:**
- vs. rule for arithmetic-shift (bq038/bq393): only n=2 in R3, no precedent in R1-R2.
  Defer.
- vs. rule for drug-name / category normalization (bq234): too narrow.
- vs. coverage-probe rule for "all 50 states" / "every age group" (sf006/sf_bq118):
  lifts only 2 of 9 fails; rule 16 lifts 2 of 9 directly + prevents R2-style
  recurrence of sf_bq052.

**Watch for round 4:**
- `wrong_join_or_fanout` should drop from 2 → 0–1 if rule 16 fires.
- Regressions to monitor: PASS tasks doing single-hop name joins (bq030, sf_bq091,
  sf_bq349 still PASSing) — should not start over-traversing the schema graph.
- If `wrong_value_calc` arithmetic-shift sub-pattern continues at 2+, propose
  rule 17 in R5.
- GA still 0: lift per-DB cap from 2 → 3 for GA stratum only in R4.
