-- Top 10 teams with the most wins across the league
-- A win is counted when a team's goals exceed the opponent's goals,
-- regardless of whether they were the home or away team.
WITH team_wins AS (
    SELECT home_team_api_id AS team_api_id, COUNT(*) AS wins
    FROM Match
    WHERE home_team_goal > away_team_goal
    GROUP BY home_team_api_id
    UNION ALL
    SELECT away_team_api_id AS team_api_id, COUNT(*) AS wins
    FROM Match
    WHERE away_team_goal > home_team_goal
    GROUP BY away_team_api_id
),
total_wins AS (
    SELECT team_api_id, SUM(wins) AS total_wins
    FROM team_wins
    GROUP BY team_api_id
)
SELECT ROW_NUMBER() OVER (ORDER BY tw.total_wins DESC) AS rank,
       t.team_api_id,
       t.team_long_name,
       tw.total_wins
FROM total_wins tw
JOIN Team t ON t.team_api_id = tw.team_api_id
ORDER BY tw.total_wins DESC
LIMIT 10;
