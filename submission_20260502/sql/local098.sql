-- ========== OUTPUT COLUMN SPEC ==========
-- 1. actor_count : count of actors who never had a four-year span without a film credit
-- ========================================

-- INTERPRETATION: For each actor (PID in M_Cast), get distinct film years.
-- A "bad gap" is when consecutive film years differ by >= 5 (meaning 4+ empty years in between).
-- Count actors with NO bad gap.

WITH actor_years AS (
    SELECT DISTINCT mc.PID, m.year
    FROM M_Cast mc
    JOIN Movie m ON mc.MID = m.MID
    WHERE m.year IS NOT NULL
),
year_gaps AS (
    SELECT
        PID,
        year - LAG(year) OVER (PARTITION BY PID ORDER BY year) AS gap
    FROM actor_years
),
actors_with_bad_gap AS (
    SELECT DISTINCT PID
    FROM year_gaps
    WHERE gap >= 5
),
all_actors AS (
    SELECT DISTINCT PID FROM actor_years
)
SELECT COUNT(*) AS actor_count
FROM all_actors
WHERE PID NOT IN (SELECT PID FROM actors_with_bad_gap)
