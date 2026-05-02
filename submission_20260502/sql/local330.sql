-- ========== OUTPUT COLUMN SPEC ==========
-- 1. path          : web page path (the page being analyzed)
-- 2. session_count : number of unique sessions where this page is a landing page, exit page, or both
-- ========================================

-- INTERPRETATION: For each session, find the first page visited (landing) and last page visited (exit).
-- For each page, count distinct sessions where it appears as landing OR exit (or both),
-- counting each session only once per page via UNION deduplication.

-- EXPECTED: ~9 rows (one per unique page path)

WITH session_bounds AS (
    SELECT
        session,
        MIN(stamp) AS first_stamp,
        MAX(stamp) AS last_stamp
    FROM activity_log
    GROUP BY session
),
landing AS (
    SELECT al.session, al.path
    FROM activity_log al
    JOIN session_bounds sb ON al.session = sb.session AND al.stamp = sb.first_stamp
),
exit_page AS (
    SELECT al.session, al.path
    FROM activity_log al
    JOIN session_bounds sb ON al.session = sb.session AND al.stamp = sb.last_stamp
),
combined AS (
    SELECT session, path FROM landing
    UNION
    SELECT session, path FROM exit_page
)
SELECT path, COUNT(*) AS session_count
FROM combined
GROUP BY path
ORDER BY session_count DESC
