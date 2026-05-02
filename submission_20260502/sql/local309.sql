-- INTERPRETATION: For each F1 season year, find the driver who scored the most points
-- (position=1 in final standings) and the constructor who scored the most points
-- (position=1 in final standings). Use the last race of each year to get final standings.
-- Constructor standings started in 1958, so earlier years have NULL constructor data.

-- ========== OUTPUT COLUMN SPEC ==========
-- 1. year              : the F1 season year
-- 2. driver_id         : driver primary key
-- 3. driver_name       : full name of the top-scoring driver (forename || ' ' || surname)
-- 4. driver_points     : total points scored by that driver in the year
-- 5. constructor_id    : constructor primary key
-- 6. constructor_name  : name of the top-scoring constructor
-- 7. constructor_points: total points scored by that constructor in the year
-- ========================================

-- EXPECTED: ~74 rows (one per F1 season, 1950-2023)

WITH last_race_per_year AS (
  SELECT year, race_id AS last_race_id
  FROM (
    SELECT year, race_id, ROW_NUMBER() OVER (PARTITION BY year ORDER BY round DESC) AS rn
    FROM races
  ) sub
  WHERE rn = 1
),
driver_season_standings AS (
  SELECT
    r.year,
    ds.driver_id,
    ds.points AS driver_points,
    ds.position AS driver_position
  FROM driver_standings ds
  JOIN last_race_per_year r ON ds.race_id = r.last_race_id
),
top_driver_per_year AS (
  SELECT year, driver_id, driver_points
  FROM driver_season_standings
  WHERE driver_position = 1
),
constructor_season_standings AS (
  SELECT
    r.year,
    cs.constructor_id,
    cs.points AS constructor_points,
    cs.position AS constructor_position
  FROM constructor_standings cs
  JOIN last_race_per_year r ON cs.race_id = r.last_race_id
),
top_constructor_per_year AS (
  SELECT year, constructor_id, constructor_points
  FROM constructor_season_standings
  WHERE constructor_position = 1
)
SELECT
  td.year,
  td.driver_id,
  (de.forename || ' ' || de.surname) AS driver_name,
  td.driver_points,
  tc.constructor_id,
  con.name AS constructor_name,
  tc.constructor_points
FROM top_driver_per_year td
JOIN drivers de ON td.driver_id = de.driver_id
LEFT JOIN top_constructor_per_year tc ON td.year = tc.year
LEFT JOIN constructors con ON tc.constructor_id = con.constructor_id
ORDER BY td.year
