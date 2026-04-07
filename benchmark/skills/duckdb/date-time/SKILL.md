---
description: "DuckDB date and time functions — extraction, arithmetic, formatting, and pitfalls that differ from PostgreSQL/MySQL."
---

# DuckDB Date & Time

## Extract Parts
```sql
YEAR(d), MONTH(d), DAY(d), HOUR(ts), MINUTE(ts)
DAYOFWEEK(d)      -- 0=Sun, 1=Mon, ..., 6=Sat
ISODOW(d)         -- 1=Mon, ..., 7=Sun (ISO standard)
DAYOFYEAR(d)
WEEKOFYEAR(d)
QUARTER(d)
```

## Current Date/Time
```sql
CURRENT_DATE              -- date only
CURRENT_TIMESTAMP         -- timestamp
NOW()                     -- same as CURRENT_TIMESTAMP
```

## Date Arithmetic
```sql
d + INTERVAL '7' DAY       -- add days
d - INTERVAL '1' MONTH     -- subtract months
d + INTERVAL '2' YEAR      -- add years

DATE_TRUNC('month', d)     -- first day of month
DATE_TRUNC('week', d)      -- first day of week (Monday)
DATE_TRUNC('quarter', d)   -- first day of quarter
DATE_TRUNC('year', d)      -- first day of year

LAST_DAY(d)                -- last day of month
DATE_DIFF('day', d1, d2)   -- difference in days
DATE_DIFF('month', d1, d2) -- difference in months
```

## Formatting
```sql
STRFTIME(d, '%Y-%m-%d')    -- 2024-01-15
STRFTIME(d, '%A')           -- Monday (full day name)
STRFTIME(d, '%a')           -- Mon (short day name)
STRFTIME(d, '%B')           -- January (full month)
STRFTIME(d, '%b')           -- Jan (short month)
STRFTIME(d, '%m/%d/%Y')    -- 01/15/2024
```

## Critical Differences from PostgreSQL/MySQL
- **No `DATEADD()`** — use `date + INTERVAL '1' DAY`
- **No `DATEDIFF()`** — use `DATE_DIFF('unit', start, end)`
- **`+ 6` does NOT add days** — use `+ INTERVAL '6' DAY`
- **`- 1` does NOT subtract days** — use `- INTERVAL '1' DAY`
- **Date subtraction returns INTERVAL**, not integer — use `DATE_DIFF` instead
- `DATE_TRUNC` returns TIMESTAMP, not DATE — cast with `CAST(... AS DATE)` if needed
- `INTERVAL` syntax requires quotes: `INTERVAL '1' DAY` not `INTERVAL 1 DAY`
