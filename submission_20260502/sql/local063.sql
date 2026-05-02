-- ========== OUTPUT COLUMN SPEC ==========
-- 1. prod_id           : product natural key
-- 2. prod_name         : product descriptive name
-- 3. total_sales       : total amount_sold across Q4 2019 + Q4 2020 (for top-20% ranking)
-- 4. sales_q4_2019     : total amount_sold in Q4 2019 (calendar_quarter_id=1772) in qualifying cities
-- 5. sales_q4_2020     : total amount_sold in Q4 2020 (calendar_quarter_id=1776) in qualifying cities
-- 6. share_q4_2019     : product's share of total sales (all products) in Q4 2019 (%)
-- 7. share_q4_2020     : product's share of total sales (all products) in Q4 2020 (%)
-- 8. pct_point_change  : |share_q4_2020 - share_q4_2019| in percentage points
-- ========================================

-- INTERPRETATION: Among US products sold with promo_id=999,
-- filter to cities where total sales (promo_id=999) grew >= 20% from Q4 2019 to Q4 2020.
-- Within those qualifying cities, rank all products by combined total sales using NTILE(5).
-- Among top-20% (quintile 1) products, find the one with smallest absolute change in
-- its share of total quarterly sales between the two quarters.

-- EXPECTED: 1 row (the single product with smallest pct-point share change in top 20%)

WITH base AS (
  SELECT s.prod_id, s.amount_sold, t.calendar_quarter_id, c.cust_city
  FROM sales s
  JOIN customers c ON s.cust_id = c.cust_id
  JOIN countries co ON c.country_id = co.country_id
  JOIN times t ON s.time_id = t.time_id
  WHERE co.country_name = 'United States of America'
    AND s.promo_id = 999
    AND t.calendar_quarter_id IN (1772, 1776)
),
city_sales AS (
  SELECT cust_city,
         SUM(CASE WHEN calendar_quarter_id = 1772 THEN amount_sold ELSE 0 END) AS city_q4_2019,
         SUM(CASE WHEN calendar_quarter_id = 1776 THEN amount_sold ELSE 0 END) AS city_q4_2020
  FROM base GROUP BY cust_city
),
qualifying_cities AS (
  SELECT cust_city FROM city_sales
  WHERE city_q4_2019 > 0 AND city_q4_2020 >= 1.2 * city_q4_2019
),
filtered_base AS (
  SELECT b.prod_id, b.amount_sold, b.calendar_quarter_id
  FROM base b JOIN qualifying_cities qc ON b.cust_city = qc.cust_city
),
quarter_totals AS (
  SELECT
    SUM(CASE WHEN calendar_quarter_id = 1772 THEN amount_sold ELSE 0 END) AS total_q4_2019,
    SUM(CASE WHEN calendar_quarter_id = 1776 THEN amount_sold ELSE 0 END) AS total_q4_2020
  FROM filtered_base
),
product_sales AS (
  SELECT prod_id,
         SUM(CASE WHEN calendar_quarter_id = 1772 THEN amount_sold ELSE 0 END) AS sales_q4_2019,
         SUM(CASE WHEN calendar_quarter_id = 1776 THEN amount_sold ELSE 0 END) AS sales_q4_2020,
         SUM(amount_sold) AS total_sales
  FROM filtered_base GROUP BY prod_id
),
with_shares AS (
  SELECT ps.prod_id, ps.sales_q4_2019, ps.sales_q4_2020, ps.total_sales,
         ps.sales_q4_2019 / qt.total_q4_2019 * 100.0 AS share_q4_2019,
         ps.sales_q4_2020 / qt.total_q4_2020 * 100.0 AS share_q4_2020,
         NTILE(5) OVER (ORDER BY ps.total_sales DESC) AS sales_quintile
  FROM product_sales ps CROSS JOIN quarter_totals qt
),
top20pct AS (
  SELECT *, ABS(share_q4_2020 - share_q4_2019) AS pct_point_change
  FROM with_shares WHERE sales_quintile = 1
)
SELECT t.prod_id, p.prod_name, t.total_sales, t.sales_q4_2019, t.sales_q4_2020,
       t.share_q4_2019, t.share_q4_2020, t.pct_point_change
FROM top20pct t
JOIN products p ON t.prod_id = p.prod_id
ORDER BY t.pct_point_change ASC
LIMIT 1;
