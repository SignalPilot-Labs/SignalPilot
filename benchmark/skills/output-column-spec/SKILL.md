---
name: output-column-spec
description: "Use this skill at the very start of EVERY task, before writing any SQL. Forces the agent to enumerate every output column the question implies — entities, identifiers, metrics, period breakdowns, classifications — so the SQL is written to produce all required columns instead of only the ones that come to mind first."
type: skill
---

# Output Column Spec Skill

## When this skill applies

**Always.** Before writing any SQL for any task. Run this first.

The single most common failure mode in SQL benchmark tasks is "the answer is correct but a column is missing." This skill prevents that by forcing explicit enumeration before any code is written.

## What this skill does

You write a SQL comment block that lists every output column the question implies, in the order they should appear, with a one-line semantic for each. You commit to this spec BEFORE writing the SQL, so the SELECT clause gets built to match.

## Procedure

Read the question slowly. Then in your scratch SQL, write:

```sql
-- ========== OUTPUT COLUMN SPEC ==========
-- For each <entity-noun> the question names, list:
--   1. <entity_id>          : the natural primary key
--   2. <entity_name>        : the descriptive label
-- For each metric/measure the question names, list:
--   3. <metric_1>           : <one line semantic>
--   4. <metric_2>           : <one line semantic>
-- For any time period, classification, rank, or breakdown, list:
--   5. <period or rank>     : <one line semantic>
-- ========================================
```

## Enumeration prompts (work through ALL of these before writing SQL)

For each question, scan for:

### 1. Entities
- What kind of thing is the question about? (customer, product, region, …)
- For each entity, do I need both an ID column AND a name/title column?
- Has the question said "list", "for each", "by", "per", "top N"? → likely yes to both

### 2. Metrics / Computed values
For each numeric/aggregate adjective in the question, add a column:
- "average X" → avg_x
- "total X" / "sum of X" → total_x
- "count of X" / "how many X" → x_count or count_x
- "share of X" / "% of X" → share_x or pct_x
- "rate of X" → rate_x
- "ratio of X to Y" → x_to_y_ratio

### 3. Modifier-bound metrics (the trap)
If the metric has a qualifier in the question, the qualifier MUST be in the column:
- "missed rounds" → missed_rounds (not rounds)
- "delivered orders" → delivered_orders
- "refunded amount" → refunded_amount
- "active users" → active_users
- "first attempt" → first_attempt_X
- "highest <unit>" → highest_<unit>
- "best performing" → best_X

### 3a. Trailing connectors attach an EXTRA metric (the second-metric trap)
A small set of phrases attach a *second* metric onto a question that's already named one. Each one introduces an additional output column you must compute:

- "**along with** their X" → add column for X
- "**and (also) their** X" → add column for X
- "**as well as** X" → add column for X
- "**together with** X" → add column for X
- "**including** X" → add column for X (when X is a metric, not a row filter)
- "**plus** X" → add column for X
- "**, showing** X" / "**, displaying** X" → add column for X
- "**and provide** X" / "**and report** X" → add column for X

These connectors are easy to miss because the sentence already has a primary metric and the second one feels like commentary. It isn't — it's a required column. The second metric usually has a *different formula* than the first (e.g., "top 5 X by avg runs per match, **along with their batting averages**" — `avg runs per match` and `batting average` are computed differently).

When you see one of these connectors, treat what follows as a new line in the OUTPUT COLUMN SPEC, with its own semantic.

### 4. Time periods (when the question compares)
If the question names two or more periods (e.g., "2019 and 2020", "before and after"):
- Add a column for each period's value, named for the period:
  `value_2019, value_2020, change` — not just `change`
- Pivot (wide form) is usually the right shape if periods are named.

### 5. Classification / ranking / position
- "top N", "ranked", "1st/2nd/3rd" → add a `rank` or `position` column
- "tier", "grade", "quintile", "category" → add BOTH the numeric score AND the label

### 6. Roll-up / overall
- "by X with overall", "compared to total", "vs the average" → include the overall figure as an extra row OR column

## After enumeration

Now look at your spec. **For each column, can you point at the SQL clause that produces it?** If you can't, the SQL is missing something.

Only AFTER the spec is written do you proceed to schema discovery and SQL writing.

## Anti-pattern

Writing the SQL first and then realizing at save time that the question asked for "average <metric> per <entity>" but you only output entity names. By that point the agent has spent turns and is reluctant to redo the query. The skill prevents that by enumerating up front.

## Verification

Just before saving result.csv, walk through the spec one more time and confirm:
- [ ] Every spec column corresponds to a column in result.csv
- [ ] Every result.csv column corresponds to something the spec named
- [ ] Modifier-bound metrics actually filter by the modifier (missed/delivered/etc.)
- [ ] If you have entity_id, you have entity_name (and vice versa)

If anything is missing, fix the SQL before saving. Do not save and hope.
