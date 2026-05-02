-- ========== OUTPUT COLUMN SPEC ==========
-- 1. store_id         : ID of the store with the highest total orders
-- 2. store_name       : Name of the store with the highest total orders
-- 3. total_orders     : Total count of orders for that store
-- 4. delivered_orders : Count of distinct orders that appear in deliveries with 'DELIVERED' status
-- 5. delivered_ratio  : delivered_orders / total_orders
-- ========================================

-- INTERPRETATION: Find the store with the most orders (joining orders + stores),
-- then compute the ratio of orders that have a matching delivery with status='DELIVERED'
-- to the total orders for that store.
-- NOTE: deliveries table has fan-out (multiple rows per delivery_order_id),
-- so we use IN subquery to count distinct orders that appear at least once as DELIVERED.

-- EXPECTED: 1 row (the single top store)

WITH store_orders AS (
    SELECT o.store_id, s.store_name, COUNT(*) AS total_orders
    FROM orders o
    JOIN stores s ON o.store_id = s.store_id
    GROUP BY o.store_id, s.store_name
    ORDER BY total_orders DESC
    LIMIT 1
),
top_store_delivered AS (
    SELECT COUNT(DISTINCT o.order_id) AS delivered_orders
    FROM orders o
    WHERE o.store_id = (SELECT store_id FROM store_orders)
      AND o.delivery_order_id IN (
          SELECT delivery_order_id FROM deliveries WHERE delivery_status = 'DELIVERED'
      )
)
SELECT
    so.store_id,
    so.store_name,
    so.total_orders,
    tsd.delivered_orders,
    CAST(tsd.delivered_orders AS REAL) / so.total_orders AS delivered_ratio
FROM store_orders so, top_store_delivered tsd
