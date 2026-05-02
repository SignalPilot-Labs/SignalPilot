-- ========== OUTPUT COLUMN SPEC ==========
-- 1. rank                : explicit ranking position (1-5) ordered by avg_batting_average DESC
-- 2. country_name        : name of the country (from player table)
-- 3. avg_batting_average : average of individual player averages (avg runs per match) for that country
-- ========================================

-- INTERPRETATION: For each player, compute their average runs per match across all matches.
-- Then for each country, compute the average of those player-level averages.
-- Return the top 5 countries ordered by this country batting average descending.
-- EXPECTED: 5 rows

WITH player_match_runs AS (
    SELECT b.striker as player_id, b.match_id, SUM(bs.runs_scored) as runs_in_match
    FROM ball_by_ball b
    JOIN batsman_scored bs ON b.match_id = bs.match_id AND b.over_id = bs.over_id AND b.ball_id = bs.ball_id AND b.innings_no = bs.innings_no
    GROUP BY b.striker, b.match_id
),
player_avg AS (
    SELECT player_id, AVG(runs_in_match) as avg_runs_per_match
    FROM player_match_runs
    GROUP BY player_id
),
country_avg AS (
    SELECT p.country_name, AVG(pa.avg_runs_per_match) as avg_batting_average
    FROM player_avg pa
    JOIN player p ON pa.player_id = p.player_id
    GROUP BY p.country_name
)
SELECT ROW_NUMBER() OVER (ORDER BY avg_batting_average DESC) AS rank,
       country_name,
       avg_batting_average
FROM country_avg
ORDER BY avg_batting_average DESC
LIMIT 5;
