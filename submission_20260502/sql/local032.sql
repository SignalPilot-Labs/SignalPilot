-- ========== OUTPUT COLUMN SPEC ==========
-- 1. achievement : label describing the category (e.g., "Highest number of distinct customer unique IDs")
-- 2. seller_id   : the seller's ID for that category
-- 3. value       : the corresponding metric value (count or sum)
-- ========================================
-- EXPECTED: 4 rows (one per category)
-- INTERPRETATION: For delivered orders only, find the top seller in 4 categories:
--   1. Most distinct customer_unique_ids served
--   2. Highest total profit (SUM of price - freight_value)
--   3. Most distinct orders fulfilled
--   4. Most 5-star reviews received

WITH delivered AS (
    SELECT order_id, customer_id
    FROM olist_orders
    WHERE order_status = 'delivered'
),
seller_customers AS (
    SELECT oi.seller_id, COUNT(DISTINCT c.customer_unique_id) AS metric_value
    FROM olist_order_items oi
    JOIN delivered d ON oi.order_id = d.order_id
    JOIN olist_customers c ON d.customer_id = c.customer_id
    GROUP BY oi.seller_id
),
seller_profit AS (
    SELECT oi.seller_id, SUM(oi.price - oi.freight_value) AS metric_value
    FROM olist_order_items oi
    JOIN delivered d ON oi.order_id = d.order_id
    GROUP BY oi.seller_id
),
seller_orders AS (
    SELECT oi.seller_id, COUNT(DISTINCT oi.order_id) AS metric_value
    FROM olist_order_items oi
    JOIN delivered d ON oi.order_id = d.order_id
    GROUP BY oi.seller_id
),
seller_5star AS (
    SELECT oi.seller_id, COUNT(DISTINCT r.review_id) AS metric_value
    FROM olist_order_items oi
    JOIN delivered d ON oi.order_id = d.order_id
    JOIN olist_order_reviews r ON oi.order_id = r.order_id
    WHERE r.review_score = 5
    GROUP BY oi.seller_id
)
SELECT 'Highest number of distinct customer unique IDs' AS achievement, seller_id, CAST(metric_value AS REAL) AS value
FROM seller_customers WHERE metric_value = (SELECT MAX(metric_value) FROM seller_customers)
UNION ALL
SELECT 'Highest profit (price minus freight value)' AS achievement, seller_id, metric_value AS value
FROM seller_profit WHERE metric_value = (SELECT MAX(metric_value) FROM seller_profit)
UNION ALL
SELECT 'Highest number of distinct orders' AS achievement, seller_id, CAST(metric_value AS REAL) AS value
FROM seller_orders WHERE metric_value = (SELECT MAX(metric_value) FROM seller_orders)
UNION ALL
SELECT 'Most 5-star ratings' AS achievement, seller_id, CAST(metric_value AS REAL) AS value
FROM seller_5star WHERE metric_value = (SELECT MAX(metric_value) FROM seller_5star);
