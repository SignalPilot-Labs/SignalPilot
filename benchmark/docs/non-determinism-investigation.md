# Spider2-DBT Non-Determinism Investigation

**Date**: 2026-04-10
**Trigger**: synthea001 consistently failing with "808 vs 809, 1 off" on `cost` table

This document captures a deep investigation into a class of Spider2-DBT failures caused by non-deterministic surrogate-key assignment in pre-shipped task scaffolding. It was triggered by trying (and repeatedly failing) to close the 1-row gap on synthea001, but the findings generalize.

---

## TL;DR

- A class of Spider2-DBT tasks contains `ROW_NUMBER() OVER (ORDER BY <non-unique column>)` in pre-shipped scaffolding files. DuckDB's tie-break for such patterns depends on execution plan / thread count / version — it is not guaranteed stable across environments.
- **This pattern is inherited from the OHDSI/ETL-Synthea upstream R package** (direct ancestor of synthea001). It is not a Spider2-introduced bug; it is a pre-existing accepted-bug in the OMOP ETL world.
- **30 of 68 Spider2-DBT tasks (44%) have at least one risky `ROW_NUMBER` pattern** per static scan. **16 of those pass anyway** because `ignore_order=True` + column-vector matching absorbs most surface drift. **~6–7 fail specifically because of surrogate-key cascade**: synthea001, superstore001, recharge001, recharge002, analytics_engineering001, inzight001, and probably danish_democracy_data001.
- For synthea001 specifically: no combination of DuckDB version (1.1.2 through 1.5.1 = 15 releases) and thread count (1 or 4) reproduces the gold's `int__all_visits` assignment at more than ~7.5% match rate. The gold was built with execution semantics we cannot replicate in DuckDB — most likely because the original OHDSI ETL ran on SQL Server.
- **Recommendation**: do not chase these individually with environment matching. Treat them as a known failure class, skip gold-side fixes, and focus benchmark effort on the higher-leverage Category A (CURRENT_DATE / date-spine) cluster which has 7 tasks.

---

## Synthea001 deep dive (the canary)

### The failure

```
cost  gold=(809, 22)  result=(808, 22)
```

One row short. Documented in `runs.md:71` as Category C — "Off by 1 / Identify which cost source drops the final row".

### The missing row

Diffing gold vs our test-env `int__cost_procedure`:

| | gold | ours |
|---|---|---|
| row count | 144 | 143 |
| missing from ours | `(cost_event_id=133, Procedure, 10430.07, 10430.07, 4892.13)` | — |

The missing row traces to a `procedure_occurrence` that joins against a `visit_occurrence` entry that doesn't exist in our build but does in gold's.

### The cascade

1. **`int__all_visits.sql`** line 3: `row_number() OVER (ORDER BY patient_id) AS visit_occurrence_id` — no tiebreaker. Each patient has ~22 visits; all 22 rows tie on `patient_id`. The surrogate key assignment is a tie-break away from undefined.
2. **`int__final_visit_ids.sql`** line 7: `row_number() OVER (PARTITION BY encounter_id ORDER BY priority)` — also no tiebreaker. Picks one vo_id per encounter.
3. Our build produces 5 collisions on `visit_occurrence_id_new` (= 5 encounters share vo_ids); gold produces only 2 collisions.
4. `visit_occurrence.sql` filters `WHERE visit_occurrence_id IN (SELECT DISTINCT visit_occurrence_id_new FROM int__final_visit_ids)` → our table has 597 rows, gold has 600.
5. `int__cost_procedure.sql` INNER-JOINs `procedure_occurrence → visit_occurrence` on `(visit_occurrence_id, person_id)` → 1 specific procedure orphans in our build.
6. `cost.sql` = UNION ALL of 4 `int__cost_*` tables → 808 vs 809.

### What we verified

| Test | Result |
|---|---|
| `int__all_visits` content (excluding `visit_occurrence_id`) identical between gold and ours | **YES** (all 5 non-surrogate columns match exactly) |
| Only `visit_occurrence_id` differs | **YES** |
| Sorted set of vo_id values identical (1..601) | **YES** |
| Raw seed data (`main_synthea_seeds.*`) byte-identical between canonical scaffold and gold | **YES** |
| `int__all_visits.sql` file byte-identical between canonical scaffold and our test-env | **YES** |
| Rebuilding `int__all_visits` from the **gold's own** `int__ip/er/op_visits` reproduces gold's `int__all_visits` | **NO — only 62/601 = 10.3% match** |

The last test is decisive: feeding the gold's own upstream into the committed SQL, with `threads=1` for determinism, still can't reproduce the gold's output. The provided `int__all_visits.sql` **cannot produce the gold's `int__all_visits` under any DuckDB execution**.

### DuckDB version sweep (15 versions × 2 thread counts × best-of-3)

Ran the int__all_visits rebuild in Docker (`sp-eval` image, pinned builds) for every DuckDB release from 2024-10 to 2026-03, with `threads=1` (deterministic) and `threads=4` (parallel). Measured match rate against gold's encounter → vo_id map.

| DuckDB threads=1 | match rate | threads=4 best-of-3 |
|---|---|---|
| 1.1.2 – 1.2.2 | 27/601 = **4.49%** | up to 37/601 = 6.16% |
| 1.3.0 – 1.3.2 | 30/601 = **4.99%** | up to 37/601 = 6.16% |
| 1.4.0 – 1.5.1 | 45/601 = **7.49%** | up to 45/601 = 7.49% |
| **Random baseline** (1 / ~22 visits-per-patient) | **~4.55%** | |

Interpretation: **every version produces output indistinguishable from random vs the gold's assignment**. No version hits a meaningful match rate. `threads=1` is deterministic per-version but diverges from gold.

### The upstream OHDSI/ETL-Synthea check

Cloned `https://github.com/OHDSI/ETL-Synthea` to look for a deterministic reference version. The R package ships a SQL Server implementation at `inst/sql/sql_server/cdm_version/v531/AllVisitTable.sql`. Line 113:

```sql
SELECT *, row_number() over(order by patient) as visit_occurrence_id
INTO @cdm_schema.all_visits
FROM (
    SELECT * FROM @cdm_schema.IP_VISITS
    UNION ALL
    SELECT * FROM @cdm_schema.ER_VISITS
    UNION ALL
    SELECT * FROM @cdm_schema.OP_VISITS
) T1;
```

**Identical non-determinism.** Spider2's dbt port is a faithful translation of the upstream. The upstream has the same bug. The OMOP/OHDSI community has tolerated it for years because analytical downstream workloads aggregate by clinical concept, not by surrogate vo_id.

### Why the Spider2 eval is sensitive to this anyway

The eval (`eval_utils.compare_pandas_table`) is generous:
- `ignore_order=True` for all synthea001 tables → sort each column vector before comparison
- `abs_tol=1e-2` for numeric comparisons
- Column-vector matching (any pred column can match any gold column)

**But** the fatal check is `if len(v1) != len(v2): return False` inside `vectors_match`. Row count mismatch is unrecoverable regardless of tolerance. Our cascade drops 1 specific row from `cost`, so `cost_id` sorted has length 808 vs gold's 809 → hard fail.

---

## Corpus scan — who else has this pattern?

Static scan over all `examples/*/models/**/*.sql` looking for `ROW_NUMBER / RANK / DENSE_RANK / NTILE` with a likely-non-unique `ORDER BY`:

| Finding | Count |
|---|---|
| Total task scaffolds scanned | 68 |
| Tasks with ≥1 risky window function | **30** (44%) |
| Risky pattern instances total | 126 |

### Split by current pass/fail status

| Task | Status | # risky patterns | Likely driver of failure? |
|---|---|---|---|
| synthea001 | FAILING | **19** | **YES** (deep cascade, see above) |
| danish_democracy_data001 | FAILING | 18 | likely (runs.md: "Surrogate key uses wrong column composition") |
| f1003 | PASSING | 10 | no |
| pendo001 | FAILING | 10 | unlikely — runs.md: "Category A - Date spine" |
| f1001 | FAILING | 7 | unclear — runs.md: "logic errors" |
| superstore001 | FAILING | 6 | **YES** (explicitly `ROW_NUMBER() OVER (ORDER BY NULL)` per runs.md) |
| tickit001 | PASSING | 5 | no |
| tickit002 | PASSING | 5 | no |
| analytics_engineering001 | FAILING | 5 | **YES** (runs.md: "ROW_NUMBER dedup loses rows") |
| workday001 | PASSING | 4 | no |
| workday002 | PASSING | 4 | no |
| jira001 | FAILING | 4 | unlikely — runs.md: "DuckDB type conflict" |
| f1002 | FAILING | 3 | unclear — logic errors |
| greenhouse001 | PASSING | 3 | no |
| lever001 | PASSING | 3 | no |
| hubspot001 | PASSING | 2 | no |
| marketo001 | PASSING | 2 | no |
| shopify001 | FAILING | 2 | unlikely — runs.md: "Category A - Date spine" |
| shopify002 | PASSING | 2 | no |
| shopify_holistic_reporting001 | PASSING | 2 | no |
| (rest: 10 tasks with 1 pattern each) | mix | 1 | mix |

### Tasks where non-determinism is plausibly the failure driver (per runs.md text)

| Task | Evidence from runs.md | Risky pattern count |
|---|---|---|
| synthea001 | "808 vs 809, 1 off — identify which cost source drops the final row" | 19 |
| superstore001 | "ROW_NUMBER() OVER (ORDER BY NULL) produces non-deterministic IDs" | 6 |
| analytics_engineering001 | "ROW_NUMBER dedup loses rows in join; insertion_timestamp is non-deterministic" | 5 |
| recharge001 | "charge_row_num sort order differs from gold" | 1 |
| recharge002 | "Row count consistently high by 2–12 rows" | 1 |
| inzight001 | "Peak value tie-breaking is non-deterministic" | 0 (not flagged by scan — logic-level, not SQL pattern) |
| danish_democracy_data001 | "Surrogate key uses wrong column composition" | 18 |

That's **~6–7 tasks where non-determinism is the actual blocker** out of 30 flagged, meaning:

- **The risky pattern is not itself a reliable predictor of failure.** Most tasks with it pass because the eval's `ignore_order=True` + column-vector matching is generous enough to absorb the surrogate drift.
- **When it does cause failure**, it's because the non-determinism cascades into row-count differences in an eval-critical table (visit_occurrence → cost for synthea001, dim/fct row counts for superstore001, etc.).

### Tasks where non-determinism is NOT the driver despite the pattern

This is the other 23 tasks — they have the pattern but fail for different reasons (date-spine drift, wrong JOIN type, logic errors, DuckDB compatibility, schema mismatches). Fixing the `ROW_NUMBER` pattern on those would not flip them.

---

## Why version matching / docker pinning did not work

- Spider2's own `spider2-dbt/methods/spider-agent-dbt/.../Dockerfile` uses **unpinned** `pip install duckdb` / `pip install dbt-duckdb`. The gold was built with "whatever pip resolved on build day".
- The last Spider2 `evaluation_suite/gold/` commit was **2025-06-26**. On that date, the latest stable releases were **duckdb 1.3.1** (2025-06-16) and **dbt-duckdb 1.9.4** (2025-06-25).
- Built a reproducible Docker container (`benchmark/ref/Dockerfile.spider-eval`) with those exact pins + `threads=1` to kill parallelism. Swept 15 DuckDB versions. None matched.
- Separately, tried using the **gold's own `int__ip/er/op_visits` tables as input** — still only 10% match. The SQL literally cannot produce the gold's output under any known configuration.

Implication: the gold was built with a fundamentally different execution (probably SQL Server running the upstream OHDSI R package directly), and the output was ported to DuckDB format as a frozen artifact. No dbt-duckdb pipeline can reproduce it.

---

## What not to do

1. **Do not regenerate the gold.** The gold is the submission target. I proposed regenerating it from a hand-patched deterministic pipeline; this is circular reasoning when the agent being tested is the same LLM doing the regeneration. The honest posture is: the gold is the target; our job is to reach it, not to change it to match us.

2. **Do not hand-patch pre-shipped `int__all_visits.sql` in the canonical scaffold.** That's modifying the benchmark task files outside the agent's authorship, which leaks evaluator-side knowledge into the pipeline.

3. **Do not obsess over version matching.** A 15-version DuckDB sweep confirmed the answer is not "find the right version". Spending more time on this is negative-ROI.

---

## What to do

In rough order of leverage:

### 1. Focus benchmark effort on Category A (date spine / CURRENT_DATE) — 7 tasks

Per `progress.md` line 46, the #1 failure category is "Date Spine / CURRENT_DATE" affecting 7 tasks (salesforce001, shopify001, xero001, xero_new001, xero_new002, quickbooks003, pendo001). The documented fix is "if a package model uses `current_date`, create a local override". This is a much higher-leverage target than non-determinism — fixing it cleanly could flip 3–5 tasks versus synthea001's 1.

### 2. Add a `dbt_project_map` signal for agents on non-determinism

Add a "non-determinism scan" to the `dbt_project_map` MCP tool output. When the agent calls `dbt_project_map project_dir=X`, it should get a section like:

```
## Non-determinism warnings
  models/intermediate/int__all_visits.sql:3  ROW_NUMBER() OVER (ORDER BY patient_id)  — no tiebreaker on non-unique column
  ...
```

This gives the agent a chance to notice and proactively rewrite these files **as part of the task**, rather than requiring us to pre-patch anything. Legitimate engineering work the agent can do within the task rules.

### 3. Add prompt guidance: "pre-existing SQL with non-deterministic ORDER BY is fair game to rewrite"

The current prompt says "don't break complete models". Clarify: **"Pre-existing files that use non-deterministic `ROW_NUMBER()` / `RANK()` / `NTILE()` are fair game to rewrite to be deterministic, especially if they are upstream of eval-critical models."**

### 4. Mark these ~6 tasks in the benchmark metadata

In `runs.md`, add a new column or note to flag the tasks where non-determinism in pre-shipped SQL is the actual blocker, not agent logic errors. This separates "agent couldn't reason about the task" from "agent couldn't overcome upstream pipeline defects". Gives a cleaner signal for what kinds of agent-side improvements would actually flip those tasks.

### 5. (Optional, future work) Build a deterministic local gold for self-improvement fine-tuning

Once the agent has a way to proactively fix the non-determinism (steps 2 and 3), we can run the full benchmark in the pinned `sp-spider2-eval` Docker env, let the agent produce deterministic output, and capture that as a local reference for self-improvement loops. This is separate from Spider2 submission — it's purely for internal agent-training iteration.

---

## Files produced during this investigation

All under `benchmark/scratch/` (ignored by default):

- `_duckdb_versions.txt` — the 15 duckdb versions swept
- `_duckdb_sweep.py` — rebuild int__all_visits and measure gold match
- `_duckdb_sweep_orchestrator.py` — loop version → pip install → run → collect
- `_duckdb_sweep_results.csv` — full table of version × threads × match count
- `_find_missing_cost_row.py` — diff gold vs ours to identify the specific missing row
- `_gold_roundtrip.py` — test rebuilding int__all_visits from gold's own upstream
- `_scan_nondet_patterns.py` — corpus-wide static scan for risky window functions
- `_nondet_scan.csv` — full scan results (task, file, line, pattern, reason)
- `_seed_compare.py` — byte-level compare of raw seeds between gold and canonical
- `_compare_upstream.py` — compare int__all_visits columns between gold and ours
- `_spider_env_e2e.py` / `_e2e_v2.py` — clean-room dbt run attempts with pinned stack
- `_duckdb_v100_test.py` — earlier single-version direct test

Reference repos cloned under `benchmark/ref/`:

- `spider/` — full Spider2 repo clone (read-only reference)
- `synthea-omop-etl/` — OHDSI/ETL-Synthea upstream (confirms non-determinism inheritance)

Docker image: `sp-spider2-eval` — reproducible pinned build env, kept on disk for future version debugging if needed. Dockerfile at `benchmark/ref/Dockerfile.spider-eval`.
