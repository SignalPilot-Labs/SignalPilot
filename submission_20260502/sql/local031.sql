-- INTERPRETATION: Find the year (2016/2017/2018) with lowest total delivered orders,
-- then return the highest single-month delivered order count within that year.
-- EXPECTED: 1 row × 1 column

WITH annual_counts AS (
    SELECT
        strftime('%Y', order_purchase_timestamp) AS year,
        COUNT(*) AS annual_delivered_orders
    FROM olist_orders
    WHERE order_status = 'delivered'
      AND strftime('%Y', order_purchase_timestamp) IN ('2016', '2017', '2018')
    GROUP BY year
),
lowest_year AS (
    SELECT year
    FROM annual_counts
    ORDER BY annual_delivered_orders ASC
    LIMIT 1
),
monthly_counts AS (
    SELECT
        strftime('%Y-%m', order_purchase_timestamp) AS year_month,
        COUNT(*) AS monthly_delivered_orders
    FROM olist_orders
    WHERE order_status = 'delivered'
      AND strftime('%Y', order_purchase_timestamp) = (SELECT year FROM lowest_year)
    GROUP BY year_month
)
SELECT MAX(monthly_delivered_orders) AS highest_monthly_delivered_orders
FROM monthly_counts
