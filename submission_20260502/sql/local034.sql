-- INTERPRETATION: For each product category, find the payment_type with the highest
-- number of payments (COUNT of payment rows, deduped at order-category level).
-- Then compute the average of those maximum payment counts across all categories.
-- EXPECTED: 1 row (single aggregate value)

WITH order_categories AS (
    -- Each unique (order_id, category) pair, avoiding item-level fan-out
    SELECT DISTINCT oi.order_id, p.product_category_name
    FROM olist_order_items oi
    JOIN olist_products p ON oi.product_id = p.product_id
    WHERE p.product_category_name IS NOT NULL
),
category_payment_counts AS (
    -- COUNT(*) = actual payment rows, no fan-out since order_categories is deduped
    SELECT
        oc.product_category_name,
        op.payment_type,
        COUNT(*) AS payment_count
    FROM olist_order_payments op
    JOIN order_categories oc ON op.order_id = oc.order_id
    GROUP BY oc.product_category_name, op.payment_type
),
max_per_category AS (
    SELECT
        product_category_name,
        MAX(payment_count) AS max_payment_count
    FROM category_payment_counts
    GROUP BY product_category_name
)
SELECT AVG(max_payment_count) AS avg_payment_count
FROM max_per_category
