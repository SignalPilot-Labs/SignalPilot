-- INTERPRETATION: Find which L1_model appears most frequently when combining
-- traditional models (model table) and Stack model (stack_ok table)
-- EXPECTED: 1 row (the most frequent category)

SELECT L1_model, COUNT(*) AS total_count
FROM (
    SELECT L1_model FROM model
    UNION ALL
    SELECT L1_model FROM stack_ok
)
GROUP BY L1_model
ORDER BY total_count DESC
LIMIT 1;
