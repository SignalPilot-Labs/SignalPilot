---
name: temporal-comparison
description: "Use this skill when the question asks to compare values across two or more time periods (e.g., 'Q4 2019 vs Q4 2020', 'year-over-year', 'before vs after', 'in 2018 and 2019', 'monthly change'). Ensures the result includes a SEPARATE column for EACH period's value, not just the difference."
type: skill
---

# Temporal Comparison Skill

## When this skill applies

The user's question mentions two or more named time periods to be compared:
- "Q4 2019 and Q4 2020"
- "January through March 2018"
- "year-over-year change"
- "monthly trend over the last 6 months"
- "compared to the previous quarter"
- "before and after the policy change"

## What to output

The result MUST contain a separate column for each period's value, in addition to any change/difference column. Three output shapes are acceptable; pick the one that matches the question:

### Shape A — wide pivot (preferred when periods are named)
```
entity_id, entity_name, value_2019, value_2020, change_pct
```

### Shape B — long with explicit period column (preferred when periods are dynamic)
```
entity_id, entity_name, period, value
```

### Shape C — wide with derived columns (when question asks for both raw and derived)
```
entity_id, entity_name, value_2019, value_2020, abs_change, pct_change
```

## Anti-pattern (this is what fails)

Returning ONLY the change/difference and dropping the per-period values:
```
entity_id, entity_name, change_pct       ← WRONG: per-period values lost
```

When the question says "compare X in period A vs period B", a reviewer cannot verify your numbers without seeing both period values. Always include both.

## SQL pattern (wide pivot)

```sql
WITH period_values AS (
  SELECT entity_id,
         SUM(CASE WHEN <period_filter_a> THEN metric END) AS value_a,
         SUM(CASE WHEN <period_filter_b> THEN metric END) AS value_b
  FROM fact_table
  WHERE <period_filter_a> OR <period_filter_b>
  GROUP BY entity_id
)
SELECT entity_id, value_a, value_b,
       (value_b - value_a) AS abs_change,
       (value_b - value_a) / NULLIF(value_a, 0) AS pct_change
FROM period_values
WHERE value_a IS NOT NULL AND value_b IS NOT NULL  -- exclude entities present in only one period unless the question allows
```

## SQL pattern (long form)

```sql
SELECT entity_id,
       <period_expression> AS period,
       SUM(metric) AS value
FROM fact_table
WHERE <period_filter_combined>
GROUP BY entity_id, <period_expression>
ORDER BY entity_id, period
```

## Window-baseline trap

If the question excludes a period ("starting from year 2", "after the policy change") AND you compute change via LAG/LEAD over a window, the excluded period must still feed the window source so the first kept period has a baseline. Otherwise the first kept row's delta is NULL.

```sql
WITH all_periods AS (  -- include ALL periods so LAG has data
  SELECT entity_id, period, SUM(metric) AS value
  FROM fact_table
  GROUP BY entity_id, period
),
with_lag AS (
  SELECT entity_id, period, value,
         LAG(value) OVER (PARTITION BY entity_id ORDER BY period) AS prev_value
  FROM all_periods
)
SELECT * FROM with_lag WHERE period >= <kept_start>  -- filter AFTER LAG
```

## Verification before saving

- [ ] Are both periods' values present as columns? (Or as rows in long form?)
- [ ] Are entities present in only one period handled per the question's intent? (Excluded? Kept with NULL?)
- [ ] If using LAG/LEAD, is the first kept row's prev_value populated?
- [ ] Does the change column's sign match a sample row's actual values?
