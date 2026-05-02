-- INTERPRETATION: For each F1 season since 2001, among all constructors whose drivers
-- scored any points, find which constructor had the fewest total points from those
-- point-scoring drivers. Count how many seasons each constructor was at the bottom.
-- Return top 5 constructors by that count.
-- EXPECTED: 5 rows

-- OUTPUT COLUMN SPEC:
-- 1. constructor_id            : primary key of the constructor
-- 2. name                      : constructor name
-- 3. seasons_with_fewest_points: count of seasons where this constructor had fewest total points

WITH driver_season_points AS (
    -- Total points per driver per season (only point-scoring drivers)
    SELECT
        r.year,
        res.driver_id,
        res.constructor_id,
        SUM(res.points) AS total_points
    FROM results res
    JOIN races r ON res.race_id = r.race_id
    WHERE r.year >= 2001
    GROUP BY r.year, res.driver_id, res.constructor_id
    HAVING SUM(res.points) > 0
),
constructor_season_points AS (
    -- Total points per constructor per season (sum of point-scoring drivers)
    SELECT
        year,
        constructor_id,
        SUM(total_points) AS constructor_total_points
    FROM driver_season_points
    GROUP BY year, constructor_id
),
min_points_per_season AS (
    -- Minimum constructor total per season
    SELECT
        year,
        MIN(constructor_total_points) AS min_points
    FROM constructor_season_points
    GROUP BY year
),
constructors_with_fewest AS (
    -- Constructors that had the minimum points in each season
    SELECT
        csp.year,
        csp.constructor_id
    FROM constructor_season_points csp
    JOIN min_points_per_season mps
        ON csp.year = mps.year
        AND csp.constructor_total_points = mps.min_points
),
constructor_counts AS (
    -- Count seasons each constructor was at the bottom
    SELECT
        constructor_id,
        COUNT(*) AS seasons_with_fewest_points
    FROM constructors_with_fewest
    GROUP BY constructor_id
)
SELECT
    cc.constructor_id,
    c.name,
    cc.seasons_with_fewest_points
FROM constructor_counts cc
JOIN constructors c ON cc.constructor_id = c.constructor_id
ORDER BY cc.seasons_with_fewest_points DESC, c.name
LIMIT 5;
