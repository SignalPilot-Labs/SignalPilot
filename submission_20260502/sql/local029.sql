WITH delivered_orders AS (
    SELECT
        o.order_id,
        c.customer_unique_id,
        c.customer_city,
        c.customer_state
    FROM olist_orders o
    JOIN olist_customers c ON o.customer_id = c.customer_id
    WHERE o.order_status = 'delivered'
),
payment_agg AS (
    SELECT
        order_id,
        SUM(payment_value) AS order_payment_value
    FROM olist_order_payments
    GROUP BY order_id
),
customer_stats AS (
    SELECT
        d.customer_unique_id,
        COUNT(d.order_id) AS delivered_order_count,
        AVG(p.order_payment_value) AS avg_payment_value,
        MAX(d.customer_city) AS customer_city,
        MAX(d.customer_state) AS customer_state
    FROM delivered_orders d
    LEFT JOIN payment_agg p ON d.order_id = p.order_id
    GROUP BY d.customer_unique_id
)
SELECT
    customer_unique_id,
    delivered_order_count,
    avg_payment_value,
    customer_city,
    customer_state
FROM customer_stats
ORDER BY delivered_order_count DESC
LIMIT 3
