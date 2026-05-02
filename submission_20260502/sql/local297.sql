-- ========== OUTPUT COLUMN SPEC ==========
-- 1. percentage : REAL — % of customers whose most recent month growth rate > 5%
-- ========================================
-- EXPECTED: 1 row, 1 column (single aggregate)
-- INTERPRETATION: deposits=positive, purchases/withdrawals=negative monthly nets,
--   cumulative sum = closing balance per month,
--   growth_rate = (current - prev) / ABS(prev) * 100,
--   if prev = 0: growth_rate = current * 100,
--   result = % of all customers where growth_rate > 5%

WITH monthly_net AS (
  SELECT
    customer_id,
    date(txn_date, 'start of month') AS month_start,
    SUM(CASE
          WHEN txn_type = 'deposit' THEN txn_amount
          WHEN txn_type IN ('withdrawal', 'purchase') THEN -txn_amount
          ELSE 0
        END) AS net_amount
  FROM customer_transactions
  GROUP BY customer_id, date(txn_date, 'start of month')
),
closing_balance AS (
  SELECT
    customer_id,
    month_start,
    SUM(net_amount) OVER (PARTITION BY customer_id ORDER BY month_start) AS balance
  FROM monthly_net
),
with_prev AS (
  SELECT
    customer_id,
    month_start,
    balance,
    LAG(balance) OVER (PARTITION BY customer_id ORDER BY month_start) AS prev_balance,
    ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY month_start DESC) AS rn
  FROM closing_balance
),
most_recent AS (
  SELECT
    customer_id,
    balance,
    prev_balance,
    CASE
      WHEN prev_balance IS NULL THEN NULL
      WHEN prev_balance = 0 THEN balance * 100.0
      ELSE (balance - prev_balance) * 1.0 / ABS(prev_balance) * 100
    END AS growth_rate
  FROM with_prev
  WHERE rn = 1
)
SELECT
  COUNT(CASE WHEN growth_rate > 5 THEN 1 END) * 100.0 / COUNT(*) AS percentage
FROM most_recent;
