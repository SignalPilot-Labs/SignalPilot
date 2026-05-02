-- ========== OUTPUT COLUMN SPEC ==========
-- 1. avg_total_runs : average of total runs scored by qualifying strikers
--    (strikers who scored > 50 in any single match)
-- ========================================
-- EXPECTED: 1 row, 1 column
-- INTERPRETATION: Find strikers who scored > 50 runs in any single match,
--   sum each such striker's total runs across all matches, then average those totals.

WITH striker_match_runs AS (
    SELECT
        b.striker,
        b.match_id,
        SUM(bs.runs_scored) AS match_runs
    FROM ball_by_ball b
    JOIN batsman_scored bs
        ON b.match_id = bs.match_id
        AND b.over_id = bs.over_id
        AND b.ball_id = bs.ball_id
        AND b.innings_no = bs.innings_no
    GROUP BY b.striker, b.match_id
),
qualifying_strikers AS (
    SELECT DISTINCT striker
    FROM striker_match_runs
    WHERE match_runs > 50
),
striker_totals AS (
    SELECT
        smr.striker,
        SUM(smr.match_runs) AS total_runs
    FROM striker_match_runs smr
    WHERE smr.striker IN (SELECT striker FROM qualifying_strikers)
    GROUP BY smr.striker
)
SELECT AVG(total_runs) AS avg_total_runs
FROM striker_totals
