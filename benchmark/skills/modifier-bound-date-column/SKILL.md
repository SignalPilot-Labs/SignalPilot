---
name: modifier-bound-date-column
description: "Use this skill when the question pairs a state modifier ('delivered', 'shipped', 'completed', 'cancelled', 'paid', 'refunded', 'approved', 'fulfilled') with a temporal grouping ('per month', 'in 2018', 'monthly volume', 'by quarter'). The date column to bucket on is the state-transition timestamp for that modifier (order_delivered_customer_date), not the generic creation timestamp (order_purchase_timestamp). Picking the wrong date column shifts entire month-buckets and silently fails."
type: skill
---

# Modifier-Bound Date Column Skill

## When this skill applies

The question contains BOTH:
1. A state modifier on the entity being counted/measured: delivered, shipped, completed, cancelled, refunded, paid, approved, fulfilled, returned, signed, expired, granted, deployed
2. A temporal grouping or filter: "per month", "in 2018", "monthly volume", "by quarter", "by year", "in Q3"

Examples:
- "How many **delivered orders** are there **per month** in 2018?"
- "**Cancelled** orders **by quarter**"
- "**Paid** invoices **in 2017**"
- "Highest **shipped** volume **per month**"

## What goes wrong

There are typically two date columns in the same table:
- A generic creation/intake timestamp (`order_purchase_timestamp`, `created_at`, `signed_up_at`) that always exists for every row
- One or more state-transition timestamps (`order_delivered_customer_date`, `shipped_at`, `paid_at`) that only populate when the entity reaches that state

When the question asks for "**delivered** orders **per month**", grouping by `order_purchase_timestamp` answers a different question:

> "Of the orders that were eventually delivered, how many were *placed* in each month?"

That is not the same as:

> "How many orders *reached delivered status* in each month?"

The first counts orders by their birth month. The second counts state transitions in each month. Both contain the same total over the full lifetime, but their per-month distributions are dramatically different — purchases lead deliveries by days to weeks.

## Concrete example (real schema)

For a single 2016 month — same `order_status='delivered'` filter, only the date column differs:

| Bucketing column | 2016-09 | 2016-10 | 2016-11 | 2016-12 |
|---|---|---|---|---|
| `order_purchase_timestamp` | 1 | 265 | 0 | 1 |
| `order_delivered_customer_date` | 0 | 205 | 58 | 4 |

The October row alone differs by 60 — enough to flip "highest monthly volume" answers. Same data, same status filter, different date column → different answer.

## Procedure

1. **Read the question and write down two things separately**:
   - The state modifier: `delivered`
   - The temporal grouping: `per month`

2. **Probe the schema for date columns on the entity table** — there are usually several:
   ```sql
   PRAGMA table_info(orders);   -- SQLite
   -- or
   SELECT column_name FROM information_schema.columns
   WHERE table_name = 'orders' AND data_type IN ('timestamp', 'date');
   ```

3. **Identify the date column that corresponds to the modifier**, by name match:

   | Modifier in question | Likely date column |
   |---|---|
   | delivered | order_delivered_customer_date / delivered_at / shipped_received_at |
   | shipped | order_delivered_carrier_date / shipped_at |
   | paid | paid_at / payment_date |
   | cancelled | cancelled_at / order_cancellation_date |
   | refunded | refunded_at / refund_date |
   | approved | approved_at / approval_date |
   | completed | completed_at / closed_at |
   | signed up / registered | created_at / registered_at |

4. **Use that column for the temporal grouping**:
   ```sql
   SELECT strftime('%Y-%m', order_delivered_customer_date) AS ym, COUNT(*)
   FROM orders
   WHERE order_status = 'delivered'
     AND order_delivered_customer_date IS NOT NULL
     AND strftime('%Y', order_delivered_customer_date) = '2018'
   GROUP BY ym
   ```

   Notes:
   - Filter on the SAME date column you GROUP BY for the year predicate (`strftime('%Y', order_delivered_customer_date) = '2018'`), not on `order_purchase_timestamp`.
   - Add `IS NOT NULL` — state-transition columns are NULL for rows that never reached that state.

5. **Sanity-check by running BOTH bucketings side-by-side** and confirming they differ as expected — see the procedure above. If the results are identical, the schema may have only one date column and there is nothing to choose; otherwise the difference confirms you picked correctly when it matches what the modifier semantically means.

## Anti-patterns (these silently fail)

**A. Generic timestamp + status filter**
```sql
-- WRONG: counts purchase events whose order eventually reached delivered status
SELECT strftime('%Y-%m', order_purchase_timestamp), COUNT(*)
FROM orders WHERE order_status = 'delivered'
GROUP BY 1
```

**B. Year filter on one column, GROUP BY on another**
```sql
-- WRONG: 2018 boundary inconsistent — orders purchased Dec 2017 delivered Jan 2018 split incorrectly
WHERE strftime('%Y', order_purchase_timestamp) = '2018'
GROUP BY strftime('%Y-%m', order_delivered_customer_date)
```

**C. Forgetting `IS NOT NULL` on the state-transition column**
State-transition columns are NULL for rows that haven't reached that state. Without `IS NOT NULL`, NULL becomes its own bucket and skews counts (or some dialects coerce it to a date sentinel).

## Verification before saving

- [ ] Does the date column you GROUP BY share a semantic with the modifier (delivered → delivered_at)?
- [ ] Is the same column used in both the WHERE year/quarter filter and the GROUP BY?
- [ ] Did you add `IS NOT NULL` on the state-transition column?
- [ ] Have you confirmed by running both bucketings (purchase-based and delivered-based) that they differ — and your numbers match the *modifier's* bucketing?
