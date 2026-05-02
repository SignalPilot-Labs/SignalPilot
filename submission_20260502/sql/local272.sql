-- ========== OUTPUT COLUMN SPEC ==========
-- 1. product_id   : product identifier from order 423 order lines
-- 2. aisle        : warehouse location aisle (warehouse 1)
-- 3. position     : warehouse location position (warehouse 1)
-- 4. qty          : quantity to pick from this location
-- ========================================

-- INTERPRETATION: For order 423, determine which warehouse-1 inventory locations to pick from
-- for each product ordered. Prioritize inventory by earlier purchased dates, then smaller
-- inventory quantity. Use cumulative range overlap (FIFO interval intersection) to determine
-- how much to pick from each location, ensuring total picked = total ordered per product.

-- EXPECTED: 5 rows (2 locations for product 4280, 3 locations for product 6520)

WITH order_lines AS (
    SELECT
        id,
        product_id,
        qty,
        SUM(qty) OVER (PARTITION BY product_id ORDER BY id
                       ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS cum_end,
        SUM(qty) OVER (PARTITION BY product_id ORDER BY id
                       ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) - qty AS cum_start
    FROM orderlines
    WHERE order_id = 423
),
inv_ranked AS (
    SELECT
        i.id AS inv_id,
        i.product_id,
        l.aisle,
        l.position,
        i.qty AS inv_qty,
        SUM(i.qty) OVER (PARTITION BY i.product_id
                         ORDER BY p.purchased ASC, i.qty ASC, i.id ASC
                         ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS inv_cum_end,
        SUM(i.qty) OVER (PARTITION BY i.product_id
                         ORDER BY p.purchased ASC, i.qty ASC, i.id ASC
                         ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) - i.qty AS inv_cum_start
    FROM inventory i
    JOIN locations l ON i.location_id = l.id AND l.warehouse = 1
    JOIN purchases p ON i.purchase_id = p.id
    WHERE i.product_id IN (SELECT product_id FROM orderlines WHERE order_id = 423)
),
picks AS (
    SELECT
        ol.product_id,
        ir.aisle,
        ir.position,
        MAX(0.0, MIN(ol.cum_end, ir.inv_cum_end) - MAX(ol.cum_start, ir.inv_cum_start)) AS pick_qty
    FROM order_lines ol
    JOIN inv_ranked ir ON ol.product_id = ir.product_id
)
SELECT product_id, aisle, position, SUM(pick_qty) AS qty
FROM picks
WHERE pick_qty > 0
GROUP BY product_id, aisle, position
ORDER BY product_id, aisle, position
