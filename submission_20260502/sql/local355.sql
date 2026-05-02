-- ========== OUTPUT COLUMN SPEC ==========
-- 1. avg_first_round : average of the first round missed across all qualifying hiatuses
-- 2. avg_last_round  : average of the last round missed across all qualifying hiatuses
-- ========================================
-- EXPECTED: 1 row (two aggregate averages)
-- INTERPRETATION: For each driver-year, find gaps between consecutive positive drive_id stints.
-- A qualifying hiatus has: races_missed < 3, constructor changed before vs after gap.
-- Return overall averages of first and last missed rounds across all qualifying hiatuses.

WITH ordered_drives AS (
  SELECT
    year, driver_id, drive_id, constructor_id, first_round, last_round,
    LAG(last_round) OVER (PARTITION BY year, driver_id ORDER BY drive_id) AS prev_last_round,
    LAG(constructor_id) OVER (PARTITION BY year, driver_id ORDER BY drive_id) AS prev_constructor_id
  FROM drives
  WHERE drive_id > 0
),
hiatuses AS (
  SELECT
    prev_last_round + 1 AS first_missed_round,
    first_round - 1 AS last_missed_round
  FROM ordered_drives
  WHERE prev_last_round IS NOT NULL
    AND first_round - prev_last_round - 1 > 0   -- gap exists
    AND first_round - prev_last_round - 1 < 3   -- fewer than 3 races missed
    AND prev_constructor_id != constructor_id    -- team switch
)
SELECT
  AVG(first_missed_round) AS avg_first_round,
  AVG(last_missed_round)  AS avg_last_round
FROM hiatuses
