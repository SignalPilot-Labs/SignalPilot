-- ========== OUTPUT COLUMN SPEC ==========
-- 1. customer_unique_id : unique customer identifier (grouped by this)
-- 2. order_count        : number of orders placed by the customer
-- 3. avg_payment        : average total payment per order (ORDER BY this DESC, LIMIT 3)
-- 4. lifespan_weeks     : (max_purchase - min_purchase) in days / 7, min 1.0
-- ========================================
-- EXPECTED: 3 rows (top 3 customers by avg payment)
-- INTERPRETATION: group by customer_unique_id (not customer_id) since one unique
--   customer can have multiple customer_ids; sum payments per order first, then
--   average across orders; lifespan = days diff / 7, set to 1.0 if < 7 days

WITH order_totals AS (
    SELECT
        o.customer_id,
        o.order_id,
        o.order_purchase_timestamp,
        SUM(op.payment_value) AS order_payment
    FROM orders o
    JOIN order_payments op ON o.order_id = op.order_id
    GROUP BY o.customer_id, o.order_id, o.order_purchase_timestamp
),
customer_stats AS (
    SELECT
        c.customer_unique_id,
        COUNT(ot.order_id) AS order_count,
        AVG(ot.order_payment) AS avg_payment,
        (julianday(MAX(ot.order_purchase_timestamp)) - julianday(MIN(ot.order_purchase_timestamp))) AS lifespan_days
    FROM customers c
    JOIN order_totals ot ON c.customer_id = ot.customer_id
    GROUP BY c.customer_unique_id
)
SELECT
    customer_unique_id,
    order_count,
    avg_payment,
    CASE
        WHEN lifespan_days < 7 THEN 1.0
        ELSE lifespan_days / 7.0
    END AS lifespan_weeks
FROM customer_stats
ORDER BY avg_payment DESC
LIMIT 3;
