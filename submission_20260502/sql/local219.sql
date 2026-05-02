-- ========== OUTPUT COLUMN SPEC ==========
-- 1. league_id   : league's primary key
-- 2. league_name : league's name (from League table)
-- 3. team_api_id : team's API ID
-- 4. team_name   : team's long name (from Team table)
-- 5. total_wins  : total wins across all seasons in that league
-- ========================================

-- INTERPRETATION: For each league (across all seasons), find the single team
-- with the minimum total wins. A win is counted when:
--   - home win: home_team_goal > away_team_goal
--   - away win: away_team_goal > home_team_goal
-- All teams that participated in a league are included (even with 0 wins).
-- Ties are broken by team_api_id ASC to ensure exactly one row per league.

-- EXPECTED: 11 rows (one per league)

WITH team_league_pairs AS (
    -- All distinct (league, team) pairs from both home and away appearances
    SELECT DISTINCT league_id, home_team_api_id AS team_api_id FROM Match
    UNION
    SELECT DISTINCT league_id, away_team_api_id AS team_api_id FROM Match
),
team_wins AS (
    -- Home wins per team per league
    SELECT league_id, home_team_api_id AS team_api_id,
           SUM(CASE WHEN home_team_goal > away_team_goal THEN 1 ELSE 0 END) AS wins
    FROM Match
    GROUP BY league_id, home_team_api_id
    UNION ALL
    -- Away wins per team per league
    SELECT league_id, away_team_api_id AS team_api_id,
           SUM(CASE WHEN away_team_goal > home_team_goal THEN 1 ELSE 0 END) AS wins
    FROM Match
    GROUP BY league_id, away_team_api_id
),
team_total_wins AS (
    -- Sum home + away wins; teams with no wins get 0 via COALESCE
    SELECT tlp.league_id, tlp.team_api_id,
           COALESCE(SUM(tw.wins), 0) AS total_wins
    FROM team_league_pairs tlp
    LEFT JOIN team_wins tw ON tlp.league_id = tw.league_id AND tlp.team_api_id = tw.team_api_id
    GROUP BY tlp.league_id, tlp.team_api_id
),
ranked AS (
    SELECT ttw.league_id, l.name AS league_name, ttw.team_api_id,
           t.team_long_name AS team_name, ttw.total_wins,
           ROW_NUMBER() OVER (PARTITION BY ttw.league_id ORDER BY ttw.total_wins ASC, ttw.team_api_id ASC) AS rn
    FROM team_total_wins ttw
    JOIN League l ON ttw.league_id = l.id
    LEFT JOIN Team t ON ttw.team_api_id = t.team_api_id
)
SELECT league_id, league_name, team_api_id, team_name, total_wins
FROM ranked
WHERE rn = 1
ORDER BY league_id;
