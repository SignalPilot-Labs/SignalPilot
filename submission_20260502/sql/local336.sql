-- ========== OUTPUT COLUMN SPEC ==========
-- 1. category       : Overtake category label (Retirement/Pit Stop/Start/Track)
-- 2. overtake_count : Count of overtakes in that category during laps 1-5 across all races
-- ========================================
-- INTERPRETATION: Compute overtakes (position swaps between consecutive laps)
-- for laps 1-5 across all races, categorized by:
--   R (Retirement): overtaken driver retired on the same lap
--   P (Pit Stop): overtaken driver pitted on same lap (entry) or previous lap (exit)
--   S (Start): lap 1 overtake, two drivers within 2 grid positions
--   T (Track): standard on-track pass (default)
-- EXPECTED: 4 rows (one per category)

WITH all_positions AS (
    -- Grid positions (lap 0) from results
    SELECT race_id, driver_id, 0 AS lap, grid AS position, 'Grid' AS lap_type
    FROM results WHERE grid > 0
    UNION ALL
    -- Race and retirement positions for laps 1-5
    SELECT race_id, driver_id, lap, position, lap_type
    FROM lap_positions
    WHERE lap BETWEEN 1 AND 5
    AND (lap_type = 'Race' OR lap_type LIKE 'Retirement%')
),
-- Add previous lap position via LAG for each driver
driver_laps AS (
    SELECT
        race_id, driver_id, lap, position, lap_type,
        LAG(position) OVER (PARTITION BY race_id, driver_id ORDER BY lap) AS prev_pos
    FROM all_positions
),
-- Drivers who improved position (potential overtakers) - must be still racing
improved AS (
    SELECT race_id, driver_id, lap, position, prev_pos
    FROM driver_laps
    WHERE lap BETWEEN 1 AND 5 AND lap_type = 'Race'
    AND prev_pos IS NOT NULL AND position < prev_pos
),
-- Drivers who fell back in position (potentially overtaken) - race or retirement
worsened AS (
    SELECT race_id, driver_id, lap, position, prev_pos, lap_type
    FROM driver_laps
    WHERE lap BETWEEN 1 AND 5
    AND (lap_type = 'Race' OR lap_type LIKE 'Retirement%')
    AND prev_pos IS NOT NULL AND position > prev_pos
),
-- Identify actual overtakes: A was behind B, now A is ahead of B
overtakes AS (
    SELECT
        a.race_id,
        a.driver_id AS overtaker_id,
        b.driver_id AS overtaken_id,
        a.lap AS overtake_lap,
        a.lap - 1 AS prev_lap,
        b.lap_type AS overtaken_type
    FROM improved a
    JOIN worsened b ON a.race_id = b.race_id AND a.lap = b.lap
        AND a.driver_id != b.driver_id
        AND a.prev_pos > b.prev_pos   -- A was behind B on previous lap
        AND a.position < b.position   -- A is now ahead of B on current lap
),
-- Pre-compute pit stop laps for efficiency
pit_lap_data AS (
    SELECT DISTINCT race_id, driver_id, lap
    FROM pit_stops
    WHERE lap BETWEEN 1 AND 5
),
-- Grid positions for Start classification
grid_data AS (
    SELECT race_id, driver_id, grid AS grid_pos
    FROM results WHERE grid > 0
),
-- Categorize each overtake (priority: R > P > S > T)
categorized AS (
    SELECT
        CASE
            -- R: overtaken driver retired on the same lap
            WHEN o.overtaken_type LIKE 'Retirement%' THEN 'Retirement'
            -- P: overtaken driver pitted on same lap (entry) or previous lap (exit)
            WHEN pl1.driver_id IS NOT NULL OR pl2.driver_id IS NOT NULL THEN 'Pit Stop'
            -- S: lap 1, both drivers within 2 grid positions of each other
            WHEN o.overtake_lap = 1
                 AND ga.driver_id IS NOT NULL AND gb.driver_id IS NOT NULL
                 AND ABS(ga.grid_pos - gb.grid_pos) <= 2 THEN 'Start'
            -- T: standard on-track pass
            ELSE 'Track'
        END AS category
    FROM overtakes o
    -- Pit entry: overtaken driver pitted on the overtake lap
    LEFT JOIN pit_lap_data pl1 ON pl1.race_id = o.race_id AND pl1.driver_id = o.overtaken_id AND pl1.lap = o.overtake_lap
    -- Pit exit: overtaken driver pitted on the previous lap
    LEFT JOIN pit_lap_data pl2 ON pl2.race_id = o.race_id AND pl2.driver_id = o.overtaken_id AND pl2.lap = o.prev_lap
    -- Grid positions for Start classification (only used for lap 1)
    LEFT JOIN grid_data ga ON ga.race_id = o.race_id AND ga.driver_id = o.overtaker_id AND o.overtake_lap = 1
    LEFT JOIN grid_data gb ON gb.race_id = o.race_id AND gb.driver_id = o.overtaken_id AND o.overtake_lap = 1
)
SELECT category, COUNT(*) AS overtake_count
FROM categorized
GROUP BY category
ORDER BY category
