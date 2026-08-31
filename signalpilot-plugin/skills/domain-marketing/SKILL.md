---
name: domain-marketing
description: "Marketing domain knowledge: attribution models, engagement funnel order."
---

# Marketing Domain Knowledge

## Driving Table

When aggregating engagement or spend metrics, drive FROM the event/activity
table (messages, clicks, impressions), not the dimension table (contacts,
accounts, campaigns). Contacts with zero engagements MUST NOT appear in
engagement reports - they have no data to aggregate.

**Exception - reports that JOIN two aggregations by a shared dimension:**
When a report groups metrics from multiple sources BY the same dimension
(e.g., cost-per-acquisition by channel), the source with the MOST distinct
values of that dimension defines the output population - INNER JOIN would
silently drop dimension values that exist in one source but not the other.
LEFT JOIN the smaller source onto the larger one. Dimension values without
matching data in the smaller source get NULL metrics.

## Attribution Models

Attribution models split conversion credit across touchpoints. Implement the model the task or YML description specifies:

- **First-touch**: 100% credit to the first touchpoint
- **Last-touch**: 100% credit to the last touchpoint
- **Linear**: equal share (1 / count of touches per conversion)
- **40-20-40**: 40% first, 40% last, 20% split equally among middle touches

When a conversion has only one touchpoint, first-touch and last-touch are the same row - do NOT double-count credit.

## Engagement Funnel Order

Standard funnel: sent → delivered → opened → clicked → bounced. Each stage is a COUNT of events, not COUNT DISTINCT of recipients.

Do NOT deduplicate across funnel stages - one email opened 3 times is 3 open events.

## Spend and Cost Sign Convention

Many API connectors (messaging, ads, telephony) store costs as negative
values (representing money leaving the account). Before writing `SUM(price)`
into a metric column, query `SELECT MIN(price), MAX(price)` on EACH source
table that contributes monetary values.

**Single-source model**: If the model reads monetary values from ONE source
only, preserve that source's sign convention. Do NOT apply `ABS()` - the
raw sign is the source of truth.

**Multi-source model**: If the model JOINs multiple tables that contain
monetary columns, check the sign of EACH monetary source with
`SELECT MIN(price), MAX(price)`. If any two sources use different sign
conventions, normalize ALL monetary columns in the model to positive with
`ABS()` - including columns that come from a single CTE. Mixing positive
and negative conventions within one model produces misleading totals and
breaks comparisons between columns.
