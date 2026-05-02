-- ========== OUTPUT COLUMN SPEC ==========
-- 1. name_given  : player's given name (from player.name_given)
-- 2. score       : the highest career total value for that stat
-- Note: 4 rows total — one winner per stat (games played, runs, hits, home runs)
-- ========================================

-- INTERPRETATION: For each of 4 stats (games played, runs, hits, home runs),
-- find the player who achieved the highest career total. Return their given name + that value.
-- Career totals = SUM(stat) per player across all seasons in the batting table.

-- EXPECTED: 4 rows (one per stat category: g, r, h, hr)

WITH career_stats AS (
    SELECT player_id,
           SUM(g)  AS total_g,
           SUM(r)  AS total_r,
           SUM(h)  AS total_h,
           SUM(hr) AS total_hr
    FROM batting
    GROUP BY player_id
)
SELECT p.name_given, cs.total_g AS score
FROM career_stats cs
JOIN player p ON cs.player_id = p.player_id
WHERE cs.total_g = (SELECT MAX(total_g) FROM career_stats)
UNION ALL
SELECT p.name_given, cs.total_r AS score
FROM career_stats cs
JOIN player p ON cs.player_id = p.player_id
WHERE cs.total_r = (SELECT MAX(total_r) FROM career_stats)
UNION ALL
SELECT p.name_given, cs.total_h AS score
FROM career_stats cs
JOIN player p ON cs.player_id = p.player_id
WHERE cs.total_h = (SELECT MAX(total_h) FROM career_stats)
UNION ALL
SELECT p.name_given, cs.total_hr AS score
FROM career_stats cs
JOIN player p ON cs.player_id = p.player_id
WHERE cs.total_hr = (SELECT MAX(total_hr) FROM career_stats)
