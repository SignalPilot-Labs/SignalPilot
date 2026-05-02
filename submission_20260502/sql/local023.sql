-- Top 5 players with the highest average runs per match in season 5
-- INTERPRETATION: Filter matches where season_id = 5, sum runs per striker per match,
-- then average across matches played, rank top 5 descending.

WITH season5_matches AS (
    SELECT match_id FROM match WHERE season_id = 5
),
runs_per_ball AS (
    SELECT
        bbb.match_id,
        bbb.striker,
        bs.runs_scored
    FROM ball_by_ball bbb
    JOIN batsman_scored bs
        ON bbb.match_id = bs.match_id
        AND bbb.over_id = bs.over_id
        AND bbb.ball_id = bs.ball_id
        AND bbb.innings_no = bs.innings_no
    WHERE bbb.match_id IN (SELECT match_id FROM season5_matches)
),
runs_per_match AS (
    SELECT
        striker,
        match_id,
        SUM(runs_scored) AS match_runs
    FROM runs_per_ball
    GROUP BY striker, match_id
),
avg_runs AS (
    SELECT
        striker AS player_id,
        AVG(match_runs) AS avg_runs_per_match
    FROM runs_per_match
    GROUP BY striker
)
SELECT
    ar.player_id,
    p.player_name,
    ar.avg_runs_per_match
FROM avg_runs ar
JOIN player p ON ar.player_id = p.player_id
ORDER BY ar.avg_runs_per_match DESC
LIMIT 5;
