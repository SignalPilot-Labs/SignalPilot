---
name: avg-of-avgs-vs-pooled
description: "Use this skill when the question asks for an aggregate-of-aggregates ('average of player averages by country', 'mean per-customer mean', 'avg quarterly avg sales by region'). The two natural interpretations — pooled (sum of children / count of children) and avg-of-avgs (mean of per-entity means) — produce different numbers whenever group sizes differ. Pick the form the question literally describes; do NOT pool when the question says 'average of averages'."
type: skill
---

# Average-of-Averages vs Pooled-Mean Skill

## When this skill applies

The question chains two aggregation levels:
- "the average of each X's average Y"
- "average per-customer monthly spend, then averaged by region"
- "the country's batting average, computed as the average of player batting averages"
- "mean per-store sales, averaged across the chain"

A single sentence is enough — wherever you see the word "average" or "mean" applied twice (once at the inner entity, once at the outer group), you are in this skill's territory.

## The two forms diverge

For an outer group containing entities with sizes `n_1, n_2, …` and entity-level totals `s_1, s_2, …`:

- **Pooled mean** (also called weighted mean): `Σs_i / Σn_i` — every individual data point counts equally.
- **Average of averages**: `Σ(s_i / n_i) / k` — every entity counts equally, regardless of size.

When entity sizes differ, the two values are different. Example:
- Player A: 100 runs over 2 matches → avg 50.00
- Player B: 90 runs over 9 matches → avg 10.00
- Pooled (country): 190 / 11 = **17.27**
- Avg-of-avgs (country): (50 + 10) / 2 = **30.00**

If the question says "average of player averages", returning 17.27 is wrong even though it looks reasonable.

## Reading the question

These phrases mean **avg-of-avgs**:
- "**average of** the [entity]-level **averages**"
- "the [entity]'s **average X**, **averaged** across [groups]"
- "**country batting average** (computed as the average of player averages)"
- "**mean per-X mean** of Y"

These phrases mean **pooled / weighted**:
- "**average X across all [individuals]**" (with no per-entity layer in between)
- "**total X / total Y**"
- "**overall average** X"
- "**combined average**"

When the question is ambiguous, the deciding clue is whether it names the inner entity ("each player's", "per-customer", "per-store") — naming the entity is what makes the inner average a real aggregation step, which is what makes the outer aggregation an avg-of-avgs.

## Domain-specific denominator subset

Even after you pick the right outer form, the **inner average's denominator may need a domain-specific subset**:

| Domain | "Average X per Y" — common subset for Y |
|---|---|
| Cricket batting | `runs / dismissals` (or `/ innings batted`) — *not* `/ matches appeared` |
| Baseball batting | `hits / at-bats` — *not* `/ games played` |
| E-commerce conversion | `purchases / unique visitors` — *not* `/ events` |
| Customer retention | `actives / period-cohort starts` — *not* `/ all-time signups` |
| Ad CTR | `clicks / impressions` — *not* `/ pageviews` |

When the question uses a domain term ("batting average", "conversion rate", "retention"), do NOT compute it as the literal English math; look up the term's domain definition and confirm it against a known datapoint before using.

## SQL pattern (avg-of-avgs)

```sql
WITH per_entity AS (
  SELECT
    group_id, group_name,
    entity_id,
    -- inner aggregate, with the domain-correct denominator
    SUM(metric_numerator) * 1.0 / SUM(metric_denominator) AS entity_metric
  FROM facts
  WHERE <population_predicate>
  GROUP BY group_id, group_name, entity_id
)
SELECT
  group_id,
  group_name,
  AVG(entity_metric) AS group_avg_of_entity_avgs
FROM per_entity
GROUP BY group_id, group_name
ORDER BY group_avg_of_entity_avgs DESC
LIMIT N;
```

## SQL pattern (pooled)

```sql
SELECT
  group_id, group_name,
  SUM(metric_numerator) * 1.0 / SUM(metric_denominator) AS group_pooled_metric
FROM facts
WHERE <population_predicate>
GROUP BY group_id, group_name;
```

The pooled form has no inner CTE — that absence is the structural giveaway that you are pooling, not averaging averages.

## Anti-patterns (these silently fail)

**A. Pool when the question says avg-of-avgs**
The numbers are pulled toward high-volume entities — values look "reasonable" but tilt heavily.

**B. Avg-of-avgs when the question says pooled**
Small entities punch above their weight; the result has higher variance and biases toward outliers.

**C. Right outer form, wrong inner denominator**
Computed `runs/matches_appeared` instead of `runs/innings_batted`. The shape is right but the values shift on every player who played without batting (substitutes, late entrants).

**D. Including entities the question excludes from the denominator**
"Average matches per player" — does that include players with zero matches? Unless the question implies it, no. Pre-filter to entities with ≥1 of the thing being averaged.

## Verification before saving

- [ ] Re-read the question. Is there an inner entity ("each player", "per-customer") between the two aggregation words? If yes, the form is avg-of-avgs.
- [ ] Did you write a `per_entity` CTE that produces one row per inner entity, then aggregate that?
- [ ] Is the inner denominator the domain-correct subset (e.g., dismissals for batting average), not the easy column (matches played)?
- [ ] Pick one outer group, hand-compute both forms on its members, and confirm your SQL produces the avg-of-avgs value, not the pooled value.
