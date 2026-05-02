-- ========== OUTPUT COLUMN SPEC ==========
-- 1. avg_career_span : float — average career span across all players,
--                      where career_span = ROUND(|Δyears|,2) + ROUND(|Δmonths|/12,2) + ROUND(|Δdays|/365,2)
-- ========================================
-- EXPECTED: 1 row (single aggregate value)
-- INTERPRETATION: For every player with both debut and final_game dates,
--   extract year/month/day parts of each date, take absolute differences,
--   round each part to 2 decimal places, sum them to get career span in years,
--   then average across all players and round to 2 decimal places.

WITH career_spans AS (
  SELECT
    player_id,
    ROUND(ABS(CAST(strftime('%Y', final_game) AS INTEGER) - CAST(strftime('%Y', debut) AS INTEGER)), 2) +
    ROUND(ABS(CAST(strftime('%m', final_game) AS INTEGER) - CAST(strftime('%m', debut) AS INTEGER)) / 12.0, 2) +
    ROUND(ABS(CAST(strftime('%d', final_game) AS INTEGER) - CAST(strftime('%d', debut) AS INTEGER)) / 365.0, 2) AS career_span
  FROM player
  WHERE debut IS NOT NULL AND debut != '' AND final_game IS NOT NULL AND final_game != ''
)
SELECT ROUND(AVG(career_span), 2) AS avg_career_span
FROM career_spans
