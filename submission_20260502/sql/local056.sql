-- ========== OUTPUT COLUMN SPEC ==========
-- 1. full_name          : customer first_name || ' ' || last_name
-- 2. avg_monthly_change : average of month-over-month differences in monthly payment totals
-- ========================================
-- INTERPRETATION: For each customer, compute monthly total payments, then calculate
-- the month-over-month change (using LAG), then average those changes.
-- The customer with the highest such average is returned.
-- EXPECTED: 1 row

WITH monthly_payments AS (
    SELECT
        customer_id,
        strftime('%Y-%m', payment_date) AS year_month,
        SUM(amount) AS monthly_total
    FROM payment
    GROUP BY customer_id, strftime('%Y-%m', payment_date)
),
monthly_changes AS (
    SELECT
        customer_id,
        year_month,
        monthly_total,
        monthly_total - LAG(monthly_total) OVER (PARTITION BY customer_id ORDER BY year_month) AS monthly_change
    FROM monthly_payments
),
avg_changes AS (
    SELECT
        customer_id,
        AVG(monthly_change) AS avg_monthly_change
    FROM monthly_changes
    WHERE monthly_change IS NOT NULL
    GROUP BY customer_id
)
SELECT
    c.first_name || ' ' || c.last_name AS full_name,
    ac.avg_monthly_change
FROM avg_changes ac
JOIN customer c ON ac.customer_id = c.customer_id
ORDER BY ac.avg_monthly_change DESC
LIMIT 1;
