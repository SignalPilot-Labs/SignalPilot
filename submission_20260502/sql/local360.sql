-- INTERPRETATION: For each session with a '/detail' or '/complete' event, count events
-- that occurred BEFORE the first such event AND have non-empty search_type.
-- Find sessions with minimum such count, return their pre-trigger events (distinct path + search_type).
-- EXPECTED: 2 rows for session 36dd0df7 (minimum count = 7 among sessions with non-empty search events)

WITH first_trigger AS (
    -- Find the first '/detail' or '/complete' event per session
    SELECT session, MIN(stamp) AS first_trigger_stamp
    FROM activity_log
    WHERE path IN ('/detail', '/detail/', '/complete')
    GROUP BY session
),
pre_trigger_non_empty AS (
    -- Events before the first trigger with non-empty search_type
    SELECT a.session, a.path, a.search_type
    FROM activity_log a
    JOIN first_trigger f ON a.session = f.session
    WHERE a.stamp < f.first_trigger_stamp
      AND a.search_type != ''
),
session_counts AS (
    -- Count pre-trigger non-empty search_type events per session
    SELECT session, COUNT(*) AS pre_count
    FROM pre_trigger_non_empty
    GROUP BY session
),
min_count AS (
    SELECT MIN(pre_count) AS min_pre_count
    FROM session_counts
)
SELECT DISTINCT p.session, p.path, p.search_type
FROM pre_trigger_non_empty p
JOIN session_counts sc ON p.session = sc.session
JOIN min_count mc ON sc.pre_count = mc.min_pre_count
ORDER BY p.session, p.path, p.search_type
