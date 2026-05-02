-- INTERPRETATION: Find players who scored >= 100 runs in a single match while batting for the losing team.
-- EXPECTED: Small number of distinct player names

WITH player_runs AS (
    SELECT
        b.match_id,
        b.striker AS player_id,
        SUM(bs.runs_scored) AS total_runs
    FROM ball_by_ball b
    JOIN batsman_scored bs
        ON b.match_id = bs.match_id
        AND b.over_id = bs.over_id
        AND b.ball_id = bs.ball_id
        AND b.innings_no = bs.innings_no
    GROUP BY b.match_id, b.striker
),
match_loser AS (
    SELECT
        match_id,
        CASE WHEN team_1 = match_winner THEN team_2 ELSE team_1 END AS losing_team
    FROM match
    WHERE match_winner IS NOT NULL
)
SELECT DISTINCT p.player_name
FROM player_runs pr
JOIN match_loser ml ON pr.match_id = ml.match_id
JOIN player_match pm ON pr.match_id = pm.match_id AND pr.player_id = pm.player_id
JOIN player p ON pr.player_id = p.player_id
WHERE pr.total_runs >= 100
  AND pm.team_id = ml.losing_team
ORDER BY p.player_name
