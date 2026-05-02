-- ========== OUTPUT COLUMN SPEC ==========
-- 1. Month   : integer (1-12) representing the calendar month
-- 2. Y2016   : count of delivered orders in that month for year 2016
-- 3. Y2017   : count of delivered orders in that month for year 2017
-- 4. Y2018   : count of delivered orders in that month for year 2018
-- ========================================
-- EXPECTED: 12 rows (one per month), 4 columns
-- INTERPRETATION: Count orders where status='delivered', grouped by month (row) and year (column) for 2016/2017/2018

SELECT
    CAST(strftime('%m', order_purchase_timestamp) AS INTEGER) AS Month,
    SUM(CASE WHEN strftime('%Y', order_purchase_timestamp) = '2016' THEN 1 ELSE 0 END) AS Y2016,
    SUM(CASE WHEN strftime('%Y', order_purchase_timestamp) = '2017' THEN 1 ELSE 0 END) AS Y2017,
    SUM(CASE WHEN strftime('%Y', order_purchase_timestamp) = '2018' THEN 1 ELSE 0 END) AS Y2018
FROM olist_orders
WHERE order_status = 'delivered'
  AND strftime('%Y', order_purchase_timestamp) IN ('2016', '2017', '2018')
GROUP BY CAST(strftime('%m', order_purchase_timestamp) AS INTEGER)
ORDER BY Month
