-- ========== OUTPUT COLUMN SPEC ==========
-- 1. product_id  : product identifier (from product_minimums)
-- 2. mth         : month in 2019 (YYYY-MM-DD) where abs diff is smallest
-- 3. abs_diff    : absolute difference between ending inventory and qty_minimum at that month
-- ========================================

-- INTERPRETATION: Starting from December 2018 inventory (from inventory table),
-- simulate each month in 2019: subtract monthly_budget.qty from inventory,
-- restock if ending < qty_minimum (add qty_purchase). Find month per product
-- with smallest ABS(ending_inventory - qty_minimum).

-- EXPECTED: 2 rows (one per product in product_minimums)

WITH RECURSIVE
start_inv AS (
    SELECT product_id, SUM(qty) as start_qty
    FROM inventory
    WHERE product_id IN (SELECT product_id FROM product_minimums)
    GROUP BY product_id
),
sim AS (
    -- Base case: January 2019
    SELECT
        si.product_id,
        1 as month_num,
        '2019-01-01' as mth,
        CASE
            WHEN si.start_qty - mb.qty < pm.qty_minimum
            THEN si.start_qty - mb.qty + pm.qty_purchase
            ELSE si.start_qty - mb.qty
        END as ending_inv
    FROM start_inv si
    JOIN product_minimums pm ON pm.product_id = si.product_id
    JOIN monthly_budget mb ON mb.product_id = si.product_id AND mb.mth = '2019-01-01'

    UNION ALL

    -- Recursive step: advance one month at a time through December 2019
    SELECT
        s.product_id,
        s.month_num + 1,
        date(s.mth, '+1 month') as next_mth,
        CASE
            WHEN s.ending_inv - mb.qty < pm.qty_minimum
            THEN s.ending_inv - mb.qty + pm.qty_purchase
            ELSE s.ending_inv - mb.qty
        END
    FROM sim s
    JOIN product_minimums pm ON pm.product_id = s.product_id
    JOIN monthly_budget mb ON mb.product_id = s.product_id AND mb.mth = date(s.mth, '+1 month')
    WHERE s.month_num < 12
),
diffs AS (
    SELECT
        s.product_id,
        s.mth,
        ABS(s.ending_inv - pm.qty_minimum) as abs_diff,
        ROW_NUMBER() OVER (PARTITION BY s.product_id ORDER BY ABS(s.ending_inv - pm.qty_minimum), s.mth) as rn
    FROM sim s
    JOIN product_minimums pm ON pm.product_id = s.product_id
)
SELECT product_id, mth, abs_diff
FROM diffs
WHERE rn = 1
ORDER BY product_id;
