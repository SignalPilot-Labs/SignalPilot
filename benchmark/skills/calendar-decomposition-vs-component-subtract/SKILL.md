---
name: calendar-decomposition-vs-component-subtract
description: "Use this skill whenever the question asks for the difference between two dates expressed as years, months, AND days (or any combination of two or more units). Component-wise subtraction (year-of-end minus year-of-start, etc.) silently overestimates the span when the smaller component is negative. The correct interpretation is calendar age decomposition (full years, then residual months, then residual days)."
type: skill
---

# Calendar-Decomposition Skill

## When this skill applies

Any question that asks for the time between two dates broken into more than one unit:
- "the difference in years, months, and days between debut and last game"
- "tenure as years and months"
- "age in years and days"
- "a span of Y years M months D days"
- a formula like `years + months/12 + days/365`

Also: any time the answer requires *combining* multiple unit-differences into a single number (e.g. fractional years).

## The trap

The natural-feeling SQL — subtract each unit independently and sum — gives the wrong answer whenever the smaller-unit component is negative:

```sql
-- WRONG: independent component subtraction
strftime('%Y', end) - strftime('%Y', start)  AS y_diff
strftime('%m', end) - strftime('%m', start)  AS m_diff
strftime('%d', end) - strftime('%d', start)  AS d_diff
-- then ABS each and sum (or sum and ABS)
ABS(y_diff) + ABS(m_diff)/12.0 + ABS(d_diff)/365.0
```

For start=2001-09-10, end=2006-04-13:
- Calendar truth: 4 years, 7 months, 3 days → 4 + 7/12 + 3/365 ≈ **4.59**
- Component subtraction with ABS: |5| + |−5|/12 + |3|/365 ≈ **5.42** ← off by ~18 %

The error compounds across the dataset and turns a passing answer into a failing one.

## What "calendar decomposition" means

Subtract whole calendar units, in order from largest to smallest, borrowing from the next unit when residual would be negative — exactly how you'd say "I am 27 years, 4 months, and 12 days old." Most dialects expose this directly:

| Dialect | Native form |
|---|---|
| PostgreSQL | `age(end, start)` returns an interval, then `EXTRACT(year/month/day FROM …)` |
| BigQuery | `DATE_DIFF` / `DATETIME_DIFF` per unit, then handle borrow manually |
| Snowflake | `DATEDIFF('year', start, end)` then adjust for partial year |
| SQLite | no native `age()` — see SQL pattern below |
| DuckDB | `age(end, start)` returns an interval (matches PostgreSQL) |

## SQL pattern — portable, no `age()` required

The trick: compute total days, then derive years and months by date-arithmetic borrowing.

```sql
-- Calendar decomposition: full years, residual months, residual days.
-- Works in any dialect with date math + day-add.

WITH inputs AS (
  SELECT
    start_date,
    end_date,
    -- A) full calendar years between dates
    CAST(strftime('%Y', end_date) AS INT) - CAST(strftime('%Y', start_date) AS INT)
      - CASE
          WHEN strftime('%m-%d', end_date) < strftime('%m-%d', start_date)
          THEN 1 ELSE 0
        END AS full_years
  FROM source
),
after_year AS (
  SELECT
    start_date, end_date, full_years,
    -- advance start_date by full_years to remove the year component
    date(start_date, '+' || full_years || ' years') AS start_plus_y
  FROM inputs
),
after_month AS (
  SELECT
    start_date, end_date, full_years, start_plus_y,
    -- B) full residual months
    CAST(strftime('%Y', end_date) AS INT) * 12 + CAST(strftime('%m', end_date) AS INT)
    - CAST(strftime('%Y', start_plus_y) AS INT) * 12 - CAST(strftime('%m', start_plus_y) AS INT)
    - CASE
        WHEN CAST(strftime('%d', end_date) AS INT) < CAST(strftime('%d', start_plus_y) AS INT)
        THEN 1 ELSE 0
      END AS residual_months
  FROM after_year
)
SELECT
  full_years,
  residual_months,
  -- C) residual days
  CAST(julianday(end_date)
       - julianday(date(start_plus_y, '+' || residual_months || ' months'))
       AS INT) AS residual_days
FROM after_month;
```

Then assemble per the question's formula:
```sql
full_years + residual_months / 12.0 + residual_days / 365.0
```

## Sanity-check before committing

Pick three start/end pairs by hand and verify:

1. **A pair that does NOT cross a unit boundary** (Jan 15 2010 → Mar 20 2015):
   - Expected: 5 years, 2 months, 5 days. Component subtraction gives the same answer here, so this case alone tells you nothing — keep going.

2. **A pair where the day component is negative** (Sep 10 2001 → Apr 13 2006):
   - Expected: 4 years, 7 months, 3 days. Component subtraction gives 5y −5m 3d which, after `ABS`, becomes 5y 5m 3d — visibly wrong.

3. **A pair where the month component is negative** (Nov 10 2010 → Mar 5 2015):
   - Expected: 4 years, 3 months, 25 days. Component subtraction gives 5y −8m −5d.

If your SQL produces the calendar values for cases 2 and 3 (not the component-subtraction values), it is correct.

## Anti-pattern (this is what fails)

```sql
ABS(year_diff) + ABS(month_diff)/12.0 + ABS(day_diff)/365.0
```

Each `ABS` independently strips the sign, so a negative residual that should reduce the count instead inflates it. Even before the `ABS`, summing signed components is fragile — the residual can leak past unit boundaries.

## Verification before saving

- [ ] Does the SQL borrow across boundaries (i.e., reduce years by 1 when end-month < start-month)?
- [ ] On a hand-picked boundary-crossing date pair, does your output match the calendar answer (not the component-subtract answer)?
- [ ] If your dialect has `age()` or an equivalent, are you using it instead of reimplementing?
