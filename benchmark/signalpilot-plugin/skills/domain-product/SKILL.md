---
name: domain-product
description: "Product analytics rules: calendar spine cross-joins, date boundary caps, event type pivoting, first-run NULL behavior."
---

# Product Analytics

## Driving Table

When aggregating usage or event metrics, drive FROM the fact/event table (events, sessions, pageviews), not the dimension table (users, features, pages). Users with zero activity MUST NOT appear in activity reports - they have no data to aggregate.

## Calendar Spine Cross-Joins

Daily metrics models that cross-join a calendar spine with entities (users, features, pages) MUST cap the join at `current_date` - generating rows beyond today produces phantom future rows with zero metrics that inflate row counts.

If the YML description says "from creation date to current date," add `AND spine.date_day >= entity.created_at::date AND spine.date_day <= current_date` to the join condition - both bounds are required.

NEVER cross-join without a date cap - unbounded spines grow indefinitely and break row count expectations.

When an entity has a `created_at` or equivalent timestamp, the spine MUST start from that date, not from the earliest date in the spine - starting earlier produces rows before the entity existed.

## Event Type Pivoting

When an events table has a `type` or `event_name` column, pivot distinct values into separate metric columns - each event type becomes a `count_<type>` column in the output.

Do NOT filter the events table to a single type before pivoting - all types must appear in the output as separate columns, using conditional aggregation (`COUNT(CASE WHEN type = 'x' THEN 1 END)`).

Read the YML or a sibling model to confirm the exact set of event types expected - inventing column names from partial data causes schema mismatches.

## First-Run Behavior

On first build with no prior state, rolling window columns (7-day avg, 30-day sum) MUST be NULL for the first N-1 periods - this is correct behavior, not a bug.

Do NOT substitute 0 for NULL in rolling window columns - NULL means "insufficient history," 0 means "activity was zero."

Period-over-period columns follow the same rule: NULL on first build. See dbt-workflow "Incremental Models and Period-Over-Period Columns" for the full rule.
