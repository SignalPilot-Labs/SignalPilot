-- EXPECTED: 1 row (count result)
-- INTERPRETATION: Count actors who co-acted with a direct Shahrukh Khan co-actor,
-- but who never directly acted with Shahrukh Khan themselves.
-- Note: PIDs in M_Cast have a leading space, so TRIM() is applied throughout.

WITH shahrukh_movies AS (
  SELECT MID FROM M_Cast WHERE TRIM(PID) = 'nm0451321'
),
shahrukh_coactors AS (
  SELECT DISTINCT TRIM(mc.PID) AS PID
  FROM M_Cast mc
  JOIN shahrukh_movies sm ON mc.MID = sm.MID
  WHERE TRIM(mc.PID) != 'nm0451321'
),
coactor_movies AS (
  SELECT DISTINCT mc.MID
  FROM M_Cast mc
  JOIN shahrukh_coactors sc ON TRIM(mc.PID) = sc.PID
),
shahrukh_number_2 AS (
  SELECT DISTINCT TRIM(mc.PID) AS PID
  FROM M_Cast mc
  JOIN coactor_movies cm ON mc.MID = cm.MID
  WHERE TRIM(mc.PID) != 'nm0451321'
    AND TRIM(mc.PID) NOT IN (SELECT PID FROM shahrukh_coactors)
)
SELECT COUNT(*) AS shahrukh_number_2_count FROM shahrukh_number_2
