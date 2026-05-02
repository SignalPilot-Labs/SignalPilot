-- ========== OUTPUT COLUMN SPEC ==========
-- 1. month          : YYYY-MM (year-month grouping)
-- 2. monthly_total  : SUM of each customer's max daily balance in that month
-- ========================================
-- EXPECTED: 4 rows (Jan-Apr 2020)
-- INTERPRETATION: For each customer, generate a daily balance series from their
-- earliest to latest transaction date, carrying forward balance on non-transaction
-- days. deposit adds, purchase/withdrawal subtracts. Floor negative balances at 0.
-- Then compute max daily balance per customer per month, then sum those maxes per month.

WITH nums AS (
  SELECT ROW_NUMBER() OVER () - 1 AS n
  FROM customer_transactions
  LIMIT 200
),
all_dates AS (
  SELECT date('2020-01-01', '+' || n || ' day') AS d
  FROM nums
  WHERE date('2020-01-01', '+' || n || ' day') <= '2020-04-28'
),
customer_ranges AS (
  SELECT customer_id, MIN(txn_date) AS min_date, MAX(txn_date) AS max_date
  FROM customer_transactions
  GROUP BY customer_id
),
daily_net AS (
  SELECT customer_id, txn_date,
    SUM(CASE WHEN txn_type = 'deposit' THEN txn_amount ELSE -txn_amount END) AS net
  FROM customer_transactions
  GROUP BY customer_id, txn_date
),
customer_daily AS (
  SELECT cr.customer_id, ad.d AS day, COALESCE(dn.net, 0) AS net
  FROM customer_ranges cr
  JOIN all_dates ad ON ad.d >= cr.min_date AND ad.d <= cr.max_date
  LEFT JOIN daily_net dn ON dn.customer_id = cr.customer_id AND dn.txn_date = ad.d
),
running_balance AS (
  SELECT customer_id, day,
    CASE WHEN SUM(net) OVER (PARTITION BY customer_id ORDER BY day) < 0 THEN 0
         ELSE SUM(net) OVER (PARTITION BY customer_id ORDER BY day) END AS balance
  FROM customer_daily
),
monthly_max AS (
  SELECT customer_id,
    strftime('%Y-%m', day) AS month,
    MAX(balance) AS max_balance
  FROM running_balance
  GROUP BY customer_id, strftime('%Y-%m', day)
)
SELECT month, SUM(max_balance) AS monthly_total
FROM monthly_max
GROUP BY month
ORDER BY month
