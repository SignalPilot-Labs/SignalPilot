-- ========== OUTPUT COLUMN SPEC ==========
-- 1. player_id          : player's unique primary key
-- 2. player_name        : player's full name
-- 3. most_frequent_role : most common role in player_match
-- 4. batting_hand       : from player table
-- 5. bowling_skill      : from player table
-- 6. total_runs         : sum of runs_scored as striker (batsman_scored, ignores extra_runs)
-- 7. total_matches      : count distinct match_id from player_match
-- 8. total_dismissals   : count from wicket_taken where player_out = player_id
-- 9. batting_average    : total_runs / total_dismissals (NULL if no dismissals)
-- 10. highest_score     : max per-match runs as striker
-- 11. matches_30plus    : count matches where player scored >= 30
-- 12. matches_50plus    : count matches where player scored >= 50
-- 13. matches_100plus   : count matches where player scored >= 100
-- 14. total_balls_faced : count rows in ball_by_ball where striker = player_id
-- 15. strike_rate       : (total_runs / total_balls_faced) * 100
-- 16. total_wickets     : count wickets from wicket_taken joined to ball_by_ball where bowler = player_id
-- 17. economy_rate      : (runs conceded / balls bowled) * 6
-- 18. best_bowling      : "W-R" from best single match (most wickets, fewest runs on tie)
-- ========================================

-- INTERPRETATION: For each of the 468 players in the database, compute a full
-- career statistics profile covering batting and bowling metrics.
-- "Ignore extra runs data" means we do NOT include extra_runs in any calculation.
-- Batting runs come only from batsman_scored; bowling runs conceded come only from
-- batsman_scored (not extra_runs). Balls faced = all deliveries as striker in ball_by_ball.
-- Balls bowled = all deliveries as bowler in ball_by_ball.
-- Economy rate uses (runs_conceded / balls_bowled) * 6 per domain definition.
-- Best bowling = match with most wickets, fewest runs conceded as tie-breaker.

-- EXPECTED: 468 rows (one per player)

WITH role_rank AS (
    SELECT
        player_id,
        role,
        COUNT(*) AS cnt,
        ROW_NUMBER() OVER (PARTITION BY player_id ORDER BY COUNT(*) DESC) AS rn
    FROM player_match
    GROUP BY player_id, role
),
most_frequent_role AS (
    SELECT player_id, role AS most_frequent_role
    FROM role_rank
    WHERE rn = 1
),
match_batting AS (
    SELECT
        bbb.striker AS player_id,
        bbb.match_id,
        SUM(bs.runs_scored) AS match_runs
    FROM ball_by_ball bbb
    JOIN batsman_scored bs ON bbb.match_id = bs.match_id
        AND bbb.over_id = bs.over_id
        AND bbb.ball_id = bs.ball_id
        AND bbb.innings_no = bs.innings_no
    GROUP BY bbb.striker, bbb.match_id
),
batting_stats AS (
    SELECT
        player_id,
        SUM(match_runs) AS total_runs,
        MAX(match_runs) AS highest_score,
        COUNT(CASE WHEN match_runs >= 30 THEN 1 END) AS matches_30plus,
        COUNT(CASE WHEN match_runs >= 50 THEN 1 END) AS matches_50plus,
        COUNT(CASE WHEN match_runs >= 100 THEN 1 END) AS matches_100plus
    FROM match_batting
    GROUP BY player_id
),
balls_faced AS (
    SELECT
        striker AS player_id,
        COUNT(*) AS total_balls_faced
    FROM ball_by_ball
    GROUP BY striker
),
dismissals AS (
    SELECT
        player_out AS player_id,
        COUNT(*) AS total_dismissals
    FROM wicket_taken
    GROUP BY player_out
),
total_matches AS (
    SELECT
        player_id,
        COUNT(DISTINCT match_id) AS total_matches
    FROM player_match
    GROUP BY player_id
),
match_bowling AS (
    SELECT
        bbb.bowler AS player_id,
        bbb.match_id,
        COUNT(*) AS balls_bowled,
        COALESCE(SUM(bs.runs_scored), 0) AS runs_conceded
    FROM ball_by_ball bbb
    LEFT JOIN batsman_scored bs ON bbb.match_id = bs.match_id
        AND bbb.over_id = bs.over_id
        AND bbb.ball_id = bs.ball_id
        AND bbb.innings_no = bs.innings_no
    GROUP BY bbb.bowler, bbb.match_id
),
match_wickets AS (
    SELECT
        bbb.bowler AS player_id,
        bbb.match_id,
        COUNT(*) AS wickets_in_match
    FROM wicket_taken wt
    JOIN ball_by_ball bbb ON wt.match_id = bbb.match_id
        AND wt.over_id = bbb.over_id
        AND wt.ball_id = bbb.ball_id
        AND wt.innings_no = bbb.innings_no
    GROUP BY bbb.bowler, bbb.match_id
),
bowling_career AS (
    SELECT
        player_id,
        SUM(balls_bowled) AS total_balls_bowled,
        SUM(runs_conceded) AS total_runs_conceded
    FROM match_bowling
    GROUP BY player_id
),
wickets_career AS (
    SELECT
        player_id,
        SUM(wickets_in_match) AS total_wickets
    FROM match_wickets
    GROUP BY player_id
),
best_bowling_combined AS (
    SELECT
        mw.player_id,
        mw.match_id,
        mw.wickets_in_match,
        COALESCE(mb.runs_conceded, 0) AS runs_conceded
    FROM match_wickets mw
    LEFT JOIN match_bowling mb ON mw.player_id = mb.player_id AND mw.match_id = mb.match_id
),
best_bowling_rank AS (
    SELECT
        player_id,
        wickets_in_match,
        runs_conceded,
        ROW_NUMBER() OVER (
            PARTITION BY player_id
            ORDER BY wickets_in_match DESC, runs_conceded ASC
        ) AS rn
    FROM best_bowling_combined
),
best_bowling AS (
    SELECT
        player_id,
        CAST(wickets_in_match AS TEXT) || '-' || CAST(runs_conceded AS TEXT) AS best_bowling
    FROM best_bowling_rank
    WHERE rn = 1
)
SELECT
    p.player_id,
    p.player_name,
    mfr.most_frequent_role,
    p.batting_hand,
    p.bowling_skill,
    COALESCE(bat.total_runs, 0) AS total_runs,
    COALESCE(tm.total_matches, 0) AS total_matches,
    COALESCE(d.total_dismissals, 0) AS total_dismissals,
    CASE WHEN COALESCE(d.total_dismissals, 0) = 0 THEN NULL
         ELSE CAST(COALESCE(bat.total_runs, 0) AS REAL) / d.total_dismissals
    END AS batting_average,
    COALESCE(bat.highest_score, 0) AS highest_score,
    COALESCE(bat.matches_30plus, 0) AS matches_30plus,
    COALESCE(bat.matches_50plus, 0) AS matches_50plus,
    COALESCE(bat.matches_100plus, 0) AS matches_100plus,
    COALESCE(bf.total_balls_faced, 0) AS total_balls_faced,
    CASE WHEN COALESCE(bf.total_balls_faced, 0) = 0 THEN NULL
         ELSE CAST(COALESCE(bat.total_runs, 0) AS REAL) / bf.total_balls_faced * 100
    END AS strike_rate,
    COALESCE(wc.total_wickets, 0) AS total_wickets,
    CASE WHEN COALESCE(bc.total_balls_bowled, 0) = 0 THEN NULL
         ELSE CAST(bc.total_runs_conceded AS REAL) / bc.total_balls_bowled * 6
    END AS economy_rate,
    bb.best_bowling
FROM player p
LEFT JOIN most_frequent_role mfr ON p.player_id = mfr.player_id
LEFT JOIN batting_stats bat ON p.player_id = bat.player_id
LEFT JOIN balls_faced bf ON p.player_id = bf.player_id
LEFT JOIN dismissals d ON p.player_id = d.player_id
LEFT JOIN total_matches tm ON p.player_id = tm.player_id
LEFT JOIN bowling_career bc ON p.player_id = bc.player_id
LEFT JOIN wickets_career wc ON p.player_id = wc.player_id
LEFT JOIN best_bowling bb ON p.player_id = bb.player_id
ORDER BY p.player_id
