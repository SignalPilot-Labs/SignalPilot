-- ========== OUTPUT COLUMN SPEC ==========
-- 1. overtake_type  : Overtake category label — 'R' (Retirement), 'P' (Pit), 'S' (Start), 'T' (Track)
-- 2. overtake_count : Number of times this overtake type occurred in F1 races with pit data
-- ========================================

-- INTERPRETATION: For all races where pit stop data is available, find pairs of drivers
-- where driver X was NOT behind driver Y on the previous lap (prev_pos_X <= prev_pos_Y)
-- but IS behind on the current lap (curr_pos_X > curr_pos_Y). Classify each such instance as:
--   R = overtaken driver retired on that lap
--   P = overtaken driver pitted on that lap (pit entry) OR pitted previous lap with gap < avg pit stop (pit exit)
--   S = lap 1 overtake where drivers were within 2 grid positions
--   T = all other track overtakes

-- EXPECTED: 4 rows (one per overtake type)

WITH races_with_pits AS (
    SELECT race_id FROM races_ext WHERE is_pit_data_available = 1
),
avg_pit AS (
    SELECT AVG(CAST(milliseconds AS REAL)) AS avg_ms
    FROM pit_stops ps
    JOIN races_with_pits rw ON ps.race_id = rw.race_id
    WHERE milliseconds > 0 AND milliseconds < 120000
),
pit_laps AS (
    SELECT DISTINCT race_id, driver_id, lap FROM pit_stops
    WHERE race_id IN (SELECT race_id FROM races_with_pits)
),
grid AS (
    SELECT race_id, driver_id, grid FROM results
    WHERE race_id IN (SELECT race_id FROM races_with_pits)
),
lp AS (
    SELECT lp.race_id, lp.driver_id, lp.lap, lp.position, lp.lap_type
    FROM lap_positions lp
    WHERE lp.race_id IN (SELECT race_id FROM races_with_pits)
),
rms AS (
    SELECT lt.race_id, lt.driver_id, lt.lap, lt.running_milliseconds
    FROM lap_times_ext lt
    WHERE lt.race_id IN (SELECT race_id FROM races_with_pits)
),
-- Detect overtakes: X was not behind Y on lap L-1, but is behind on lap L
-- Use driver_id < to enumerate unordered pairs, then UNION for both directions
overtakes AS (
    SELECT cx.race_id, cx.driver_id AS overtaken_id, cy.driver_id AS overtaking_id,
           cx.lap AS overtake_lap, cx.lap_type AS x_lap_type
    FROM lp cx
    JOIN lp cy ON cx.race_id = cy.race_id AND cx.lap = cy.lap AND cx.driver_id < cy.driver_id
    JOIN lp px ON cx.race_id = px.race_id AND cx.driver_id = px.driver_id AND px.lap = cx.lap - 1
    JOIN lp py ON cy.race_id = py.race_id AND cy.driver_id = py.driver_id AND py.lap = cy.lap - 1
    WHERE px.position <= py.position AND cx.position > cy.position
    UNION ALL
    SELECT cx.race_id, cy.driver_id AS overtaken_id, cx.driver_id AS overtaking_id,
           cx.lap AS overtake_lap, cy.lap_type AS x_lap_type
    FROM lp cx
    JOIN lp cy ON cx.race_id = cy.race_id AND cx.lap = cy.lap AND cx.driver_id < cy.driver_id
    JOIN lp px ON cx.race_id = px.race_id AND cx.driver_id = px.driver_id AND px.lap = cx.lap - 1
    JOIN lp py ON cy.race_id = py.race_id AND cy.driver_id = py.driver_id AND py.lap = cy.lap - 1
    WHERE py.position <= px.position AND cy.position > cx.position
),
-- Enrich with classification signals via LEFT JOINs (avoids correlated subqueries)
enriched AS (
    SELECT
        o.*,
        pe.driver_id IS NOT NULL AS is_pit_entry,
        pp.driver_id IS NOT NULL AS is_pit_prev,
        ABS(COALESCE(rm_x.running_milliseconds, 0) - COALESCE(rm_y.running_milliseconds, 0)) AS ms_gap,
        (SELECT avg_ms FROM avg_pit) AS avg_pit_ms,
        ABS(COALESCE(gx.grid, 99) - COALESCE(gy.grid, 99)) AS grid_diff
    FROM overtakes o
    LEFT JOIN pit_laps pe ON o.race_id = pe.race_id AND o.overtaken_id = pe.driver_id AND pe.lap = o.overtake_lap
    LEFT JOIN pit_laps pp ON o.race_id = pp.race_id AND o.overtaken_id = pp.driver_id AND pp.lap = o.overtake_lap - 1
    LEFT JOIN rms rm_x ON o.race_id = rm_x.race_id AND o.overtaken_id = rm_x.driver_id AND rm_x.lap = o.overtake_lap - 1
    LEFT JOIN rms rm_y ON o.race_id = rm_y.race_id AND o.overtaking_id = rm_y.driver_id AND rm_y.lap = o.overtake_lap - 1
    LEFT JOIN grid gx ON o.race_id = gx.race_id AND o.overtaken_id = gx.driver_id
    LEFT JOIN grid gy ON o.race_id = gy.race_id AND o.overtaking_id = gy.driver_id
)
SELECT
    CASE
        WHEN x_lap_type LIKE 'Retirement%' THEN 'R'
        WHEN is_pit_entry THEN 'P'
        WHEN is_pit_prev AND ms_gap < avg_pit_ms THEN 'P'
        WHEN overtake_lap = 1 AND grid_diff <= 2 THEN 'S'
        ELSE 'T'
    END AS overtake_type,
    COUNT(*) AS overtake_count
FROM enriched
GROUP BY 1
ORDER BY 1
