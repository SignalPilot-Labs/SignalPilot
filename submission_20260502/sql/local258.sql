-- ========== OUTPUT COLUMN SPEC ==========
-- 1. player_id     : unique identifier for the bowler (INTEGER)
-- 2. player_name   : name of the bowler (TEXT)
-- 3. total_wickets : wickets attributed to the bowler, excluding run out / retired hurt / obstructing the field
-- 4. economy_rate  : total bat runs conceded / (legal balls / 6), ignoring wides and no-balls in both runs and ball count
-- 5. strike_rate   : total legal balls bowled / total wickets taken
-- 6. best_bowling  : "W-R" string for the match with the most wickets taken (ties broken by fewest runs)
-- ==========================================

-- INTERPRETATION: For each bowler, compute aggregate bowling statistics:
--   wickets = count of dismissals attributed to the bowler (excl. run out, retired hurt, obstructing the field)
--   economy = bat runs (from batsman_scored, no extras) / legal overs (excl. wide/no-ball deliveries)
--   strike rate = legal balls / wickets
--   best bowling = "W-R" for the single best match by wickets (fewest runs as tiebreaker)

-- EXPECTED: ~282 rows (all players who bowled and took at least 1 wicket)

WITH bowler_match_balls AS (
    -- Legal deliveries only (excluding wides and no-balls from over count)
    SELECT
        b.bowler,
        b.match_id,
        COUNT(*) AS legal_balls
    FROM ball_by_ball b
    LEFT JOIN extra_runs er
        ON b.match_id = er.match_id
        AND b.over_id = er.over_id
        AND b.ball_id = er.ball_id
        AND b.innings_no = er.innings_no
        AND er.extra_type IN ('wides', 'noballs')
    WHERE er.match_id IS NULL
    GROUP BY b.bowler, b.match_id
),
bowler_match_bat_runs AS (
    -- Bat runs for all deliveries (batsman_scored contains only runs off the bat)
    SELECT
        b.bowler,
        b.match_id,
        SUM(COALESCE(bs.runs_scored, 0)) AS bat_runs
    FROM ball_by_ball b
    LEFT JOIN batsman_scored bs
        ON b.match_id = bs.match_id
        AND b.over_id = bs.over_id
        AND b.ball_id = bs.ball_id
        AND b.innings_no = bs.innings_no
    GROUP BY b.bowler, b.match_id
),
bowler_match_stats AS (
    SELECT
        bb.bowler,
        bb.match_id,
        bb.legal_balls AS balls,
        COALESCE(br.bat_runs, 0) AS bat_runs
    FROM bowler_match_balls bb
    LEFT JOIN bowler_match_bat_runs br ON bb.bowler = br.bowler AND bb.match_id = br.match_id
),
bowler_match_wickets AS (
    -- Wickets attributed to the bowler (excludes run out, retired hurt, obstructing the field)
    SELECT
        b.bowler,
        b.match_id,
        COUNT(*) AS wickets
    FROM ball_by_ball b
    JOIN wicket_taken wt
        ON b.match_id = wt.match_id
        AND b.over_id = wt.over_id
        AND b.ball_id = wt.ball_id
        AND b.innings_no = wt.innings_no
    WHERE wt.kind_out NOT IN ('run out', 'retired hurt', 'obstructing the field')
    GROUP BY b.bowler, b.match_id
),
combined AS (
    SELECT
        bms.bowler,
        bms.match_id,
        bms.balls,
        bms.bat_runs,
        COALESCE(bmw.wickets, 0) AS wickets
    FROM bowler_match_stats bms
    LEFT JOIN bowler_match_wickets bmw
        ON bms.bowler = bmw.bowler AND bms.match_id = bmw.match_id
),
bowler_totals AS (
    SELECT
        bowler,
        SUM(balls) AS total_balls,
        SUM(bat_runs) AS total_bat_runs,
        SUM(wickets) AS total_wickets
    FROM combined
    GROUP BY bowler
),
best_match AS (
    SELECT
        bowler,
        match_id,
        wickets,
        bat_runs,
        ROW_NUMBER() OVER (PARTITION BY bowler ORDER BY wickets DESC, bat_runs ASC) AS rn
    FROM combined
    WHERE wickets > 0
),
best_bowling AS (
    SELECT bowler, wickets || '-' || bat_runs AS best_bowling
    FROM best_match
    WHERE rn = 1
)
SELECT
    p.player_id,
    p.player_name,
    bt.total_wickets,
    CAST(bt.total_bat_runs AS REAL) / (bt.total_balls / 6.0) AS economy_rate,
    CAST(bt.total_balls AS REAL) / bt.total_wickets AS strike_rate,
    bb.best_bowling
FROM bowler_totals bt
JOIN player p ON bt.bowler = p.player_id
JOIN best_bowling bb ON bt.bowler = bb.bowler
WHERE bt.total_wickets > 0
ORDER BY bt.total_wickets DESC;
