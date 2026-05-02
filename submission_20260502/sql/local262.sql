-- INTERPRETATION: Find problems where the count of (name, version, step) combos
-- (steps 1-3) where any non-"Stack" model's MAX test_score < "Stack" model's
-- test_score EXCEEDS the count of times that problem appears in the solution table.
-- EXPECTED: ~7 rows

WITH scores AS (
  SELECT
    name, version, step,
    MAX(CASE WHEN model = 'Stack' THEN test_score END) AS stack_score,
    MAX(CASE WHEN model != 'Stack' THEN test_score END) AS max_non_stack_score
  FROM model_score
  WHERE step IN (1, 2, 3)
  GROUP BY name, version, step
),
qualifying AS (
  SELECT name, COUNT(*) AS qualifying_count
  FROM scores
  WHERE max_non_stack_score < stack_score
  GROUP BY name
),
sol_counts AS (
  SELECT name, COUNT(*) AS solution_count
  FROM solution
  GROUP BY name
)
SELECT q.name, q.qualifying_count, s.solution_count
FROM qualifying q
JOIN sol_counts s ON q.name = s.name
WHERE q.qualifying_count > s.solution_count
ORDER BY q.name;
