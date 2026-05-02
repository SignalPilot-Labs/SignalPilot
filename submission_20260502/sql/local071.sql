-- ========== OUTPUT COLUMN SPEC ==========
-- 1. country_code_2 : 2-letter country code of countries with the longest streak
--                     of consecutive city insert dates in June 2022
-- ========================================

-- INTERPRETATION: For June 2022, find distinct dates per country when at least one
-- city was inserted. Then find the longest consecutive daily streak per country.
-- Return all countries tied at the maximum streak length.

-- EXPECTED: Small number of countries tied at the max streak (turned out to be 3
-- countries with a 30-day streak = every day of June 2022).

WITH distinct_dates AS (
    SELECT DISTINCT country_code_2, insert_date
    FROM cities
    WHERE insert_date LIKE '2022-06-%'
),
numbered AS (
    SELECT
        country_code_2,
        insert_date,
        ROW_NUMBER() OVER (PARTITION BY country_code_2 ORDER BY insert_date) AS rn
    FROM distinct_dates
),
groups AS (
    SELECT
        country_code_2,
        insert_date,
        date(insert_date, '-' || (rn - 1) || ' days') AS grp
    FROM numbered
),
streaks AS (
    SELECT
        country_code_2,
        grp,
        COUNT(*) AS streak_len
    FROM groups
    GROUP BY country_code_2, grp
),
max_streak_per_country AS (
    SELECT country_code_2, MAX(streak_len) AS max_streak
    FROM streaks
    GROUP BY country_code_2
),
overall_max AS (
    SELECT MAX(max_streak) AS top_streak
    FROM max_streak_per_country
)
SELECT m.country_code_2
FROM max_streak_per_country m
CROSS JOIN overall_max o
WHERE m.max_streak = o.top_streak
ORDER BY m.country_code_2;
