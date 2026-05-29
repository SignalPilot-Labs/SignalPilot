---
name: domain-hr
description: "HR & operations rules: SCD current-record filtering, issue resolution metrics."
---

# HR & Operations

## Driving Table

When aggregating workforce or issue metrics, drive FROM the fact/event table (issues, tickets, time_entries), not the dimension table (employees, teams, projects). Employees with zero activity MUST NOT appear in activity reports - they have no data to aggregate.

Exception: if a parent/entity table exists whose primary key matches the
GROUP BY key AND some parent rows have no matching children in the detail
table, drive FROM the parent and LEFT JOIN the detail. Parent rows with
zero children must appear with count=0, not be silently dropped.

## SCD (Slowly Changing Dimensions)

Tables with `_fivetran_start`/`_fivetran_end` or `valid_from`/`valid_to` columns track historical state. You MUST filter to the current record before aggregating.

Current record: `_fivetran_end = '9999-12-31'` OR `_fivetran_end IS NULL` - verify the sentinel value by querying 3-5 rows before assuming.

For `_fivetran_active` columns, always use `WHERE COALESCE(_fivetran_active, true)` - never `WHERE _fivetran_active = true` because NULL values (meaning "active") would be filtered out.

NEVER aggregate across all historical rows without filtering to current records first - doing so double-counts entities that changed state.

## Issue Resolution Metrics

Include ONLY closed issues in resolution time calculations - open issues have no close timestamp.

NEVER substitute `current_date` for a missing close timestamp - this produces artificially inflated resolution times that corrupt the metric.
