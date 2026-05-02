-- EXPECTED: 6 rows (one per hardware product segment)
-- INTERPRETATION: Count distinct product_codes per segment for fiscal_year 2020 and 2021,
-- compute % increase = (count_2021 - count_2020) / count_2020 * 100, order by % increase DESC
-- OUTPUT COLUMNS: segment, unique_products_2020, pct_increase

WITH sales_2020 AS (
    SELECT dp.segment, COUNT(DISTINCT fs.product_code) AS unique_products_2020
    FROM hardware_fact_sales_monthly fs
    JOIN hardware_dim_product dp ON fs.product_code = dp.product_code
    WHERE fs.fiscal_year = 2020
    GROUP BY dp.segment
),
sales_2021 AS (
    SELECT dp.segment, COUNT(DISTINCT fs.product_code) AS unique_products_2021
    FROM hardware_fact_sales_monthly fs
    JOIN hardware_dim_product dp ON fs.product_code = dp.product_code
    WHERE fs.fiscal_year = 2021
    GROUP BY dp.segment
)
SELECT
    s20.segment,
    s20.unique_products_2020,
    CAST(s21.unique_products_2021 - s20.unique_products_2020 AS REAL) / s20.unique_products_2020 * 100 AS pct_increase
FROM sales_2020 s20
JOIN sales_2021 s21 ON s20.segment = s21.segment
ORDER BY pct_increase DESC
