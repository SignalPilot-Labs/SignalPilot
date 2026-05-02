-- ========== OUTPUT COLUMN SPEC ==========
-- 1. seller_id                    : TEXT — seller's primary key
-- 2. total_sales                  : REAL — SUM(price) of all items sold by this seller
-- 3. avg_item_price               : REAL — AVG(price) per item for this seller
-- 4. avg_review_score             : REAL — AVG(review_score) from reviews on this seller's orders (deduplicated by order)
-- 5. avg_packing_time             : REAL — AVG(days from order_approved_at to order_delivered_carrier_date)
-- 6. quantity_sold                : INTEGER — COUNT of order_items rows (filter: > 100)
-- 7. top_product_category_english : TEXT — English name of the product category with highest quantity sold for this seller
-- ========================================
-- FILTER: only sellers with quantity_sold > 100
-- EXPECTED: ~236 sellers

WITH seller_metrics AS (
    SELECT
        oi.seller_id,
        SUM(oi.price) AS total_sales,
        AVG(oi.price) AS avg_item_price,
        COUNT(*) AS quantity_sold
    FROM order_items oi
    GROUP BY oi.seller_id
    HAVING COUNT(*) > 100
),
seller_reviews AS (
    SELECT
        seller_orders.seller_id,
        AVG(r.review_score) AS avg_review_score
    FROM (SELECT DISTINCT seller_id, order_id FROM order_items) AS seller_orders
    JOIN order_reviews r ON r.order_id = seller_orders.order_id
    GROUP BY seller_orders.seller_id
),
seller_packing AS (
    SELECT
        oi.seller_id,
        AVG(julianday(o.order_delivered_carrier_date) - julianday(o.order_approved_at)) AS avg_packing_time
    FROM order_items oi
    JOIN orders o ON o.order_id = oi.order_id
    WHERE o.order_approved_at IS NOT NULL
      AND o.order_delivered_carrier_date IS NOT NULL
    GROUP BY oi.seller_id
),
seller_categories AS (
    SELECT
        oi.seller_id,
        t.product_category_name_english,
        COUNT(*) AS category_quantity
    FROM order_items oi
    JOIN products p ON p.product_id = oi.product_id
    JOIN product_category_name_translation t ON t.product_category_name = p.product_category_name
    GROUP BY oi.seller_id, t.product_category_name_english
),
seller_top_category AS (
    SELECT seller_id, product_category_name_english
    FROM (
        SELECT
            seller_id,
            product_category_name_english,
            ROW_NUMBER() OVER (PARTITION BY seller_id ORDER BY category_quantity DESC) AS rn
        FROM seller_categories
    )
    WHERE rn = 1
)
SELECT
    sm.seller_id,
    sm.total_sales,
    sm.avg_item_price,
    sr.avg_review_score,
    sp.avg_packing_time,
    sm.quantity_sold,
    stc.product_category_name_english AS top_product_category_english
FROM seller_metrics sm
LEFT JOIN seller_reviews sr ON sr.seller_id = sm.seller_id
LEFT JOIN seller_packing sp ON sp.seller_id = sm.seller_id
LEFT JOIN seller_top_category stc ON stc.seller_id = sm.seller_id
ORDER BY sm.total_sales DESC
