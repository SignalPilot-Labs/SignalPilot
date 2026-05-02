-- ========== OUTPUT COLUMN SPEC ==========
-- 1. unique_sessions : COUNT of distinct sessions that visited /regist/input
--                      BEFORE /regist/confirm (in that order, by stamp)
-- ========================================

-- EXPECTED: 1 row with a single integer count
-- INTERPRETATION: Count sessions where /regist/input visit (a.stamp) is strictly
--   earlier than a /regist/confirm visit (b.stamp) within the same session.

SELECT COUNT(DISTINCT a.session) AS unique_sessions
FROM form_log a
JOIN form_log b ON a.session = b.session
WHERE a.path = '/regist/input'
  AND b.path = '/regist/confirm'
  AND a.stamp < b.stamp
