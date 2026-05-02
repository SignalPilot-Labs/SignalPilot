-- ========== OUTPUT COLUMN SPEC ==========
-- 1. product_id   : numeric product ID from page_hierarchy
-- 2. product_name : product name (page_name) from page_hierarchy
-- 3. page_views   : count of page view events (event_type=1) per product
-- 4. cart_adds    : count of add-to-cart events (event_type=2) per product
-- 5. abandoned    : count of add-to-cart events in visits that did NOT result in a purchase
-- 6. purchases    : count of add-to-cart events in visits that DID result in a purchase
-- ========================================

-- INTERPRETATION: For each product page (excluding page_ids 1,2,12,13), count:
--   views (event_type=1), cart adds (event_type=2), abandoned cart (added but visit had no purchase),
--   and purchases (added in a visit that resulted in a purchase event).
-- EXPECTED: 9 rows (one per product)

WITH purchase_visits AS (
  SELECT DISTINCT visit_id
  FROM shopping_cart_events
  WHERE event_type = 3
),
product_events AS (
  SELECT
    e.visit_id,
    e.page_id,
    e.event_type,
    p.page_name,
    p.product_id
  FROM shopping_cart_events e
  JOIN shopping_cart_page_hierarchy p ON e.page_id = p.page_id
  WHERE e.page_id NOT IN (1, 2, 12, 13)
)
SELECT
  pe.product_id,
  pe.page_name AS product_name,
  SUM(CASE WHEN pe.event_type = 1 THEN 1 ELSE 0 END) AS page_views,
  SUM(CASE WHEN pe.event_type = 2 THEN 1 ELSE 0 END) AS cart_adds,
  SUM(CASE WHEN pe.event_type = 2 AND pv.visit_id IS NULL THEN 1 ELSE 0 END) AS abandoned,
  SUM(CASE WHEN pe.event_type = 2 AND pv.visit_id IS NOT NULL THEN 1 ELSE 0 END) AS purchases
FROM product_events pe
LEFT JOIN purchase_visits pv ON pe.visit_id = pv.visit_id
GROUP BY pe.product_id, pe.page_name
ORDER BY pe.product_id;
