-- ========== OUTPUT COLUMN SPEC ==========
-- 1. year          : integer year extracted from last 4 chars of Movie.year
-- 2. total_movies  : total count of movies in that year (from Movie table)
-- 3. percentage    : % of movies with exclusively female cast (no Male/None gender actors)
-- ========================================

-- INTERPRETATION: For each year, find the % of movies whose entire cast is female
-- (has at least one female actor AND zero actors with Male or None gender).
-- Note: M_Cast.PID has a leading space, so TRIM() is required for the join.

WITH movie_years AS (
    SELECT MID, CAST(substr(year, -4) AS INTEGER) AS yr FROM Movie
),
movies_with_non_female AS (
    SELECT DISTINCT mc.MID FROM M_Cast mc
    JOIN Person p ON TRIM(mc.PID) = p.PID
    WHERE p.Gender IN ('Male', 'None')
),
movies_with_female AS (
    SELECT DISTINCT mc.MID FROM M_Cast mc
    JOIN Person p ON TRIM(mc.PID) = p.PID
    WHERE p.Gender = 'Female'
),
exclusively_female AS (
    SELECT MID FROM movies_with_female
    WHERE MID NOT IN (SELECT MID FROM movies_with_non_female)
),
movies_per_year AS (
    SELECT yr, COUNT(DISTINCT MID) AS total_movies FROM movie_years GROUP BY yr
),
female_per_year AS (
    SELECT my.yr, COUNT(DISTINCT my.MID) AS female_movies
    FROM movie_years my INNER JOIN exclusively_female ef ON my.MID = ef.MID
    GROUP BY my.yr
)
SELECT mpy.yr AS year, mpy.total_movies,
    COALESCE(CAST(fpy.female_movies AS REAL) / mpy.total_movies * 100, 0.0) AS percentage
FROM movies_per_year mpy
LEFT JOIN female_per_year fpy ON mpy.yr = fpy.yr
ORDER BY mpy.yr;
