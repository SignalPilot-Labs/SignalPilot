-- ========== OUTPUT COLUMN SPEC ==========
-- 1. month         : YYYY-MM text, each month from 2nd month onwards (ascending)
-- 2. total_balance : sum of all customers' running balances (as of 1st of that month,
--                    i.e., using transactions from all prior months), with each
--                    customer's negative balance replaced by 0 before summing
-- ========================================
-- INTERPRETATION: For each month M (starting from 2nd month in data), compute each
-- customer's cumulative balance using all transactions BEFORE month M.
-- Replace any negative individual balance with 0. Sum across all customers.
-- Exclude the first month from output (it's baseline only). Sort by month asc.
-- EXPECTED: 3 rows (data spans 4 months Jan-Apr 2020, output has 3 rows)

WITH monthly_changes AS (
  SELECT
    customer_id,
    strftime('%Y-%m', txn_date) AS month,
    SUM(CASE WHEN txn_type = 'deposit' THEN txn_amount ELSE -txn_amount END) AS net_change
  FROM customer_transactions
  GROUP BY customer_id, strftime('%Y-%m', txn_date)
),
all_months AS (
  SELECT DISTINCT strftime('%Y-%m', txn_date) AS month
  FROM customer_transactions
),
all_customers AS (
  SELECT DISTINCT customer_id FROM customer_transactions
),
customer_month_balance AS (
  -- For each customer and month, calculate running balance as of the 1st of that month
  -- (sum of all net changes from prior months only)
  SELECT
    ac.customer_id,
    am.month,
    COALESCE(SUM(mc.net_change), 0) AS balance
  FROM all_customers ac
  CROSS JOIN all_months am
  LEFT JOIN monthly_changes mc
    ON mc.customer_id = ac.customer_id
    AND mc.month < am.month
  GROUP BY ac.customer_id, am.month
),
monthly_total AS (
  -- Replace negative per-customer balances with 0, then sum per month
  SELECT
    month,
    SUM(CASE WHEN balance < 0 THEN 0 ELSE balance END) AS total_balance
  FROM customer_month_balance
  GROUP BY month
),
ranked_months AS (
  SELECT
    month,
    total_balance,
    ROW_NUMBER() OVER (ORDER BY month) AS rn
  FROM monthly_total
)
SELECT
  month,
  total_balance
FROM ranked_months
WHERE rn > 1
ORDER BY month;
