---
name: classification-with-score
description: "Use this skill when the question places entities into grades, tiers, quintiles, percentile bands, categories, or buckets (e.g., 'classify customers into A/B/C tiers', 'top quintile', 'pass/fail grade'). Ensures the result includes BOTH the numeric score that drove the classification AND the categorical label."
type: skill
---

# Classification-with-Score Skill

## When this skill applies

The question requires assigning entities to categories based on a numeric value:
- "classify each X into tiers"
- "what quintile is each X in"
- "label each X as high/medium/low"
- "top 20% / top decile / first percentile"
- "pass/fail" or "above/below threshold"
- "letter grade" / "category A/B/C"

## Required output columns

The result MUST include BOTH:

1. **The numeric value** that drove the classification (the actual score / metric)
2. **The classification label** (the tier name / quintile number / category letter)

The classification label alone is not enough — a reviewer needs to verify that the threshold was applied correctly without re-running your query.

```
entity_id, entity_name, score, tier
A100,      Alice,        95.0,  Top
B200,      Bob,          78.0,  Mid
C300,      Carol,        42.0,  Low
```

## Anti-patterns (these fail)

**A. Label without the underlying score**
```
entity_id, entity_name, tier        ← reviewer cannot verify the threshold was applied correctly
```

**B. Score without the label**
```
entity_id, entity_name, score       ← question asked for the classification, not the raw score
```

## SQL patterns

### Quintile / NTILE bucketing
```sql
SELECT
    entity_id,
    entity_name,
    metric AS score,
    NTILE(5) OVER (ORDER BY metric DESC) AS quintile
FROM ...
```
Note: `NTILE(5)` produces buckets 1..5. Bucket 1 = top 20% when ORDER BY DESC.

### Percentage thresholds ("top 20%")
```sql
WITH ranked AS (
    SELECT entity_id, entity_name, metric,
           PERCENT_RANK() OVER (ORDER BY metric DESC) AS pct_rank
    FROM ...
)
SELECT entity_id, entity_name, metric AS score,
       CASE WHEN pct_rank <= 0.20 THEN 'top'
            WHEN pct_rank <= 0.50 THEN 'mid'
            ELSE 'bottom' END AS tier
FROM ranked
```

### Fixed thresholds (pass/fail, A/B/C)
```sql
SELECT
    entity_id,
    entity_name,
    metric AS score,
    CASE WHEN metric >= 90 THEN 'A'
         WHEN metric >= 80 THEN 'B'
         WHEN metric >= 70 THEN 'C'
         ELSE 'F' END AS grade
FROM ...
```

## Subtle traps

**Top X% via NTILE is approximate, not exact.** `NTILE(5)` divides rows into roughly equal-sized buckets — if the population isn't evenly distributed, the top bucket can be slightly more or fewer than 20%. If the question requires *exactly* top 20%, use PERCENT_RANK or a fractional cutoff.

**Direction of ORDER BY matters.** "Top quintile" with `ORDER BY metric DESC` → NTILE bucket 1. With `ORDER BY metric ASC` → NTILE bucket 5. Pick consistently and document.

**Ties on the boundary.** Two entities with the same score may fall in different NTILE buckets arbitrarily. If reproducibility matters, add a deterministic tie-breaker to the ORDER BY.

## Verification before saving

- [ ] Result has BOTH a numeric score column AND a classification label column?
- [ ] Bucket counts roughly match the question? (If "top 20%", is the top bucket ~20% of rows?)
- [ ] If using NTILE, did you sort in the correct direction?
- [ ] Sample row: does the score value plausibly justify the assigned label?
