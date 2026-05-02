-- ========== OUTPUT COLUMN SPEC ==========
-- 1. match_id          : match identifier
-- 2. player1_id        : player ID with higher individual score (or higher ID if tied)
-- 3. player1_score     : individual runs by player 1 in this partnership
-- 4. player2_id        : player ID with lower individual score (or lower ID if tied)
-- 5. player2_score     : individual runs by player 2 in this partnership
-- 6. partnership_score : total runs by the partnership
-- ========================================
-- EXPECTED: ~577 rows (one or more per match for top partnerships)
-- INTERPRETATION: Find the partnership (pair of batsmen) with the highest total runs
--   in each match; output both player IDs, their individual batting scores within
--   that partnership, and the total; handle ties per stated rules.

WITH ball_runs AS (
    SELECT bbb.match_id, bbb.innings_no, bbb.striker, bbb.non_striker,
        COALESCE(bs.runs_scored, 0) AS runs_scored
    FROM ball_by_ball bbb
    LEFT JOIN batsman_scored bs
        ON bbb.match_id = bs.match_id AND bbb.over_id = bs.over_id
        AND bbb.ball_id = bs.ball_id AND bbb.innings_no = bs.innings_no
),
partnership_stats AS (
    SELECT match_id, innings_no,
        MIN(striker, non_striker) AS player_a, MAX(striker, non_striker) AS player_b,
        SUM(CASE WHEN striker = MIN(striker, non_striker) THEN runs_scored ELSE 0 END) AS player_a_runs,
        SUM(CASE WHEN striker = MAX(striker, non_striker) THEN runs_scored ELSE 0 END) AS player_b_runs,
        SUM(runs_scored) AS total_partnership_runs
    FROM ball_runs
    GROUP BY match_id, innings_no, MIN(striker, non_striker), MAX(striker, non_striker)
),
match_max AS (
    SELECT match_id, MAX(total_partnership_runs) AS max_partnership FROM partnership_stats GROUP BY match_id
),
top_partnerships AS (
    SELECT ps.match_id, ps.player_a, ps.player_b, ps.player_a_runs, ps.player_b_runs, ps.total_partnership_runs
    FROM partnership_stats ps
    JOIN match_max mm ON ps.match_id = mm.match_id AND ps.total_partnership_runs = mm.max_partnership
)
SELECT
    match_id,
    CASE WHEN player_b_runs > player_a_runs THEN player_b WHEN player_a_runs > player_b_runs THEN player_a ELSE player_b END AS player1_id,
    CASE WHEN player_b_runs > player_a_runs THEN player_b_runs WHEN player_a_runs > player_b_runs THEN player_a_runs ELSE player_b_runs END AS player1_score,
    CASE WHEN player_b_runs > player_a_runs THEN player_a WHEN player_a_runs > player_b_runs THEN player_b ELSE player_a END AS player2_id,
    CASE WHEN player_b_runs > player_a_runs THEN player_a_runs WHEN player_a_runs > player_b_runs THEN player_b_runs ELSE player_a_runs END AS player2_score,
    total_partnership_runs AS partnership_score
FROM top_partnerships
ORDER BY match_id
