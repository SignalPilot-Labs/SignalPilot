-- EXPECTED: 2000 rows (500 customers × 4 months: Jan-Apr 2020)
-- INTERPRETATION: Monthly closing balance summary per customer with monthly net changes
-- and cumulative bank account balances. Customers with no activity in a month get
-- monthly_change = 0 and carry forward their previous closing_balance.

WITH monthly_activity AS (
    SELECT
        customer_id,
        strftime('%Y-%m', txn_date) AS month,
        SUM(CASE
            WHEN txn_type = 'deposit' THEN txn_amount
            WHEN txn_type IN ('purchase', 'withdrawal') THEN -txn_amount
            ELSE 0
        END) AS monthly_change
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
customer_months AS (
    SELECT c.customer_id, m.month
    FROM all_customers c
    CROSS JOIN all_months m
)
SELECT
    cm.customer_id,
    cm.month,
    COALESCE(ma.monthly_change, 0) AS monthly_change,
    SUM(COALESCE(ma.monthly_change, 0)) OVER (
        PARTITION BY cm.customer_id
        ORDER BY cm.month
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS closing_balance
FROM customer_months cm
LEFT JOIN monthly_activity ma
    ON cm.customer_id = ma.customer_id AND cm.month = ma.month
ORDER BY cm.customer_id, cm.month;
