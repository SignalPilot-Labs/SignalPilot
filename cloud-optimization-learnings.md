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
