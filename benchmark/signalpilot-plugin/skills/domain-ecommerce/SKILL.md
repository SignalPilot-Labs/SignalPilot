---
name: domain-ecommerce
description: "E-commerce domain knowledge: transaction lifecycle, driving tables, status filtering."
---

# E-Commerce Domain Knowledge

## WARNING: Return Filtering

BEFORE writing any purchase or revenue metric, check: does a separate
returns *source* table exist? A "separate returns table" means a distinct
raw source table (not a dbt model or ref) that records returns independently.
A downstream dbt model like `lost_revenue` that aggregates returns FROM the
same fact table is NOT a separate returns table.

**IF YES** (a raw source table for returns exists, separate from the main
fact table) - the main fact table records only sales. Do NOT add a return
filter. Filtering drops valid sales rows that are tracked in the other table.

**IF NO** (returns are rows in the same fact table via a status/flag column,
even if a dbt model aggregates those returns separately) - Exclude them
with `WHERE status_col NOT IN (...)` BEFORE any GROUP BY. Use WHERE, not
CASE WHEN - CASE WHEN zeroes out return rows but keeps return-only entities
in the output with fake purchase_total=0. A customer who bought 5 items
and returned 3 made 2 purchases - not 5.

## Driving Table

When a model computes metrics by aggregating a fact table (SUM, COUNT, AVG on transactions), the fact aggregation MUST be the FROM clause - driving from the dimension table and LEFT JOINing facts produces rows for entities with zero activity, inflating row counts with NULL or zero metrics.

LEFT JOIN the dimension table onto the fact aggregation for enrichment (names, addresses). The dimension does NOT control which entities appear - the fact table does. If a customer has no qualifying rows in the fact table after status filtering, that customer has no data to report and MUST NOT appear in the output.

**Exception - calendar-spine models (daily/weekly/monthly reports):**
When a model CROSS JOINs a date spine with a shop/entity, the date spine
drives the FROM clause - NOT the fact table. Days with zero activity MUST
appear in the output with metric columns COALESCE'd to 0. This is the
opposite of the fact-drives rule above. The calendar ensures every date
appears regardless of whether transactions occurred. Identify calendar-spine
models by: CROSS JOIN with a date/calendar table, or YML description
mentioning "daily", "weekly", or "per day."

## Transaction Lifecycle

An order moves through stages. Not every row in a transaction table is a completed sale:

1. **Placed** → customer submits an order
2. **Authorized** → payment is approved but not yet captured
3. **Fulfilled / Shipped / Delivered** → goods sent or received - this is revenue
4. **Returned** → customer sends goods back - this offsets revenue
5. **Refunded** → money returned to customer - this offsets revenue
6. **Cancelled / Voided** → order was abandoned or reversed before fulfillment - not revenue

A fact table may contain rows from ALL of these stages. Only fulfilled/delivered rows count as revenue. Returns and refunds are separate metrics. Cancelled orders are neither.

## Revenue Metrics MUST Exclude Non-Sale Events

A purchase or revenue total counts ONLY completed sales. Returned, refunded, and cancelled items are NOT revenue - they are reversals or abandonments. If a transaction table has a status/flag column, revenue metrics MUST exclude these negative event types.

BEFORE writing any SUM for a revenue metric, run `SELECT DISTINCT <status_col>` on the table in your FROM clause - not its raw source (intermediate models rename columns). Find which values represent returns, refunds, or cancellations from sibling models or existing WHERE clauses. Then exclude them with `WHERE status_col NOT IN (...)`. Keep ALL other values - they are valid sales regardless of what their codes mean.

## Customer Health Scoring

When categorizing entities into health tiers (green/yellow/orange/red, good/fair/poor, A/B/C/D), use equal-width percentage bands unless the YML description specifies different thresholds - guessing custom breakpoints from data distributions produces arbitrary boundaries that vary between runs. For a 0-100% range with 4 tiers: 0-25%, 25-50%, 50-75%, 75-100%.

If a computed metric exceeds 100% (e.g., returns exceed purchases), that entity is an anomaly. Set its category to NULL - it does not belong in any defined tier.

## Common Traps

1. **Guessing the purchase value**: Status columns often have codes or abbreviations. If you only include the one value you THINK means "purchase," you miss other valid purchase states. Exclude the known negative values instead.
2. **No filter at all**: Summing all rows mixes purchases + returns + cancellations. Return-only customers appear in purchase reports with fake amounts.
3. **CASE WHEN instead of WHERE**: Zeroing out return rows with CASE WHEN keeps return-only entities in the GROUP BY with purchase_total=0. Use WHERE to exclude them from the FROM entirely.
