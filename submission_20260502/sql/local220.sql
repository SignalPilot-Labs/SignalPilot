-- EXPECTED: 2 rows (top winner, top loser)
-- INTERPRETATION: Find the single player with most winning match appearances (team won, non-draw)
--                 and single player with most losing match appearances (team lost, non-draw)
--                 across all 22 player positions in the Match table, excluding NULL entries
WITH player_matches AS (
  SELECT player_api_id, outcome FROM (
    SELECT home_player_1  AS player_api_id, CASE WHEN home_team_goal > away_team_goal THEN 'win' WHEN home_team_goal < away_team_goal THEN 'loss' ELSE 'draw' END AS outcome FROM Match WHERE home_player_1  IS NOT NULL
    UNION ALL
    SELECT home_player_2  AS player_api_id, CASE WHEN home_team_goal > away_team_goal THEN 'win' WHEN home_team_goal < away_team_goal THEN 'loss' ELSE 'draw' END FROM Match WHERE home_player_2  IS NOT NULL
    UNION ALL
    SELECT home_player_3  AS player_api_id, CASE WHEN home_team_goal > away_team_goal THEN 'win' WHEN home_team_goal < away_team_goal THEN 'loss' ELSE 'draw' END FROM Match WHERE home_player_3  IS NOT NULL
    UNION ALL
    SELECT home_player_4  AS player_api_id, CASE WHEN home_team_goal > away_team_goal THEN 'win' WHEN home_team_goal < away_team_goal THEN 'loss' ELSE 'draw' END FROM Match WHERE home_player_4  IS NOT NULL
    UNION ALL
    SELECT home_player_5  AS player_api_id, CASE WHEN home_team_goal > away_team_goal THEN 'win' WHEN home_team_goal < away_team_goal THEN 'loss' ELSE 'draw' END FROM Match WHERE home_player_5  IS NOT NULL
    UNION ALL
    SELECT home_player_6  AS player_api_id, CASE WHEN home_team_goal > away_team_goal THEN 'win' WHEN home_team_goal < away_team_goal THEN 'loss' ELSE 'draw' END FROM Match WHERE home_player_6  IS NOT NULL
    UNION ALL
    SELECT home_player_7  AS player_api_id, CASE WHEN home_team_goal > away_team_goal THEN 'win' WHEN home_team_goal < away_team_goal THEN 'loss' ELSE 'draw' END FROM Match WHERE home_player_7  IS NOT NULL
    UNION ALL
    SELECT home_player_8  AS player_api_id, CASE WHEN home_team_goal > away_team_goal THEN 'win' WHEN home_team_goal < away_team_goal THEN 'loss' ELSE 'draw' END FROM Match WHERE home_player_8  IS NOT NULL
    UNION ALL
    SELECT home_player_9  AS player_api_id, CASE WHEN home_team_goal > away_team_goal THEN 'win' WHEN home_team_goal < away_team_goal THEN 'loss' ELSE 'draw' END FROM Match WHERE home_player_9  IS NOT NULL
    UNION ALL
    SELECT home_player_10 AS player_api_id, CASE WHEN home_team_goal > away_team_goal THEN 'win' WHEN home_team_goal < away_team_goal THEN 'loss' ELSE 'draw' END FROM Match WHERE home_player_10 IS NOT NULL
    UNION ALL
    SELECT home_player_11 AS player_api_id, CASE WHEN home_team_goal > away_team_goal THEN 'win' WHEN home_team_goal < away_team_goal THEN 'loss' ELSE 'draw' END FROM Match WHERE home_player_11 IS NOT NULL
    UNION ALL
    SELECT away_player_1  AS player_api_id, CASE WHEN away_team_goal > home_team_goal THEN 'win' WHEN away_team_goal < home_team_goal THEN 'loss' ELSE 'draw' END FROM Match WHERE away_player_1  IS NOT NULL
    UNION ALL
    SELECT away_player_2  AS player_api_id, CASE WHEN away_team_goal > home_team_goal THEN 'win' WHEN away_team_goal < home_team_goal THEN 'loss' ELSE 'draw' END FROM Match WHERE away_player_2  IS NOT NULL
    UNION ALL
    SELECT away_player_3  AS player_api_id, CASE WHEN away_team_goal > home_team_goal THEN 'win' WHEN away_team_goal < home_team_goal THEN 'loss' ELSE 'draw' END FROM Match WHERE away_player_3  IS NOT NULL
    UNION ALL
    SELECT away_player_4  AS player_api_id, CASE WHEN away_team_goal > home_team_goal THEN 'win' WHEN away_team_goal < home_team_goal THEN 'loss' ELSE 'draw' END FROM Match WHERE away_player_4  IS NOT NULL
    UNION ALL
    SELECT away_player_5  AS player_api_id, CASE WHEN away_team_goal > home_team_goal THEN 'win' WHEN away_team_goal < home_team_goal THEN 'loss' ELSE 'draw' END FROM Match WHERE away_player_5  IS NOT NULL
    UNION ALL
    SELECT away_player_6  AS player_api_id, CASE WHEN away_team_goal > home_team_goal THEN 'win' WHEN away_team_goal < home_team_goal THEN 'loss' ELSE 'draw' END FROM Match WHERE away_player_6  IS NOT NULL
    UNION ALL
    SELECT away_player_7  AS player_api_id, CASE WHEN away_team_goal > home_team_goal THEN 'win' WHEN away_team_goal < home_team_goal THEN 'loss' ELSE 'draw' END FROM Match WHERE away_player_7  IS NOT NULL
    UNION ALL
    SELECT away_player_8  AS player_api_id, CASE WHEN away_team_goal > home_team_goal THEN 'win' WHEN away_team_goal < home_team_goal THEN 'loss' ELSE 'draw' END FROM Match WHERE away_player_8  IS NOT NULL
    UNION ALL
    SELECT away_player_9  AS player_api_id, CASE WHEN away_team_goal > home_team_goal THEN 'win' WHEN away_team_goal < home_team_goal THEN 'loss' ELSE 'draw' END FROM Match WHERE away_player_9  IS NOT NULL
    UNION ALL
    SELECT away_player_10 AS player_api_id, CASE WHEN away_team_goal > home_team_goal THEN 'win' WHEN away_team_goal < home_team_goal THEN 'loss' ELSE 'draw' END FROM Match WHERE away_player_10 IS NOT NULL
    UNION ALL
    SELECT away_player_11 AS player_api_id, CASE WHEN away_team_goal > home_team_goal THEN 'win' WHEN away_team_goal < home_team_goal THEN 'loss' ELSE 'draw' END FROM Match WHERE away_player_11 IS NOT NULL
  )
  WHERE outcome != 'draw'
),
player_counts AS (
  SELECT player_api_id,
         SUM(CASE WHEN outcome = 'win'  THEN 1 ELSE 0 END) AS win_count,
         SUM(CASE WHEN outcome = 'loss' THEN 1 ELSE 0 END) AS loss_count
  FROM player_matches
  GROUP BY player_api_id
),
top_winner AS (
  SELECT pc.player_api_id, p.player_name, pc.win_count AS match_count, 'winning' AS category
  FROM player_counts pc
  JOIN Player p ON p.player_api_id = pc.player_api_id
  ORDER BY pc.win_count DESC
  LIMIT 1
),
top_loser AS (
  SELECT pc.player_api_id, p.player_name, pc.loss_count AS match_count, 'losing' AS category
  FROM player_counts pc
  JOIN Player p ON p.player_api_id = pc.player_api_id
  ORDER BY pc.loss_count DESC
  LIMIT 1
)
SELECT player_api_id, player_name, match_count, category FROM top_winner
UNION ALL
SELECT player_api_id, player_name, match_count, category FROM top_loser
