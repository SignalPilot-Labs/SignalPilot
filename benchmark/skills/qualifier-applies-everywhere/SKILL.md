---
name: qualifier-applies-everywhere
description: "Use this skill when the question contains a population qualifier like 'considering only X', 'for X only', 'X customers', 'X orders' that the answer should respect. Ensures the qualifier filter is applied in EVERY CTE that contributes to the final population, not just the top-level WHERE — silent population drift is the most common cause of values that look right but miss tolerance."
type: skill
---

# Qualifier-Applies-Everywhere Skill

## When this skill applies

The question contains a population-narrowing phrase the answer must respect:
- "considering only delivered orders"
- "for active customers"
- "of completed transactions"
- "shipped within 7 days"
- "subscribers who have at least one purchase"
- any "X orders / X users / X records" where X is an adjective (delivered, completed, qualified, primary)

## What goes wrong

The qualifier is applied to the LAST CTE (the one that names the metric) but not to upstream CTEs (the ones that compute scores, ranks, percentiles, or deduplications). Upstream CTEs see the un-filtered population, so:

- Quintile / percentile cutpoints shift (NTILE uses a different ordering)
- Rank windows include rows the answer should not see
- Per-customer aggregations include orders that should be excluded
- Recency / first / last calculations anchor on a row that should not exist

The result is a value that *looks* close but lands a few percent off — outside the evaluator's tolerance, with no syntactic error to find.

## Procedure

1. **Read the question once and underline every adjective that narrows the population.** The most common are: delivered, shipped, completed, cancelled, refunded, active, paid, qualified, primary, validated, granted, finalized.

2. **Write a one-line population predicate as a SQL comment, BEFORE writing CTEs**:
   ```sql
   -- POPULATION: WHERE order_status = 'delivered'
   ```

3. **For every CTE you write, the first thing that goes in the WHERE clause is the population predicate.** Not "I'll filter at the end" — at the top, every time:

   ```sql
   WITH RecencyScore AS (
     SELECT customer_id, NTILE(5) OVER (ORDER BY MAX(ts) DESC) AS r
     FROM orders
     WHERE order_status = 'delivered'   -- POPULATION
     GROUP BY customer_id
   ),
   FrequencyScore AS (
     SELECT customer_id, NTILE(5) OVER (ORDER BY COUNT(*) DESC) AS f
     FROM orders
     WHERE order_status = 'delivered'   -- POPULATION (same predicate)
     GROUP BY customer_id
   ),
   MonetaryScore AS (
     SELECT customer_id, NTILE(5) OVER (ORDER BY SUM(price) DESC) AS m
     FROM orders JOIN order_items USING (order_id)
     WHERE order_status = 'delivered'   -- POPULATION (same predicate)
     GROUP BY customer_id
   )
   ```

4. **If you factor the predicate into a base CTE that every other CTE reads from, the predicate only needs to live in one place** — but every downstream CTE must read from that base, not from the raw table:
   ```sql
   WITH base AS (
     SELECT * FROM orders WHERE order_status = 'delivered'
   ),
   recency AS (SELECT ... FROM base GROUP BY customer_id),
   frequency AS (SELECT ... FROM base GROUP BY customer_id)
   ```
   This is the safer pattern for multi-CTE pipelines.

## Anti-patterns (these silently fail)

**A. Filter only at the final aggregate**
```sql
-- WRONG: scores computed on full universe, filter applied last
WITH scores AS (SELECT customer_id, NTILE(5) OVER (...) FROM orders ...)
SELECT bucket, AVG(metric)
FROM scores JOIN orders USING (customer_id)
WHERE order_status = 'delivered'
GROUP BY bucket
```

**B. Filter in some CTEs but not others**
```sql
-- WRONG: recency filtered, monetary not — scores shift relative to each other
WITH recency AS (SELECT ... FROM orders WHERE order_status='delivered' ...),
     monetary AS (SELECT ... FROM orders JOIN order_items ... GROUP BY customer_id)
```

**C. Filter at the JOIN to a dimension instead of the fact**
```sql
-- WRONG: dim CTE filters status, fact CTE doesn't
WITH delivered_customers AS (SELECT DISTINCT customer_id FROM orders WHERE status='delivered')
SELECT c.id, AVG(price) FROM customers c JOIN orders o ON ... JOIN delivered_customers dc ...
```
The fact aggregation still includes non-delivered orders for delivered customers.

## Verification before saving

- [ ] Does every CTE that touches the fact table carry the same population predicate (or read from a base CTE that does)?
- [ ] If the question says "considering only X", grep your SQL for the predicate — is it in every CTE that GROUPs or RANKs or NTILEs the entity?
- [ ] If you removed the population predicate from one CTE, would the row count change? If the answer is "I don't know," apply it.
- [ ] Run the SQL with the predicate and without it; if the final values differ, that's expected — the predicate matters; do NOT submit the unfiltered version.
