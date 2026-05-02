SELECT CAST(SUM(CASE WHEN health = 'Good' THEN 1 ELSE 0 END) AS REAL) * 100.0 / COUNT(*) AS percentage
FROM trees
WHERE boroname = 'Bronx'
