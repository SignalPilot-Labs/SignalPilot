-- ========== OUTPUT COLUMN SPEC ==========
-- 1. season_id     : IPL season identifier (ascending order)
-- 2. position      : 1, 2, or 3 (matched rank between batsman and bowler)
-- 3. batsman_id    : player_id of the top batsman
-- 4. batsman_name  : player name of the top batsman
-- 5. total_runs    : total runs scored by the batsman in the season
-- 6. bowler_id     : player_id of the top bowler
-- 7. bowler_name   : player name of the top bowler
-- 8. total_wickets : total wickets taken by the bowler (excluding run out, hit wicket, retired hurt)
-- ========================================

-- EXPECTED: 27 rows (9 seasons × 3 positions each)
-- INTERPRETATION: For each IPL season, find the top-3 run-scorers and top-3 wicket-takers
-- (excluding run out, hit wicket, retired hurt dismissals), then pair them by rank position.
-- Ties broken by smaller player_id.

WITH season_runs AS (
    SELECT
        m.season_id,
        bbb.striker AS player_id,
        SUM(bs.runs_scored) AS total_runs
    FROM ball_by_ball bbb
    JOIN batsman_scored bs ON bbb.match_id = bs.match_id
        AND bbb.over_id = bs.over_id
        AND bbb.ball_id = bs.ball_id
        AND bbb.innings_no = bs.innings_no
    JOIN match m ON bbb.match_id = m.match_id
    GROUP BY m.season_id, bbb.striker
),
ranked_batsmen AS (
    SELECT
        season_id,
        player_id,
        total_runs,
        ROW_NUMBER() OVER (PARTITION BY season_id ORDER BY total_runs DESC, player_id ASC) AS rank
    FROM season_runs
),
top_batsmen AS (
    SELECT * FROM ranked_batsmen WHERE rank <= 3
),
season_wickets AS (
    SELECT
        m.season_id,
        bbb.bowler AS player_id,
        COUNT(*) AS total_wickets
    FROM wicket_taken wt
    JOIN ball_by_ball bbb ON wt.match_id = bbb.match_id
        AND wt.over_id = bbb.over_id
        AND wt.ball_id = bbb.ball_id
        AND wt.innings_no = bbb.innings_no
    JOIN match m ON wt.match_id = m.match_id
    WHERE wt.kind_out NOT IN ('run out', 'hit wicket', 'retired hurt')
    GROUP BY m.season_id, bbb.bowler
),
ranked_bowlers AS (
    SELECT
        season_id,
        player_id,
        total_wickets,
        ROW_NUMBER() OVER (PARTITION BY season_id ORDER BY total_wickets DESC, player_id ASC) AS rank
    FROM season_wickets
),
top_bowlers AS (
    SELECT * FROM ranked_bowlers WHERE rank <= 3
)
SELECT
    tb.season_id,
    tb.rank AS position,
    tb.player_id AS batsman_id,
    p1.player_name AS batsman_name,
    tb.total_runs,
    bw.player_id AS bowler_id,
    p2.player_name AS bowler_name,
    bw.total_wickets
FROM top_batsmen tb
JOIN top_bowlers bw ON tb.season_id = bw.season_id AND tb.rank = bw.rank
JOIN player p1 ON tb.player_id = p1.player_id
JOIN player p2 ON bw.player_id = p2.player_id
ORDER BY tb.season_id ASC, tb.rank ASC;
