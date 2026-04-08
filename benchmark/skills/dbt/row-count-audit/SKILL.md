---
description: "Row count audit protocol — diagnosing and fixing JOIN fan-out and over-filter in dbt models."
---

# Row Count Audit

## When to Run

After every successful `dbt run` on a priority model. A passing dbt run with wrong row counts
fails evaluation just as much as a compile error. Run this audit before declaring any model done.

## The 5-Step Audit

**Step A — Baseline cardinality from primary source:**
```sql
SELECT COUNT(*) AS source_rows, COUNT(DISTINCT <pk>) AS unique_pks FROM <source_table>;
```

**Step B — Count your output:**
```sql
SELECT COUNT(*) AS output_rows FROM {{ ref('my_model') }};
```

**Step C — Decide if count is correct:**
- Aggregation model (one row per group): `output_rows == COUNT(DISTINCT group_key)`
- Pass-through/filter model: `output_rows <= source_rows`; verify against task description

**Step D — If output_rows > expected → FAN-OUT:**
```sql
SELECT <join_key>, COUNT(*) AS cnt
FROM {{ ref('my_model') }}
GROUP BY <join_key> HAVING cnt > 1
ORDER BY cnt DESC LIMIT 10;
```
Fix: pre-aggregate the right-join table, or add DISTINCT, or use ROW_NUMBER() dedup.

**Step E — If output_rows < expected → OVER-FILTER:**
Remove one WHERE/JOIN condition at a time, counting rows each time.
Check if INNER JOIN should be LEFT JOIN (rows with no match are being silently dropped).

NEVER finish a priority model without running this 5-step audit.

## Fan-Out Playbook

Too many rows: one left-side row is matching multiple right-side rows in a JOIN.

**Diagnose — find duplicating join keys:**
```sql
SELECT join_key, COUNT(*) AS cnt
FROM {{ ref('my_model') }}
GROUP BY join_key HAVING cnt > 1
ORDER BY cnt DESC LIMIT 10;
```

**Fix A — pre-aggregate right table before joining:**
```sql
WITH deduped AS (
  SELECT join_col, MAX(value) AS value
  FROM right_table GROUP BY join_col
)
SELECT l.*, d.value FROM left_table l
INNER JOIN deduped d ON l.join_col = d.join_col
```

**Fix B — select distinct on output (only when all columns are determinate):**
```sql
SELECT DISTINCT id, col1, col2 FROM {{ ref('my_model') }}
```

**Fix C — ROW_NUMBER() dedup (when you need "most recent" or "first"):**
```sql
WITH ranked AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY join_key ORDER BY updated_at DESC) AS rn
  FROM right_table
)
SELECT l.*, r.value
FROM left_table l
JOIN ranked r ON l.join_key = r.join_key AND r.rn = 1
```

## Over-Filter Playbook

Too few rows: conditions or JOIN types are dropping rows that should be in the output.

**Binary search — which condition drops rows?**
```sql
SELECT COUNT(*) FROM source_table;                          -- baseline: 874
SELECT COUNT(*) FROM source_table WHERE cond_1;             -- still 874? keep
SELECT COUNT(*) FROM source_table WHERE cond_1 AND cond_2;  -- drops to 460? cond_2 culprit
```

**Check if INNER JOIN silently drops legitimate rows:**
```sql
SELECT COUNT(*) FROM left_table l
LEFT JOIN right_table r ON l.id = r.id
WHERE r.id IS NULL;
-- If count > 0 and those rows should appear: switch to LEFT JOIN
```

**LEFT JOIN + WHERE right.col IS NOT NULL = INNER JOIN (dangerous anti-pattern):**
```sql
-- BAD: silently drops unmatched left rows
SELECT l.*, r.name FROM left_table l
LEFT JOIN right_table r ON l.id = r.id
WHERE r.name IS NOT NULL;

-- GOOD: explicit about intent
SELECT l.*, r.name FROM left_table l
INNER JOIN right_table r ON l.id = r.id
```

## Value Mismatch Playbook

Row counts match but values are wrong.

- Check source column type first: `DESCRIBE <table>`
- For currency — check scale: `SELECT MIN(amount), MAX(amount) FROM <table>`
  (values of 150000 when expecting 1500.00 = cents vs dollars)
- For dates — always `explore_table` before assuming format
  (European DD/MM/YYYY requires `STRPTIME(col, '%d/%m/%Y')`)
- Validate your formula on 2–3 known rows manually before writing SQL

## Priority Protocol

- PRIORITY models trump all other work
- At turn 15, stop exploring; write the priority model with current knowledge
- A wrong-but-built model is better than a never-written model — the fix agent can correct it
- After writing, immediately `dbt run --select <model>` — do not batch with other models
- Then run the 5-step audit above before moving on
