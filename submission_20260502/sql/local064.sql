-- INTERPRETATION:
-- For each customer and each month of 2020, compute month-end balance =
-- SUM(deposit amounts) - SUM(withdrawal amounts) for that month.
-- Count customers with positive month-end balance per month.
-- Find the month with highest count and the month with lowest count.
-- Compute average month-end balance for all customers in each of those two months.
-- Return both months' info and the difference between their averages.

-- EXPECTED: 1 row

WITH monthly_balance AS (
  SELECT
    customer_id,
    CAST(strftime('%m', txn_date) AS INTEGER) AS month,
    SUM(CASE WHEN txn_type = 'deposit' THEN txn_amount ELSE 0 END) -
    SUM(CASE WHEN txn_type = 'withdrawal' THEN txn_amount ELSE 0 END) AS month_end_balance
  FROM customer_transactions
  WHERE strftime('%Y', txn_date) = '2020'
  GROUP BY customer_id, month
),
positive_counts AS (
  SELECT
    month,
    COUNT(*) AS positive_count
  FROM monthly_balance
  WHERE month_end_balance > 0
  GROUP BY month
),
high_month AS (
  SELECT month FROM positive_counts ORDER BY positive_count DESC LIMIT 1
),
low_month AS (
  SELECT month FROM positive_counts ORDER BY positive_count ASC LIMIT 1
),
avg_high AS (
  SELECT AVG(mb.month_end_balance) AS avg_balance
  FROM monthly_balance mb
  WHERE mb.month = (SELECT month FROM high_month)
),
avg_low AS (
  SELECT AVG(mb.month_end_balance) AS avg_balance
  FROM monthly_balance mb
  WHERE mb.month = (SELECT month FROM low_month)
)
SELECT
  (SELECT month FROM high_month) AS highest_month,
  (SELECT positive_count FROM positive_counts WHERE month = (SELECT month FROM high_month)) AS highest_positive_count,
  (SELECT avg_balance FROM avg_high) AS highest_avg_balance,
  (SELECT month FROM low_month) AS lowest_month,
  (SELECT positive_count FROM positive_counts WHERE month = (SELECT month FROM low_month)) AS lowest_positive_count,
  (SELECT avg_balance FROM avg_low) AS lowest_avg_balance,
  (SELECT avg_balance FROM avg_high) - (SELECT avg_balance FROM avg_low) AS balance_difference;
