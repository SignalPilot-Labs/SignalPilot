---
name: ranking-with-position
description: "Use this skill when the question asks for top-N, ranked, highest, lowest, ordered by, or '1st/2nd/3rd' results. Ensures the result includes an explicit numeric rank/position column, handles ties correctly, and uses the right window function for the desired tie behavior."
type: skill
---

# Ranking-with-Position Skill

## When this skill applies

The question implies an ordered top-N output:
- "top 3 X by Y"
- "highest/lowest N entities"
- "ranked by"
- "in order of"
- "1st, 2nd, 3rd place"
- "the leading/trailing N"

## Required output columns

The result MUST contain an explicit numeric `rank` (or `position`) column. Implicit row order in the CSV is NOT a substitute — a reviewer can't verify "this is rank 3 because it's the 3rd row written" without an explicit column.

```
rank, entity_id, entity_name, metric
1,    A100,      Alice,       95.0
2,    B200,      Bob,         92.5
3,    C300,      Carol,       88.0
```

## Tie handling — pick the right window function

| Function | Behavior on ties | When to use |
|---|---|---|
| `ROW_NUMBER()` | Distinct ranks 1,2,3 even if tied | Use when "top N" means *exactly N rows* |
| `RANK()` | Tied rows share rank, gaps after (1,1,3) | Use when "top N" means "in the top N tier, including ties" |
| `DENSE_RANK()` | Tied rows share rank, no gaps (1,1,2) | Use when ranks are categorical labels |

If the question doesn't disambiguate, prefer `DENSE_RANK()` and document the choice in a SQL comment.

## SQL patterns

### Top N globally
```sql
WITH ranked AS (
    SELECT
        entity_id,
        entity_name,
        metric,
        DENSE_RANK() OVER (ORDER BY metric DESC) AS rnk
    FROM ...
)
SELECT rnk AS rank, entity_id, entity_name, metric
FROM ranked
WHERE rnk <= N
ORDER BY rnk, entity_id
```

### Top N within each group ("top 3 X for each Y")
```sql
WITH ranked AS (
    SELECT
        group_id, group_name,
        entity_id, entity_name,
        metric,
        DENSE_RANK() OVER (PARTITION BY group_id ORDER BY metric DESC) AS rnk
    FROM ...
)
SELECT group_id, group_name, rnk AS rank, entity_id, entity_name, metric
FROM ranked
WHERE rnk <= 3
ORDER BY group_id, rnk, entity_id
```

## Anti-patterns (these fail)

**A. No rank column, only ORDER BY**
```sql
SELECT entity_id, entity_name, metric
FROM ...
ORDER BY metric DESC
LIMIT 3
```
The CSV has no `rank` column — reviewer can't verify position.

**B. LIMIT instead of window — wrong on ties**
```sql
SELECT * FROM (... ORDER BY metric DESC LIMIT 3)
```
If rank 3 is tied with rank 4, only one of them gets returned arbitrarily.

**C. Top-N within group via correlated subquery (often slow + buggy)**
Use a window function instead.

## Verification before saving

- [ ] Is there a column literally named `rank`, `position`, `rnk`, `place`, or similar?
- [ ] Does that column contain integer values starting at 1?
- [ ] If "top N", do values stay ≤ N? (Or ≤ N tiers if using DENSE_RANK?)
- [ ] If grouped top-N, does each group's ranks restart at 1?
- [ ] Are ties handled the way the question implies?
