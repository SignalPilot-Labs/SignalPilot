-- ========== OUTPUT COLUMN SPEC ==========
-- 1. path  : the third page path visited after two consecutive /detail visits (normalized, no trailing slash)
-- 2. count : number of times each third-page visit occurs in this pattern
-- ========================================
-- EXPECTED: 3 rows (top 3 distinct third-page visits)
-- INTERPRETATION: For each row in activity_log, use LAG to get the previous two page paths per session
--                 (ordered by stamp). Filter where prev[n-2] = '/detail' AND prev[n-1] = '/detail'.
--                 Count occurrences of each third page path and return top 3.
--                 Normalize trailing slashes (RTRIM '/' except for the root '/' path itself).

WITH ranked AS (
  SELECT
    session,
    stamp,
    CASE WHEN path = '/' THEN '/' ELSE RTRIM(path, '/') END AS path,
    LAG(CASE WHEN path = '/' THEN '/' ELSE RTRIM(path, '/') END, 1) OVER (PARTITION BY session ORDER BY stamp) AS prev1_path,
    LAG(CASE WHEN path = '/' THEN '/' ELSE RTRIM(path, '/') END, 2) OVER (PARTITION BY session ORDER BY stamp) AS prev2_path
  FROM activity_log
)
SELECT
  path,
  COUNT(*) AS count
FROM ranked
WHERE prev1_path = '/detail' AND prev2_path = '/detail'
GROUP BY path
ORDER BY count DESC
LIMIT 3;
