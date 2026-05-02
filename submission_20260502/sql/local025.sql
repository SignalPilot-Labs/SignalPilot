-- ========== OUTPUT COLUMN SPEC ==========
-- 1. match_id              : match identifier
-- 2. innings_no            : innings number for the best over
-- 3. over_id               : over number with highest combined runs for that match
-- 4. total_runs            : combined batsman + extra runs for that over
-- 5. bowler_id             : bowler who bowled that over (from ball_by_ball)
-- 6. avg_highest_over_runs : average of the highest over totals across all matches
-- ========================================
-- INTERPRETATION: For each match (all innings), sum batsman_scored.runs_scored +
-- extra_runs.extra_runs per (match_id, innings_no, over_id). Pick the single over
-- with the highest total per match (ROW_NUMBER tiebreak). Retrieve that over's
-- bowler from ball_by_ball. Compute AVG of those max totals across all 568 matches.
-- EXPECTED: 568 rows (one per match), avg_highest_over_runs = 19.426056338028168

WITH batsman_over AS (
    SELECT match_id, innings_no, over_id, SUM(runs_scored) AS batsman_runs
    FROM batsman_scored
    GROUP BY match_id, innings_no, over_id
),
extra_over AS (
    SELECT match_id, innings_no, over_id, SUM(extra_runs) AS extra_runs_total
    FROM extra_runs
    GROUP BY match_id, innings_no, over_id
),
all_overs AS (
    SELECT DISTINCT match_id, innings_no, over_id FROM batsman_scored
    UNION
    SELECT DISTINCT match_id, innings_no, over_id FROM extra_runs
),
over_total AS (
    SELECT
        ao.match_id,
        ao.innings_no,
        ao.over_id,
        COALESCE(b.batsman_runs, 0) + COALESCE(e.extra_runs_total, 0) AS total_runs
    FROM all_overs ao
    LEFT JOIN batsman_over b
        ON ao.match_id = b.match_id
       AND ao.innings_no = b.innings_no
       AND ao.over_id = b.over_id
    LEFT JOIN extra_over e
        ON ao.match_id = e.match_id
       AND ao.innings_no = e.innings_no
       AND ao.over_id = e.over_id
),
ranked_overs AS (
    SELECT
        match_id, innings_no, over_id, total_runs,
        ROW_NUMBER() OVER (PARTITION BY match_id ORDER BY total_runs DESC) AS rn
    FROM over_total
),
best_over AS (
    SELECT match_id, innings_no, over_id, total_runs
    FROM ranked_overs
    WHERE rn = 1
),
bowler_over AS (
    SELECT
        bo.match_id,
        bo.innings_no,
        bo.over_id,
        bo.total_runs,
        MIN(bb.bowler) AS bowler_id
    FROM best_over bo
    JOIN ball_by_ball bb
        ON bo.match_id   = bb.match_id
       AND bo.innings_no = bb.innings_no
       AND bo.over_id    = bb.over_id
    GROUP BY bo.match_id, bo.innings_no, bo.over_id, bo.total_runs
)
SELECT
    match_id,
    innings_no,
    over_id,
    total_runs,
    bowler_id,
    AVG(total_runs) OVER () AS avg_highest_over_runs
FROM bowler_over
ORDER BY match_id;
