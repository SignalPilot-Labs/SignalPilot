-- ========== OUTPUT COLUMN SPEC ==========
-- 1. division          : the hardware division name (N & S, P & A, PC)
-- 2. avg_quantity_sold : average total quantity sold of the top 3 products
--                        (by total qty) in this division for calendar year 2021
-- ========================================
-- INTERPRETATION: For calendar year 2021 (filtering by date column, not fiscal_year),
-- find the top 3 products by total sold_quantity per division, then compute the
-- average of those top-3 total quantities for each division.
-- EXPECTED: 3 rows (one per division)

WITH sales_2021 AS (
    SELECT
        s.product_code,
        SUM(s.sold_quantity) AS total_quantity
    FROM hardware_fact_sales_monthly s
    WHERE strftime('%Y', s.date) = '2021'
    GROUP BY s.product_code
),
products_with_division AS (
    SELECT
        p.product_code,
        p.division,
        s.total_quantity
    FROM hardware_dim_product p
    JOIN sales_2021 s ON p.product_code = s.product_code
),
ranked AS (
    SELECT
        division,
        product_code,
        total_quantity,
        ROW_NUMBER() OVER (PARTITION BY division ORDER BY total_quantity DESC) AS rn
    FROM products_with_division
),
top3 AS (
    SELECT division, product_code, total_quantity
    FROM ranked
    WHERE rn <= 3
)
SELECT
    division,
    AVG(total_quantity) AS avg_quantity_sold
FROM top3
GROUP BY division
ORDER BY division
