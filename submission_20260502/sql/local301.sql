-- EXPECTED: 3 rows (one per year: 2018, 2019, 2020)
-- INTERPRETATION: For each year, sum total sales across all rows whose week_date falls
--   within 28 days before June 15 (4 weeks leading up) and 28 days after June 15
--   (4 weeks following), then compute % change = (after - before) / before * 100

-- ========== OUTPUT COLUMN SPEC ==========
-- 1. year          : calendar year (2018, 2019, 2020)
-- 2. before_sales  : total sales for 4 weeks leading up to June 15
-- 3. after_sales   : total sales for 4 weeks following June 15
-- 4. pct_change    : percentage change (after - before) / before * 100
-- ========================================

WITH sales_periods AS (
  SELECT
    calendar_year,
    sales,
    julianday(week_date) - julianday(calendar_year || '-06-15') AS days_from_june15
  FROM cleaned_weekly_sales
  WHERE calendar_year IN (2018, 2019, 2020)
),
categorized AS (
  SELECT
    calendar_year,
    sales,
    CASE
      WHEN days_from_june15 BETWEEN -28 AND -1 THEN 'before'
      WHEN days_from_june15 BETWEEN 1 AND 28 THEN 'after'
    END AS period
  FROM sales_periods
  WHERE days_from_june15 BETWEEN -28 AND -1
     OR days_from_june15 BETWEEN 1 AND 28
),
aggregated AS (
  SELECT
    calendar_year,
    SUM(CASE WHEN period = 'before' THEN sales ELSE 0 END) AS before_sales,
    SUM(CASE WHEN period = 'after' THEN sales ELSE 0 END) AS after_sales
  FROM categorized
  GROUP BY calendar_year
)
SELECT
  calendar_year AS year,
  before_sales,
  after_sales,
  ROUND(
    (after_sales - before_sales) * 100.0 / before_sales, 2
  ) AS pct_change
FROM aggregated
ORDER BY calendar_year;
