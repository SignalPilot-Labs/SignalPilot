-- ========== OUTPUT COLUMN SPEC ==========
-- 1. start_year  : the movie release year that starts the 10-year window (from distinct years in data)
-- 2. film_count  : number of films released in [start_year, start_year+9] inclusive
-- ========================================
-- INTERPRETATION: For each unique release year Y in the data, count all films released
-- in years Y through Y+9. Return the single Y with the highest count.
-- EXPECTED: 1 row

WITH parsed AS (
    SELECT CAST(substr(trim(year), -4) AS INTEGER) AS release_year
    FROM Movie
    WHERE year IS NOT NULL
      AND CAST(substr(trim(year), -4) AS INTEGER) BETWEEN 1000 AND 9999
),
unique_years AS (
    SELECT DISTINCT release_year AS start_year FROM parsed
),
period_counts AS (
    SELECT
        u.start_year,
        COUNT(*) AS film_count
    FROM unique_years u
    JOIN parsed p ON p.release_year BETWEEN u.start_year AND u.start_year + 9
    GROUP BY u.start_year
)
SELECT start_year, film_count
FROM period_counts
ORDER BY film_count DESC
LIMIT 1;
