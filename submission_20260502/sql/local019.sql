WITH shortest AS (
  SELECT m.winner_id, m.loser_id
  FROM Matches m
  JOIN Belts b ON m.title_id = CAST(b.id AS TEXT)
  WHERE b.name LIKE '%NXT%'
    AND m.title_change = 0
    AND m.duration != ''
    AND m.duration IS NOT NULL
  ORDER BY
    (CAST(substr(m.duration, 1, instr(m.duration, ':') - 1) AS INTEGER) * 60 +
     CAST(substr(m.duration, instr(m.duration, ':') + 1) AS INTEGER)) ASC
  LIMIT 1
)
SELECT w1.name AS winner_name, w2.name AS loser_name
FROM shortest s
JOIN Wrestlers w1 ON CAST(w1.id AS TEXT) = s.winner_id
JOIN Wrestlers w2 ON CAST(w2.id AS TEXT) = s.loser_id;
