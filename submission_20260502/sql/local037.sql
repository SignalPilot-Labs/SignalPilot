-- ========== OUTPUT COLUMN SPEC ==========
-- 1. rank                  : explicit rank position (1, 2, 3)
-- 2. product_category_name : name of the product category
-- 3. payment_type          : most commonly used payment type for that category
-- 4. payment_count         : number of payments using that payment type in that category
-- ========================================

-- INTERPRETATION: For each product category, find which payment_type is most common
-- (mode). Count payments for that (category, payment_type) pair. Return top 3
-- categories ranked by that count descending.
-- EXPECTED: 3 rows

WITH category_orders AS (
    SELECT DISTINCT oi.order_id, p.product_category_name
    FROM olist_order_items oi
    JOIN olist_products p ON oi.product_id = p.product_id
    WHERE p.product_category_name IS NOT NULL
),
category_payment_counts AS (
    SELECT
        co.product_category_name,
        op.payment_type,
        COUNT(*) AS payment_count
    FROM category_orders co
    JOIN olist_order_payments op ON co.order_id = op.order_id
    GROUP BY co.product_category_name, op.payment_type
),
ranked AS (
    SELECT
        product_category_name,
        payment_type,
        payment_count,
        ROW_NUMBER() OVER (PARTITION BY product_category_name ORDER BY payment_count DESC) AS rn
    FROM category_payment_counts
),
top_payment_per_category AS (
    SELECT
        product_category_name,
        payment_type,
        payment_count
    FROM ranked
    WHERE rn = 1
)
SELECT
    ROW_NUMBER() OVER (ORDER BY payment_count DESC) AS rank,
    product_category_name,
    payment_type,
    payment_count
FROM top_payment_per_category
ORDER BY payment_count DESC
LIMIT 3;
