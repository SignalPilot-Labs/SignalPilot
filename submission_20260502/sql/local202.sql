-- INTERPRETATION: Among the top 10 states by alien population, count how many have
-- pct of friendly aliens (aggressive=0) > pct of hostile aliens (aggressive=1)
-- AND average alien age > 200.
-- EXPECTED: 1 row (a single count)

WITH top10_states AS (
    SELECT state, COUNT(*) AS alien_population
    FROM alien_data
    GROUP BY state
    ORDER BY alien_population DESC
    LIMIT 10
),
state_stats AS (
    SELECT
        a.state,
        COUNT(*) AS total,
        SUM(CASE WHEN a.aggressive = 0 THEN 1 ELSE 0 END) AS friendly_count,
        SUM(CASE WHEN a.aggressive = 1 THEN 1 ELSE 0 END) AS hostile_count,
        CAST(SUM(CASE WHEN a.aggressive = 0 THEN 1 ELSE 0 END) AS REAL) / COUNT(*) AS pct_friendly,
        CAST(SUM(CASE WHEN a.aggressive = 1 THEN 1 ELSE 0 END) AS REAL) / COUNT(*) AS pct_hostile,
        AVG(a.age) AS avg_age
    FROM alien_data a
    JOIN top10_states t ON a.state = t.state
    GROUP BY a.state
)
SELECT COUNT(*) AS qualifying_state_count
FROM state_stats
WHERE pct_friendly > pct_hostile
  AND avg_age > 200;
