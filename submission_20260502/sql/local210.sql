-- ========== OUTPUT COLUMN SPEC ==========
-- 1. hub_id              : hub's primary key (INTEGER)
-- 2. hub_name            : hub's descriptive name (VARCHAR)
-- 3. finished_orders_feb : count of FINISHED orders in February per hub
-- 4. finished_orders_mar : count of FINISHED orders in March per hub
-- 5. pct_increase        : percentage increase from Feb to March
-- ========================================

-- INTERPRETATION: Find hubs where count of FINISHED orders in March 2021 exceeds
-- count of FINISHED orders in February 2021 by more than 20%.
-- EXPECTED: ~20 rows (hubs passing the >20% growth filter)

WITH hub_monthly AS (
    SELECT
        h.hub_id,
        h.hub_name,
        COUNT(CASE WHEN o.order_created_month = 2 THEN 1 END) AS finished_orders_feb,
        COUNT(CASE WHEN o.order_created_month = 3 THEN 1 END) AS finished_orders_mar
    FROM orders o
    JOIN stores s ON o.store_id = s.store_id
    JOIN hubs h ON s.hub_id = h.hub_id
    WHERE o.order_status = 'FINISHED'
      AND o.order_created_year = 2021
    GROUP BY h.hub_id, h.hub_name
)
SELECT
    hub_id,
    hub_name,
    finished_orders_feb,
    finished_orders_mar,
    ROUND(CAST(finished_orders_mar - finished_orders_feb AS REAL) / finished_orders_feb * 100, 2) AS pct_increase
FROM hub_monthly
WHERE finished_orders_feb > 0
  AND CAST(finished_orders_mar - finished_orders_feb AS REAL) / finished_orders_feb > 0.20
ORDER BY pct_increase DESC
