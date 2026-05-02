-- ========== OUTPUT COLUMN SPEC ==========
-- 1. driver_id   : unique identifier for the driver
-- 2. driver_name : full name of the driver (forename || ' ' || surname)
-- ========================================

-- INTERPRETATION: Find F1 drivers who, in at least one season between 1950-1959,
-- (a) had the same constructor in their first race (min round) and their last race
--     (max round) of that season, AND
-- (b) participated in at least 2 distinct race rounds during that season.
-- Returns distinct drivers (not seasons).

-- EXPECTED: ~100 rows — many 1950s drivers raced exclusively with one constructor per season

WITH season_bounds AS (
    -- For each driver+year in the 1950s, find the overall first and last round
    SELECT year, driver_id,
           MIN(first_round) AS season_first_round,
           MAX(last_round) AS season_last_round
    FROM drives
    WHERE year BETWEEN 1950 AND 1959
    GROUP BY year, driver_id
),
distinct_rounds AS (
    -- Count distinct rounds actually participated in per driver+year
    SELECT res.driver_id, ra.year, COUNT(DISTINCT ra.round) AS num_rounds
    FROM results res
    JOIN races ra ON res.race_id = ra.race_id
    WHERE ra.year BETWEEN 1950 AND 1959
    GROUP BY res.driver_id, ra.year
),
qualifying_driver_seasons AS (
    -- Find driver+year combinations where first and last race used the same constructor
    -- and the driver participated in at least 2 distinct rounds
    SELECT DISTINCT sb.driver_id, sb.year
    FROM season_bounds sb
    JOIN drives d_first ON d_first.year = sb.year
        AND d_first.driver_id = sb.driver_id
        AND d_first.first_round = sb.season_first_round
    JOIN drives d_last ON d_last.year = sb.year
        AND d_last.driver_id = sb.driver_id
        AND d_last.last_round = sb.season_last_round
        AND d_last.constructor_id = d_first.constructor_id  -- same constructor first and last
    JOIN distinct_rounds dr ON dr.year = sb.year AND dr.driver_id = sb.driver_id
    WHERE dr.num_rounds >= 2
)
SELECT DISTINCT
    d.driver_id,
    d.forename || ' ' || d.surname AS driver_name
FROM qualifying_driver_seasons q
JOIN drivers d ON q.driver_id = d.driver_id
ORDER BY d.forename || ' ' || d.surname;
