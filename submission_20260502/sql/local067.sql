-- ========== OUTPUT COLUMN SPEC ==========
-- 1. tier        : integer 1-10, NTILE(10) tier based on December 2021 profit per Italian customer
-- 2. min_profit  : lowest profit value within that tier
-- 3. max_profit  : highest profit value within that tier
-- ========================================
-- INTERPRETATION: For Italian customers (country_id = 52770 = Italy), compute each customer's
-- total profit (amount_sold - unit_cost * quantity_sold) for December 2021, assign them into
-- 10 evenly-divided tiers using NTILE(10), then return the min and max profit per tier.
-- EXPECTED: 10 rows (one per tier)

WITH italian_custs AS (
  SELECT cust_id FROM customers WHERE country_id = 52770
),
dec2021_profits AS (
  SELECT s.cust_id,
         SUM(s.amount_sold - c.unit_cost * s.quantity_sold) AS profit
  FROM sales s
  JOIN costs c ON s.prod_id = c.prod_id AND s.time_id = c.time_id
                 AND s.channel_id = c.channel_id AND s.promo_id = c.promo_id
  JOIN italian_custs ic ON s.cust_id = ic.cust_id
  WHERE s.time_id >= '2021-12-01' AND s.time_id <= '2021-12-31'
  GROUP BY s.cust_id
),
tiered AS (
  SELECT cust_id, profit,
         NTILE(10) OVER (ORDER BY profit) AS tier
  FROM dec2021_profits
)
SELECT tier,
       MIN(profit) AS min_profit,
       MAX(profit) AS max_profit
FROM tiered
GROUP BY tier
ORDER BY tier;
