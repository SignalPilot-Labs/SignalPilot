-- ========== OUTPUT COLUMN SPEC ==========
-- 1. rank                : explicit rank position (1-5) by avg_daily_deliveries
-- 2. driver_id           : the driver's primary key ID
-- 3. driver_modal        : type of transport modal (BIKER, MOTOBOY, etc.)
-- 4. driver_type         : employment type (FREELANCE, LOGISTIC OPERATOR, etc.)
-- 5. avg_daily_deliveries: average number of deliveries per calendar day (ranking metric)
-- ========================================
-- INTERPRETATION: Join deliveries → orders (via delivery_order_id) to get dates,
--   count deliveries per driver per day, average those daily counts per driver,
--   return top 5 by highest average (excluding NULL driver_ids).
-- EXPECTED: 5 rows

WITH daily_counts AS (
    SELECT
        d.driver_id,
        o.order_created_year,
        o.order_created_month,
        o.order_created_day,
        COUNT(d.delivery_id) AS daily_deliveries
    FROM deliveries d
    JOIN orders o ON d.delivery_order_id = o.delivery_order_id
    WHERE d.driver_id IS NOT NULL
    GROUP BY d.driver_id, o.order_created_year, o.order_created_month, o.order_created_day
),
driver_avg AS (
    SELECT
        driver_id,
        AVG(daily_deliveries) AS avg_daily_deliveries
    FROM daily_counts
    GROUP BY driver_id
    ORDER BY avg_daily_deliveries DESC
    LIMIT 5
)
SELECT
    ROW_NUMBER() OVER (ORDER BY da.avg_daily_deliveries DESC) AS rank,
    da.driver_id,
    dr.driver_modal,
    dr.driver_type,
    da.avg_daily_deliveries
FROM driver_avg da
JOIN drivers dr ON da.driver_id = dr.driver_id
ORDER BY da.avg_daily_deliveries DESC;
