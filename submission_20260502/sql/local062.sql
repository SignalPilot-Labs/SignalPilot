-- ========== OUTPUT COLUMN SPEC ==========
-- 1. bucket        : bucket number (1-10), equal-width interval
-- 2. num_customers : count of Italian customers in this bucket
-- 3. min_profit    : minimum total profit within this bucket
-- 4. max_profit    : maximum total profit within this bucket
-- ========================================
-- EXPECTED: 10 rows (one per bucket)
-- INTERPRETATION: Group Italian customers by Dec 2021 total profit
--   (SUM of quantity_sold*(unit_price-unit_cost)) into 10 equal-width
--   intervals, report count/min/max per bucket

WITH italian_customers AS (
    SELECT cu.cust_id
    FROM customers cu
    JOIN countries co ON co.country_id = cu.country_id
    WHERE co.country_name = 'Italy'
),
dec2021_profits AS (
    SELECT
        s.cust_id,
        SUM(s.quantity_sold * (c.unit_price - c.unit_cost)) AS total_profit
    FROM sales s
    JOIN costs c ON c.prod_id = s.prod_id
                 AND c.time_id = s.time_id
                 AND c.promo_id = s.promo_id
                 AND c.channel_id = s.channel_id
    JOIN italian_customers ic ON ic.cust_id = s.cust_id
    WHERE strftime('%Y-%m', s.time_id) = '2021-12'
    GROUP BY s.cust_id
),
stats AS (
    SELECT MIN(total_profit) AS min_profit, MAX(total_profit) AS max_profit
    FROM dec2021_profits
),
bucketed AS (
    SELECT
        dp.cust_id,
        dp.total_profit,
        CAST(MIN(10, FLOOR((dp.total_profit - s.min_profit) / ((s.max_profit - s.min_profit) / 10.0)) + 1) AS INTEGER) AS bucket
    FROM dec2021_profits dp
    CROSS JOIN stats s
)
SELECT
    bucket,
    COUNT(*) AS num_customers,
    MIN(total_profit) AS min_profit,
    MAX(total_profit) AS max_profit
FROM bucketed
GROUP BY bucket
ORDER BY bucket
