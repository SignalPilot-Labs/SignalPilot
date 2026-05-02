-- ========== OUTPUT COLUMN SPEC ==========
-- 1. rank          : ranking position (1, 2, 3)
-- 2. bowler_id     : player_id of the bowler (natural key)
-- 3. bowler_name   : player_name of the bowler
-- 4. match_id      : match_id where the bowler conceded the maximum runs
-- 5. runs_conceded : total runs conceded in that single over
-- ========================================
--
-- INTERPRETATION: For each match, find the over(s) where maximum total runs were
-- conceded (batsman runs + extras). From all such "max overs" across all matches,
-- rank bowlers by runs conceded in a single over (descending) and return the top 3.
--
-- EXPECTED: 3 rows

WITH over_runs AS (
    -- Total runs per over per match (batsman runs + extras), keyed by bowler
    SELECT
        b.match_id,
        b.over_id,
        b.innings_no,
        b.bowler,
        SUM(COALESCE(bs.runs_scored, 0) + COALESCE(er.extra_runs, 0)) AS total_runs
    FROM ball_by_ball b
    LEFT JOIN batsman_scored bs
        ON b.match_id = bs.match_id
        AND b.over_id = bs.over_id
        AND b.ball_id = bs.ball_id
        AND b.innings_no = bs.innings_no
    LEFT JOIN extra_runs er
        ON b.match_id = er.match_id
        AND b.over_id = er.over_id
        AND b.ball_id = er.ball_id
        AND b.innings_no = er.innings_no
    GROUP BY b.match_id, b.over_id, b.innings_no, b.bowler
),
max_over_per_match AS (
    -- Maximum runs in any single over for each match
    SELECT match_id, MAX(total_runs) AS max_runs
    FROM over_runs
    GROUP BY match_id
),
top_overs AS (
    -- Only overs that had the maximum runs in their respective match
    SELECT o.match_id, o.over_id, o.innings_no, o.bowler, o.total_runs
    FROM over_runs o
    JOIN max_over_per_match m
        ON o.match_id = m.match_id
        AND o.total_runs = m.max_runs
),
ranked_bowlers AS (
    -- Rank bowlers by runs conceded in a single max-over, deterministic tie-breaking
    SELECT
        bowler,
        match_id,
        total_runs,
        ROW_NUMBER() OVER (ORDER BY total_runs DESC, match_id ASC, bowler ASC) AS rnk
    FROM top_overs
)
SELECT
    rb.rnk AS rank,
    rb.bowler AS bowler_id,
    p.player_name AS bowler_name,
    rb.match_id,
    rb.total_runs AS runs_conceded
FROM ranked_bowlers rb
JOIN player p ON rb.bowler = p.player_id
WHERE rb.rnk <= 3
ORDER BY rb.rnk;
