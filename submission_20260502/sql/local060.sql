-- ========== OUTPUT COLUMN SPEC ==========
-- 1. prod_id       : product primary key
-- 2. prod_name     : product name (NULL where not in products table)
-- 3. share_q4_2019 : product's share of total sales in Q4 2019 (qualifying cities, no promo)
-- 4. share_q4_2020 : product's share of total sales in Q4 2020 (qualifying cities, no promo)
-- 5. share_change  : share_q4_2020 - share_q4_2019
-- ORDER BY share_change DESC
-- ========================================

-- INTERPRETATION:
-- 1. Filter: US only (country_id=52790), no promotions (promo_id=999), Q4 2019 & Q4 2020
-- 2. Qualify cities: those where no-promo sales grew >= 20% from Q4 2019 to Q4 2020
-- 3. Among qualifying cities, rank products by total (Q4 2019+2020) sales (no promo), top 20% via NTILE(5)
-- 4. Compute each top product's share of TOTAL sales per quarter across qualifying cities
-- 5. Return share_change = share_q4_2020 - share_q4_2019, descending

WITH city_quarterly_sales AS (
  SELECT c.cust_city,
    SUM(CASE WHEN t.calendar_quarter_desc = '2019-04' THEN s.amount_sold ELSE 0 END) AS sales_q4_2019,
    SUM(CASE WHEN t.calendar_quarter_desc = '2020-04' THEN s.amount_sold ELSE 0 END) AS sales_q4_2020
  FROM sales s
  JOIN customers c ON s.cust_id = c.cust_id
  JOIN times t ON s.time_id = t.time_id
  WHERE s.promo_id = 999 AND c.country_id = 52790
    AND t.calendar_quarter_desc IN ('2019-04', '2020-04')
  GROUP BY c.cust_city
),
qualifying_cities AS (
  SELECT cust_city FROM city_quarterly_sales
  WHERE sales_q4_2019 > 0 AND sales_q4_2020 >= sales_q4_2019 * 1.2
),
base_sales AS (
  SELECT s.prod_id, t.calendar_quarter_desc, s.amount_sold
  FROM sales s
  JOIN customers c ON s.cust_id = c.cust_id
  JOIN times t ON s.time_id = t.time_id
  WHERE s.promo_id = 999 AND c.country_id = 52790
    AND t.calendar_quarter_desc IN ('2019-04', '2020-04')
    AND c.cust_city IN (SELECT cust_city FROM qualifying_cities)
),
product_overall_sales AS (
  SELECT prod_id, SUM(amount_sold) AS overall_sales,
    NTILE(5) OVER (ORDER BY SUM(amount_sold) DESC) AS quintile
  FROM base_sales GROUP BY prod_id
),
top_products AS (
  SELECT prod_id FROM product_overall_sales WHERE quintile = 1
),
product_quarter_sales AS (
  SELECT prod_id,
    SUM(CASE WHEN calendar_quarter_desc = '2019-04' THEN amount_sold ELSE 0 END) AS prod_sales_q4_2019,
    SUM(CASE WHEN calendar_quarter_desc = '2020-04' THEN amount_sold ELSE 0 END) AS prod_sales_q4_2020
  FROM base_sales
  WHERE prod_id IN (SELECT prod_id FROM top_products)
  GROUP BY prod_id
),
total_quarter_sales AS (
  SELECT
    SUM(CASE WHEN calendar_quarter_desc = '2019-04' THEN amount_sold ELSE 0 END) AS total_sales_q4_2019,
    SUM(CASE WHEN calendar_quarter_desc = '2020-04' THEN amount_sold ELSE 0 END) AS total_sales_q4_2020
  FROM base_sales
)
SELECT
  pqs.prod_id,
  pr.prod_name,
  pqs.prod_sales_q4_2019 / tqs.total_sales_q4_2019 AS share_q4_2019,
  pqs.prod_sales_q4_2020 / tqs.total_sales_q4_2020 AS share_q4_2020,
  (pqs.prod_sales_q4_2020 / tqs.total_sales_q4_2020) - (pqs.prod_sales_q4_2019 / tqs.total_sales_q4_2019) AS share_change
FROM product_quarter_sales pqs
JOIN total_quarter_sales tqs ON 1=1
LEFT JOIN products pr ON pqs.prod_id = pr.prod_id
ORDER BY share_change DESC
