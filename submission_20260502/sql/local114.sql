-- ========== OUTPUT COLUMN SPEC ==========
-- 1. region_id      : ID of the region (web_region.id)
-- 2. region_name    : Name of the region (web_region.name)
-- 3. num_orders     : COUNT of orders in that region
-- 4. total_sales    : SUM(total_amt_usd) across all orders in that region
-- 5. top_rep_name   : Name of sales rep(s) with highest regional sales (ties included)
-- 6. top_rep_sales  : Total sales amount for that top sales rep in the region
-- ========================================

-- INTERPRETATION: For each of the 4 regions, show the total number of web orders,
-- total sales USD, plus the name and sales total of the top-performing sales rep(s)
-- (all reps in case of ties). Join path: web_orders -> web_accounts -> web_sales_reps -> web_region.

-- EXPECTED: 4+ rows (one per region, more if there are ties for top rep)

WITH rep_sales AS (
    SELECT
        sr.id AS rep_id,
        sr.name AS rep_name,
        sr.region_id,
        SUM(o.total_amt_usd) AS rep_total_sales
    FROM web_sales_reps sr
    JOIN web_accounts a ON a.sales_rep_id = sr.id
    JOIN web_orders o ON o.account_id = a.id
    GROUP BY sr.id, sr.name, sr.region_id
),
region_stats AS (
    SELECT
        sr.region_id,
        COUNT(o.id) AS num_orders,
        SUM(o.total_amt_usd) AS total_sales
    FROM web_sales_reps sr
    JOIN web_accounts a ON a.sales_rep_id = sr.id
    JOIN web_orders o ON o.account_id = a.id
    GROUP BY sr.region_id
),
max_rep_sales AS (
    SELECT region_id, MAX(rep_total_sales) AS max_sales
    FROM rep_sales
    GROUP BY region_id
),
top_reps AS (
    SELECT rs.rep_id, rs.rep_name, rs.region_id, rs.rep_total_sales
    FROM rep_sales rs
    JOIN max_rep_sales m ON rs.region_id = m.region_id AND rs.rep_total_sales = m.max_sales
)
SELECT
    r.id AS region_id,
    r.name AS region_name,
    rs.num_orders,
    rs.total_sales,
    tr.rep_name AS top_rep_name,
    tr.rep_total_sales AS top_rep_sales
FROM web_region r
JOIN region_stats rs ON rs.region_id = r.id
JOIN top_reps tr ON tr.region_id = r.id
ORDER BY r.id, tr.rep_name;
