-- ========== OUTPUT COLUMN SPEC ==========
-- 1. year  : the F1 season year
-- 2. total : sum of (max driver season points) + (max constructor season points) for that year
-- ========================================

-- INTERPRETATION: Find the 3 years where the combined maximum (best driver total points +
-- best constructor total points, both summed from the results table) is smallest.
-- Points are aggregated from the results table; races table joined only to get the year.
-- EXPECTED: 3 rows, ordered by total ascending

WITH driver_year_points AS (
    SELECT r.year, res.driver_id, SUM(res.points) AS driver_points
    FROM results res
    JOIN races r ON res.race_id = r.race_id
    GROUP BY r.year, res.driver_id
),
max_driver_per_year AS (
    SELECT year, MAX(driver_points) AS max_driver_points
    FROM driver_year_points
    GROUP BY year
),
constructor_year_points AS (
    SELECT r.year, res.constructor_id, SUM(res.points) AS constructor_points
    FROM results res
    JOIN races r ON res.race_id = r.race_id
    GROUP BY r.year, res.constructor_id
),
max_constructor_per_year AS (
    SELECT year, MAX(constructor_points) AS max_constructor_points
    FROM constructor_year_points
    GROUP BY year
),
yearly_totals AS (
    SELECT d.year,
           d.max_driver_points + c.max_constructor_points AS total
    FROM max_driver_per_year d
    JOIN max_constructor_per_year c ON d.year = c.year
)
SELECT year, total
FROM yearly_totals
ORDER BY total ASC
LIMIT 3;
