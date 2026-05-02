-- INTERPRETATION: For each customer (excluding those with zero LTV), compute the percentage
-- of total lifetime sales that occurred within the first 7 days and first 30 days (exact
-- hours-minutes-seconds) after their initial purchase. Return the averages across all customers.
-- EXPECTED: 1 row (single aggregated result)

WITH customer_base AS (
  SELECT
    customer_id,
    MIN(payment_date) AS first_purchase,
    SUM(amount) AS ltv
  FROM payment
  GROUP BY customer_id
  HAVING SUM(amount) > 0
),
customer_periods AS (
  SELECT
    cb.customer_id,
    cb.first_purchase,
    cb.ltv,
    COALESCE(SUM(CASE WHEN (julianday(p.payment_date) - julianday(cb.first_purchase)) <= 7.0 THEN p.amount ELSE 0 END), 0) AS sales_7d,
    COALESCE(SUM(CASE WHEN (julianday(p.payment_date) - julianday(cb.first_purchase)) <= 30.0 THEN p.amount ELSE 0 END), 0) AS sales_30d
  FROM customer_base cb
  JOIN payment p ON cb.customer_id = p.customer_id
  GROUP BY cb.customer_id, cb.first_purchase, cb.ltv
)
SELECT
  AVG(sales_7d / ltv * 100) AS avg_pct_sales_7d,
  AVG(sales_30d / ltv * 100) AS avg_pct_sales_30d,
  AVG(ltv) AS avg_ltv
FROM customer_periods
