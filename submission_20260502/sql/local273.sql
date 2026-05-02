-- ========== OUTPUT COLUMN SPEC ==========
-- 1. product_id    : products.id - the product primary key
-- 2. product_name  : products.name - the product name
-- 3. avg_pick_pct  : average pick percentage = AVG(MIN(orderline.qty, inventory.qty) / orderline.qty)
--                   where inventory row is selected FIFO (earliest purchase_date ASC, then smallest qty ASC)
-- ========================================

-- INTERPRETATION: For each orderline (order_id, product_id, required_qty):
--   1. Find inventory rows for the same product
--   2. Order them by purchase date ASC, then inventory.qty ASC (FIFO)
--   3. Select only the FIRST inventory row (rn = 1)
--   4. picked_qty = MIN(orderline.qty, inventory.qty) — the overlapping range
--   5. pick_pct = picked_qty / orderline.qty
-- Average pick_pct by product_name, ordered by product_name.

-- EXPECTED: 6 rows (one per distinct product in orderlines)

WITH fifo_ranked AS (
  SELECT
    ol.id AS orderline_id,
    ol.product_id,
    ol.qty AS required_qty,
    i.qty AS inv_qty,
    pu.purchased,
    ROW_NUMBER() OVER (
      PARTITION BY ol.id
      ORDER BY pu.purchased ASC, i.qty ASC
    ) AS rn
  FROM orderlines ol
  JOIN inventory i ON i.product_id = ol.product_id
  JOIN purchases pu ON pu.id = i.purchase_id
),
fifo_selected AS (
  SELECT
    orderline_id,
    product_id,
    required_qty,
    inv_qty,
    CAST(MIN(required_qty, inv_qty) AS REAL) AS picked_qty,
    CAST(MIN(required_qty, inv_qty) AS REAL) / required_qty AS pick_pct
  FROM fifo_ranked
  WHERE rn = 1
)
SELECT
  p.id AS product_id,
  p.name AS product_name,
  AVG(f.pick_pct) AS avg_pick_pct
FROM fifo_selected f
JOIN products p ON p.id = f.product_id
GROUP BY p.id, p.name
ORDER BY p.name
