-- ========== OUTPUT COLUMN SPEC ==========
-- 1. attribute_type  : the attribute category name (region/platform/age_band/demographic/customer_type)
-- 2. avg_pct_change  : average % change in sales across all values of that attribute type
-- ========================================
-- INTERPRETATION: For each of the 5 attribute types, compute each value's % change in sales
-- (12 weeks after June 15 vs 12 weeks before), then average those % changes per type.
-- June 15, 2020 = week 25. Before = weeks 13-24 (2020). After = weeks 25-36 (2020).
-- Return the single attribute type with the most negative average % change.
-- EXPECTED: 1 row (the attribute type with highest negative impact)

WITH region_sales AS (
  SELECT 'region' AS attribute_type,
         region AS attribute_value,
         SUM(CASE WHEN week_number BETWEEN 13 AND 24 THEN sales ELSE 0 END) AS sales_before,
         SUM(CASE WHEN week_number BETWEEN 25 AND 36 THEN sales ELSE 0 END) AS sales_after
  FROM cleaned_weekly_sales
  WHERE calendar_year = 2020
  GROUP BY region
),
platform_sales AS (
  SELECT 'platform' AS attribute_type,
         platform AS attribute_value,
         SUM(CASE WHEN week_number BETWEEN 13 AND 24 THEN sales ELSE 0 END) AS sales_before,
         SUM(CASE WHEN week_number BETWEEN 25 AND 36 THEN sales ELSE 0 END) AS sales_after
  FROM cleaned_weekly_sales
  WHERE calendar_year = 2020
  GROUP BY platform
),
age_band_sales AS (
  SELECT 'age_band' AS attribute_type,
         age_band AS attribute_value,
         SUM(CASE WHEN week_number BETWEEN 13 AND 24 THEN sales ELSE 0 END) AS sales_before,
         SUM(CASE WHEN week_number BETWEEN 25 AND 36 THEN sales ELSE 0 END) AS sales_after
  FROM cleaned_weekly_sales
  WHERE calendar_year = 2020
  GROUP BY age_band
),
demographic_sales AS (
  SELECT 'demographic' AS attribute_type,
         demographic AS attribute_value,
         SUM(CASE WHEN week_number BETWEEN 13 AND 24 THEN sales ELSE 0 END) AS sales_before,
         SUM(CASE WHEN week_number BETWEEN 25 AND 36 THEN sales ELSE 0 END) AS sales_after
  FROM cleaned_weekly_sales
  WHERE calendar_year = 2020
  GROUP BY demographic
),
customer_type_sales AS (
  SELECT 'customer_type' AS attribute_type,
         customer_type AS attribute_value,
         SUM(CASE WHEN week_number BETWEEN 13 AND 24 THEN sales ELSE 0 END) AS sales_before,
         SUM(CASE WHEN week_number BETWEEN 25 AND 36 THEN sales ELSE 0 END) AS sales_after
  FROM cleaned_weekly_sales
  WHERE calendar_year = 2020
  GROUP BY customer_type
),
all_changes AS (
  SELECT * FROM region_sales
  UNION ALL SELECT * FROM platform_sales
  UNION ALL SELECT * FROM age_band_sales
  UNION ALL SELECT * FROM demographic_sales
  UNION ALL SELECT * FROM customer_type_sales
),
pct_changes AS (
  SELECT attribute_type,
         attribute_value,
         CAST(sales_after - sales_before AS REAL) / sales_before * 100 AS pct_change
  FROM all_changes
  WHERE sales_before > 0
),
avg_by_type AS (
  SELECT attribute_type,
         AVG(pct_change) AS avg_pct_change
  FROM pct_changes
  GROUP BY attribute_type
)
SELECT attribute_type,
       avg_pct_change
FROM avg_by_type
ORDER BY avg_pct_change ASC
LIMIT 1
