-- OUTPUT COLUMN SPEC:
-- 1. employeeid           : employee's integer ID
-- 2. late_orders          : count of orders where shippeddate >= requireddate
-- 3. late_order_percentage: late_orders / total_orders * 100

-- INTERPRETATION: Among employees with >50 total orders, find top 3 by late-order %.
-- Late = shippeddate >= requireddate. NULL shippeddate = not late (not yet shipped).
-- EXPECTED: 3 rows

WITH order_stats AS (
    SELECT
        employeeid,
        COUNT(*) AS total_orders,
        SUM(CASE WHEN shippeddate >= requireddate THEN 1 ELSE 0 END) AS late_orders
    FROM orders
    GROUP BY employeeid
    HAVING COUNT(*) > 50
)
SELECT
    employeeid,
    late_orders,
    CAST(late_orders AS REAL) * 100.0 / total_orders AS late_order_percentage
FROM order_stats
ORDER BY late_order_percentage DESC
LIMIT 3;
