-- ========== OUTPUT COLUMN SPEC ==========
-- 1. full_name : driver's full name (forename || ' ' || surname)
-- ========================================
-- INTERPRETATION: Find drivers where total times being overtaken on track (position worsened)
-- exceeds total times overtaking others (position improved), using only Race laps.
-- Exclusions:
--   1. First lap: auto-excluded (lap=1 Race row has no previous Race row → LAG=NULL)
--   2. Pit stop entry: transition at the pit stop lap for the pitting driver
--   3. Pit stop exit: transition at pit_lap+1 for the pitting driver
--   4. Retirements: transition at the retirement lap for the retiring driver
--   5. Paired approach: only count changes when BOTH gains AND losses exist in same race/lap
--      (handles retirement effects on other drivers)
-- Restricted to races with pit stop data available (2011+) for proper exclusion.
-- EXPECTED: ~13 rows (known F1 backmarker drivers from 2011+ era)

WITH race_laps AS (
    SELECT lp.race_id, lp.driver_id, lp.lap, lp.position
    FROM lap_positions lp
    JOIN races_ext re ON re.race_id = lp.race_id AND re.is_pit_data_available = 1
    WHERE lp.lap_type = 'Race'
),
pos_changes AS (
    SELECT
        race_id, driver_id, lap,
        position - LAG(position) OVER (PARTITION BY race_id, driver_id ORDER BY lap) AS pos_change,
        LAG(lap) OVER (PARTITION BY race_id, driver_id ORDER BY lap) AS prev_lap
    FROM race_laps
),
pit_flagged AS (
    -- Flag both pit entry lap (lap) and pit exit lap (lap+1) for each pit stop
    SELECT race_id, driver_id, lap AS flagged_lap FROM pit_stops
    UNION ALL
    SELECT race_id, driver_id, lap + 1 AS flagged_lap FROM pit_stops
),
retirement_laps AS (
    -- Flag the retirement lap for each retiring driver
    SELECT DISTINCT race_id, driver_id, lap AS retirement_lap FROM retirements
),
valid_changes AS (
    SELECT pc.race_id, pc.driver_id, pc.lap, pc.pos_change
    FROM pos_changes pc
    LEFT JOIN pit_flagged pf ON pf.race_id = pc.race_id AND pf.driver_id = pc.driver_id AND pf.flagged_lap = pc.lap
    LEFT JOIN retirement_laps rl ON rl.race_id = pc.race_id AND rl.driver_id = pc.driver_id AND rl.retirement_lap = pc.lap
    WHERE pc.pos_change IS NOT NULL       -- has previous Race row (excludes lap 1)
      AND pc.prev_lap = pc.lap - 1        -- consecutive laps only (no gaps)
      AND pc.lap > 1                      -- explicitly exclude first lap transitions
      AND pf.flagged_lap IS NULL          -- exclude pit stop entry and exit laps
      AND rl.retirement_lap IS NULL       -- exclude retirement laps
),
-- Paired approach: only count changes in laps where BOTH gains AND losses exist
-- This handles retirement effects: retirement-only laps have only gains, no losses
transition_check AS (
    SELECT race_id, lap,
        SUM(CASE WHEN pos_change < 0 THEN 1 ELSE 0 END) AS has_gains,
        SUM(CASE WHEN pos_change > 0 THEN 1 ELSE 0 END) AS has_losses
    FROM valid_changes
    GROUP BY race_id, lap
),
paired_changes AS (
    SELECT vc.race_id, vc.driver_id, vc.lap, vc.pos_change
    FROM valid_changes vc
    JOIN transition_check tc ON tc.race_id = vc.race_id AND tc.lap = vc.lap
    WHERE tc.has_gains > 0 AND tc.has_losses > 0 AND vc.pos_change != 0
),
driver_stats AS (
    SELECT
        driver_id,
        SUM(CASE WHEN pos_change < 0 THEN 1 ELSE 0 END) AS times_overtook,
        SUM(CASE WHEN pos_change > 0 THEN 1 ELSE 0 END) AS times_overtaken
    FROM paired_changes
    GROUP BY driver_id
)
SELECT
    d.forename || ' ' || d.surname AS full_name
FROM driver_stats ds
JOIN drivers d ON d.driver_id = ds.driver_id
WHERE ds.times_overtaken > ds.times_overtook
ORDER BY full_name;
