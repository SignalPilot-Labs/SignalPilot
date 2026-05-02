-- INTERPRETATION: For each team, find the maximum total goals scored in a single season
-- (summing home + away goals). Then compute the median of those per-team maximums.
-- EXPECTED: 1 row (single scalar median value)

WITH team_season_goals AS (
    SELECT
        home_team_api_id AS team_api_id,
        season,
        SUM(home_team_goal) AS goals
    FROM Match
    GROUP BY home_team_api_id, season
    UNION ALL
    SELECT
        away_team_api_id AS team_api_id,
        season,
        SUM(away_team_goal) AS goals
    FROM Match
    GROUP BY away_team_api_id, season
),
team_season_total AS (
    SELECT
        team_api_id,
        season,
        SUM(goals) AS season_goals
    FROM team_season_goals
    GROUP BY team_api_id, season
),
team_max_goals AS (
    SELECT
        team_api_id,
        MAX(season_goals) AS max_season_goals
    FROM team_season_total
    GROUP BY team_api_id
),
ranked AS (
    SELECT
        max_season_goals,
        ROW_NUMBER() OVER (ORDER BY max_season_goals) AS rn,
        COUNT(*) OVER () AS cnt
    FROM team_max_goals
)
SELECT AVG(CAST(max_season_goals AS REAL)) AS median
FROM ranked
WHERE rn IN ((cnt + 1) / 2, (cnt + 2) / 2)
