---
name: entity-with-metrics
description: "Use this skill when the question asks for properties OR metrics 'for each X', 'per X', 'by X', or 'list of X' (e.g., 'for each director, the average rating', 'per customer, total spend'). Ensures the result includes the entity's ID column, name/title column, AND every metric the question explicitly mentions."
type: skill
---

# Entity-with-Metrics Skill

## When this skill applies

Any question of the form "for each <entity>, return <metrics>":
- "For each customer, total spend and order count"
- "Per director, the average movie rating and total votes"
- "List of products with their share of revenue"
- "By region, monthly sales and growth rate"

## Required output columns

For each entity asked about, the result MUST include:

1. **Entity identifier** — the natural primary key (e.g., `*_id`, `*_key`, `*_code`)
2. **Entity name/title/label** — the descriptive column a human can read
3. **Every metric the question explicitly names** — each as its own column

Skipping any of these three is the most common failure mode for "for each X" questions.

### Examples (generic)

| Question phrase | Required columns |
|---|---|
| "average rating per director" | director_id, director_name, avg_rating |
| "for each customer, total spend and order count" | customer_id, customer_name, total_spend, order_count |
| "list each product with share of revenue" | product_id, product_name, share_revenue |

## Anti-patterns (these fail)

**A. Name column missing**
```
director_id, avg_rating         ← reviewer can't tell which director
```

**B. ID column missing**
```
director_name, avg_rating       ← reviewer can't disambiguate same-name entities
```

**C. Metric column missing — only entity returned**
```
director_id, director_name      ← question asked for avg_rating, where is it?
```

**D. Metric collapsed into the row order rather than a column**
```
director_id, director_name      ← rows ordered by avg_rating but no avg_rating column
```

## SQL pattern

```sql
SELECT
    e.entity_id,
    e.entity_name,
    <agg_expr_1> AS metric_1,
    <agg_expr_2> AS metric_2
FROM entity_table e
LEFT JOIN fact_table f ON f.entity_id = e.entity_id
WHERE <conditions>
GROUP BY e.entity_id, e.entity_name
ORDER BY metric_1 DESC
```

## Fan-out check

If the entity table has a one-to-many relationship to another joined table, AVG/COUNT can be inflated. Pre-aggregate before joining:

```sql
WITH entity_stats AS (
    SELECT entity_id, AVG(metric) AS avg_metric
    FROM fact_table
    GROUP BY entity_id
)
SELECT e.entity_id, e.entity_name, s.avg_metric
FROM entity_table e
JOIN entity_stats s ON s.entity_id = e.entity_id
```

## Verification before saving

For each metric mentioned in the question, point at the column in the result that holds it:
- [ ] "average X" → there's a column for AVG of X
- [ ] "total X" → there's a column for SUM of X
- [ ] "count of X" → there's a column for COUNT of X
- [ ] "share of X" → there's a column for X / SUM(X) over the population
- [ ] "rate of X" → there's a column for X numerator / Y denominator

If you can't point at a column for any metric the question names, add it.
