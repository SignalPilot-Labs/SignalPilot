-- ========== OUTPUT COLUMN SPEC ==========
-- 1. sum_of_moving_averages : sum of four 5-day symmetric moving averages of
--    predicted toy sales for Dec 5, 6, 7, 8, 2018
-- ==========================================

-- INTERPRETATION:
-- 1. Get daily toy sales counts (product_category_name = 'brinquedos') from 2017-01-01 to 2018-08-29
-- 2. Fit a simple linear regression: y = beta0 + beta1 * x, where x = days since 2017-01-01
-- 3. Predict toy sales for Dec 3-10, 2018 (need these for 5-day symmetric MAs of Dec 5-8)
-- 4. For each of Dec 5, 6, 7, 8: compute symmetric 5-day MA = avg(day-2, day-1, day, day+1, day+2)
-- 5. Return SUM of those four MAs
-- EXPECTED: 1 row (the sum)

WITH daily_sales AS (
  SELECT
    CAST(julianday(date(o.order_purchase_timestamp)) - julianday('2017-01-01') AS REAL) AS x,
    COUNT(*) AS y
  FROM orders o
  JOIN order_items oi ON o.order_id = oi.order_id
  JOIN products p ON oi.product_id = p.product_id
  WHERE p.product_category_name = 'brinquedos'
    AND date(o.order_purchase_timestamp) >= '2017-01-01'
    AND date(o.order_purchase_timestamp) <= '2018-08-29'
  GROUP BY date(o.order_purchase_timestamp)
),
regression_params AS (
  SELECT
    (COUNT(*) * SUM(x * y) - SUM(x) * SUM(y)) / (COUNT(*) * SUM(x * x) - SUM(x) * SUM(x)) AS beta1,
    AVG(y) - ((COUNT(*) * SUM(x * y) - SUM(x) * SUM(y)) / (COUNT(*) * SUM(x * x) - SUM(x) * SUM(x))) * AVG(x) AS beta0
  FROM daily_sales
),
forecast_dates AS (
  SELECT date('2018-12-03', '+' || n || ' days') AS forecast_date,
         julianday(date('2018-12-03', '+' || n || ' days')) - julianday('2017-01-01') AS x_val
  FROM (SELECT 0 AS n UNION SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4
        UNION SELECT 5 UNION SELECT 6 UNION SELECT 7)
),
predictions AS (
  SELECT
    f.forecast_date,
    f.x_val,
    r.beta0 + r.beta1 * f.x_val AS predicted_sales
  FROM forecast_dates f, regression_params r
),
moving_averages AS (
  SELECT
    center.forecast_date AS target_date,
    (p1.predicted_sales + p2.predicted_sales + center.predicted_sales + p3.predicted_sales + p4.predicted_sales) / 5.0 AS ma5
  FROM predictions center
  JOIN predictions p1 ON julianday(p1.forecast_date) = julianday(center.forecast_date) - 2
  JOIN predictions p2 ON julianday(p2.forecast_date) = julianday(center.forecast_date) - 1
  JOIN predictions p3 ON julianday(p3.forecast_date) = julianday(center.forecast_date) + 1
  JOIN predictions p4 ON julianday(p4.forecast_date) = julianday(center.forecast_date) + 2
  WHERE center.forecast_date IN ('2018-12-05','2018-12-06','2018-12-07','2018-12-08')
)
SELECT SUM(ma5) AS sum_of_moving_averages
FROM moving_averages;
