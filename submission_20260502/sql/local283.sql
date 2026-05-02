-- ========== OUTPUT COLUMN SPEC ==========
-- 1. season        : soccer season (e.g., "2014/2015")
-- 2. team_long_name: champion team's full name
-- 3. league        : name of the league
-- 4. country       : name of the country
-- 5. total_points  : total points (3*wins + 1*ties + 0*losses)
-- ========================================
-- EXPECTED: 88 rows (one champion per season+league, 8 seasons × 11 leagues)
-- INTERPRETATION: For each (season, league), compute each team's total points
--   by treating home and away appearances separately, then return the team with
--   the highest points. Ties broken by team_api_id ASC (deterministic).

WITH team_points AS (
  -- Home team points per match
  SELECT season, league_id, home_team_api_id AS team_api_id,
    CASE WHEN home_team_goal > away_team_goal THEN 3
         WHEN home_team_goal = away_team_goal THEN 1
         ELSE 0 END AS pts
  FROM Match
  UNION ALL
  -- Away team points per match
  SELECT season, league_id, away_team_api_id AS team_api_id,
    CASE WHEN away_team_goal > home_team_goal THEN 3
         WHEN away_team_goal = home_team_goal THEN 1
         ELSE 0 END AS pts
  FROM Match
),
team_totals AS (
  SELECT season, league_id, team_api_id, SUM(pts) AS total_points
  FROM team_points
  GROUP BY season, league_id, team_api_id
),
ranked AS (
  SELECT season, league_id, team_api_id, total_points,
    ROW_NUMBER() OVER (PARTITION BY season, league_id ORDER BY total_points DESC, team_api_id ASC) AS rn
  FROM team_totals
),
champions AS (
  SELECT season, league_id, team_api_id, total_points
  FROM ranked WHERE rn = 1
)
SELECT
  c.season,
  tm.team_long_name,
  l.name AS league,
  co.name AS country,
  c.total_points
FROM champions c
JOIN Team tm ON tm.team_api_id = c.team_api_id
JOIN League l ON l.id = c.league_id
JOIN Country co ON co.id = l.country_id
ORDER BY c.season, l.name
