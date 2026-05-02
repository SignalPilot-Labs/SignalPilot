-- INTERPRETATION: Find products where the sales-to-CMA ratio (actual sales / centered moving average)
-- is greater than 2 for EVERY month in 2017. CMA uses two overlapping 12-month windows:
--   Window 1: t-5 to t+6 (5 months before + current + 6 months after)
--   Window 2: t-6 to t+5 (6 months before + current + 5 months after)
--   CMA = (W1_avg + W2_avg) / 2
-- Restricted to months 7-30 (Jul 2016 - Jun 2018) to avoid edge effects.
-- 2017 = months 13-24 in sequential month numbering starting Jan 2016 = 1.

-- OUTPUT COLUMN SPEC:
-- 1. product_id   : integer PK from products table
-- 2. product_name : descriptive name of the product

-- EXPECTED: 0 rows — no product has ratio > 2 for all 12 months of 2017

WITH numbered_sales AS (
    SELECT
        product_id,
        mth,
        qty,
        (CAST(strftime('%Y', mth) AS INTEGER) - 2016) * 12 + CAST(strftime('%m', mth) AS INTEGER) AS month_num
    FROM monthly_sales
),
cma_calc AS (
    SELECT
        t.product_id,
        t.month_num,
        t.qty,
        (SELECT AVG(s.qty) FROM numbered_sales s
         WHERE s.product_id = t.product_id
         AND s.month_num BETWEEN t.month_num - 5 AND t.month_num + 6) AS w1_avg,
        (SELECT AVG(s.qty) FROM numbered_sales s
         WHERE s.product_id = t.product_id
         AND s.month_num BETWEEN t.month_num - 6 AND t.month_num + 5) AS w2_avg
    FROM numbered_sales t
    WHERE t.month_num BETWEEN 7 AND 30
),
ratios AS (
    SELECT
        product_id,
        month_num,
        qty,
        (w1_avg + w2_avg) / 2.0 AS cma,
        qty / ((w1_avg + w2_avg) / 2.0) AS ratio
    FROM cma_calc
),
year_2017 AS (
    SELECT product_id, month_num, ratio
    FROM ratios
    WHERE month_num BETWEEN 13 AND 24
),
qualified AS (
    SELECT product_id
    FROM year_2017
    GROUP BY product_id
    HAVING COUNT(*) = 12 AND MIN(ratio) > 2
)
SELECT p.id AS product_id, p.name AS product_name
FROM qualified q
JOIN products p ON p.id = q.product_id
ORDER BY p.id;
