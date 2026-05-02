-- INTERPRETATION: Among the top 10 customers (ranked by total payments),
-- find the largest month-over-month change in payment totals between
-- consecutive calendar months, and report the customer and the month
-- in which that change occurred, with the absolute difference rounded to 2 decimals.
WITH top10 AS (
  SELECT customer_id
  FROM payment
  GROUP BY customer_id
  ORDER BY SUM(amount) DESC
  LIMIT 10
),
monthly AS (
  SELECT p.customer_id,
         strftime('%Y-%m', p.payment_date) AS payment_month,
         strftime('%Y-%m-01', p.payment_date) AS month_start,
         SUM(p.amount) AS monthly_amount
  FROM payment p
  JOIN top10 t ON p.customer_id = t.customer_id
  GROUP BY p.customer_id, payment_month, month_start
),
with_lag AS (
  SELECT m.customer_id, m.payment_month, m.month_start, m.monthly_amount,
         LAG(m.monthly_amount) OVER (PARTITION BY m.customer_id ORDER BY m.month_start) AS prev_amount,
         LAG(m.month_start)    OVER (PARTITION BY m.customer_id ORDER BY m.month_start) AS prev_month_start
  FROM monthly m
),
consec AS (
  SELECT customer_id, payment_month,
         ROUND(ABS(monthly_amount - prev_amount), 2) AS abs_diff
  FROM with_lag
  WHERE prev_amount IS NOT NULL
    AND CAST((julianday(month_start) - julianday(prev_month_start)) AS INTEGER) BETWEEN 28 AND 31
)
SELECT c.customer_id,
       cu.first_name,
       cu.last_name,
       c.payment_month,
       c.abs_diff AS max_mom_difference
FROM consec c
JOIN customer cu ON cu.customer_id = c.customer_id
ORDER BY c.abs_diff DESC
LIMIT 1;
