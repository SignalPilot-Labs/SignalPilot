-- INTERPRETATION: Find the bowler with the lowest bowling average (runs conceded / wickets credited to bowler)
-- Excludes non-bowler dismissals: run out, retired hurt, obstructing the field
-- EXPECTED: 1 row — the single bowler with the minimum bowling average

WITH runs_per_bowler AS (
    SELECT b.bowler, SUM(bs.runs_scored) AS runs_conceded
    FROM ball_by_ball b
    JOIN batsman_scored bs
      ON b.match_id = bs.match_id
     AND b.over_id = bs.over_id
     AND b.ball_id = bs.ball_id
     AND b.innings_no = bs.innings_no
    GROUP BY b.bowler
),
wickets_per_bowler AS (
    SELECT b.bowler, COUNT(*) AS wickets_taken
    FROM ball_by_ball b
    JOIN wicket_taken w
      ON b.match_id = w.match_id
     AND b.over_id = w.over_id
     AND b.ball_id = w.ball_id
     AND b.innings_no = w.innings_no
    WHERE w.kind_out NOT IN ('run out', 'retired hurt', 'obstructing the field')
    GROUP BY b.bowler
),
bowling_avg AS (
    SELECT
        r.bowler,
        r.runs_conceded,
        w.wickets_taken,
        CAST(r.runs_conceded AS REAL) / w.wickets_taken AS bowling_average
    FROM runs_per_bowler r
    JOIN wickets_per_bowler w ON r.bowler = w.bowler
)
SELECT
    p.player_id,
    p.player_name,
    ba.bowling_average
FROM bowling_avg ba
JOIN player p ON ba.bowler = p.player_id
ORDER BY ba.bowling_average ASC
LIMIT 1;
