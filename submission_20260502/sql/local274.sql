-- ========== OUTPUT COLUMN SPEC ==========
-- 1. product_id   : product identifier
-- 2. product_name : product descriptive name
-- 3. avg_qty      : average number of units picked per picking line (FIFO method)
-- ========================================

-- INTERPRETATION: Find products picked for order 421 from picking_line,
-- join to products for names. FIFO (First-In, First-Out) describes the picking
-- method (oldest inventory consumed first), reflected in the picking_line data.
-- Compute AVG(qty) per product across their picking lines.
-- EXPECTED: 2 rows (products 4280 and 6520)

SELECT
    pl.product_id,
    p.name AS product_name,
    AVG(pl.qty) AS avg_qty
FROM picking_line pl
JOIN products p ON p.id = pl.product_id
WHERE pl.order_id = 421
GROUP BY pl.product_id, p.name
ORDER BY pl.product_id
