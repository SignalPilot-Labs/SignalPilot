-- ========== OUTPUT COLUMN SPEC ==========
-- 1. month                : YYYY-MM, calendar month (first month per customer excluded)
-- 2. total_max_avg_balance: SUM of each customer's MAX 30-day rolling avg balance in that month
-- ========================================
--
-- INTERPRETATION: Compute daily running balance per customer (deposit = +, all others = -),
-- generate a full calendar-day series from each customer's first transaction date to the
-- data end date, compute 30-day rolling average balance (only valid from day 30 onwards;
-- negative averages clamped to 0), find each customer's max rolling avg per month,
-- sum those maxes per month, and exclude each customer's first month.
--
-- EXPECTED: 3 rows (Feb, Mar, Apr 2020) since all 500 customers start in Jan 2020

WITH RECURSIVE calendar AS (
    SELECT '2020-01-01' AS d
    UNION ALL
    SELECT date(d, '+1 day') FROM calendar
    WHERE d < (SELECT MAX(txn_date) FROM customer_transactions)
),
customer_first AS (
    SELECT customer_id, MIN(txn_date) AS first_date
    FROM customer_transactions
    GROUP BY customer_id
),
daily_net AS (
    SELECT
        customer_id,
        txn_date,
        SUM(CASE WHEN txn_type = 'deposit' THEN txn_amount ELSE -txn_amount END) AS net_amount
    FROM customer_transactions
    GROUP BY customer_id, txn_date
),
customer_calendar AS (
    SELECT cf.customer_id, c.d AS cal_date
    FROM customer_first cf
    JOIN calendar c ON c.d >= cf.first_date
),
daily_with_net AS (
    SELECT cc.customer_id, cc.cal_date,
        COALESCE(dn.net_amount, 0) AS net_amount
    FROM customer_calendar cc
    LEFT JOIN daily_net dn ON cc.customer_id = dn.customer_id AND cc.cal_date = dn.txn_date
),
running_balance AS (
    SELECT customer_id, cal_date,
        SUM(net_amount) OVER (PARTITION BY customer_id ORDER BY cal_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS balance,
        ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY cal_date) AS rn
    FROM daily_with_net
),
rolling_avg AS (
    SELECT customer_id, cal_date,
        CASE
            WHEN rn >= 30 THEN
                CASE WHEN AVG(CAST(balance AS REAL)) OVER (PARTITION BY customer_id ORDER BY cal_date ROWS BETWEEN 29 PRECEDING AND CURRENT ROW) < 0
                     THEN 0.0
                     ELSE AVG(CAST(balance AS REAL)) OVER (PARTITION BY customer_id ORDER BY cal_date ROWS BETWEEN 29 PRECEDING AND CURRENT ROW)
                END
            ELSE NULL
        END AS adj_avg_30d
    FROM running_balance
),
monthly_max AS (
    SELECT customer_id, strftime('%Y-%m', cal_date) AS month, MAX(adj_avg_30d) AS max_avg
    FROM rolling_avg
    WHERE adj_avg_30d IS NOT NULL
    GROUP BY customer_id, strftime('%Y-%m', cal_date)
),
first_month AS (
    SELECT customer_id, strftime('%Y-%m', MIN(txn_date)) AS first_month
    FROM customer_transactions
    GROUP BY customer_id
)
SELECT
    mm.month,
    SUM(mm.max_avg) AS total_max_avg_balance
FROM monthly_max mm
JOIN first_month fm ON mm.customer_id = fm.customer_id
WHERE mm.month != fm.first_month
GROUP BY mm.month
ORDER BY mm.month;
