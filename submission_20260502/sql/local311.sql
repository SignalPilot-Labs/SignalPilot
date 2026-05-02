-- EXPECTED: 3 rows because "top 3"
-- INTERPRETATION: For each constructor+year, combined_points = constructor season-end points + best driver season-end points
-- The "best driver" is the driver with max season-end points who drove for that constructor that year

WITH last_race_per_year AS (
    SELECT r.year, r.race_id
    FROM races r
    JOIN (SELECT year, MAX(round) as max_round FROM races GROUP BY year) lr
      ON r.year = lr.year AND r.round = lr.max_round
),
constructor_season_pts AS (
    SELECT lr.year, cs.constructor_id, cs.points AS constructor_points
    FROM constructor_standings cs
    JOIN last_race_per_year lr ON cs.race_id = lr.race_id
),
driver_season_pts AS (
    SELECT lr.year, ds.driver_id, ds.points AS driver_points
    FROM driver_standings ds
    JOIN last_race_per_year lr ON ds.race_id = lr.race_id
),
driver_constructor_link AS (
    -- Link drivers to constructors via any race in the season
    SELECT DISTINCT r.year, res.driver_id, res.constructor_id
    FROM results res
    JOIN races r ON res.race_id = r.race_id
),
best_driver_per_constructor AS (
    SELECT dcl.year, dcl.constructor_id, MAX(dsp.driver_points) AS best_driver_points
    FROM driver_constructor_link dcl
    JOIN driver_season_pts dsp ON dcl.driver_id = dsp.driver_id AND dcl.year = dsp.year
    GROUP BY dcl.year, dcl.constructor_id
),
combined AS (
    SELECT
        csp.year,
        csp.constructor_id,
        csp.constructor_points,
        bdp.best_driver_points,
        csp.constructor_points + bdp.best_driver_points AS combined_points
    FROM constructor_season_pts csp
    JOIN best_driver_per_constructor bdp
      ON csp.constructor_id = bdp.constructor_id AND csp.year = bdp.year
)
SELECT
    ROW_NUMBER() OVER (ORDER BY combined_points DESC) AS rank,
    c.year,
    con.constructor_id,
    con.name AS constructor_name,
    c.constructor_points,
    c.best_driver_points,
    c.combined_points
FROM combined c
JOIN constructors con ON c.constructor_id = con.constructor_id
ORDER BY combined_points DESC
LIMIT 3;
