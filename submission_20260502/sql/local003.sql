-- ========== OUTPUT COLUMN SPEC ==========
-- 1. rfm_segment        : RFM segment name per RFM.md criteria
-- 2. avg_sales_per_order: SUM(total_spend) / SUM(total_orders) per segment
-- ========================================

-- INTERPRETATION: For each delivered order, join customers (using customer_unique_id)
-- and order_payments to get spend. Per customer, compute:
--   Recency = latest order_purchase_timestamp (scored 1=most recent via NTILE(5) DESC)
--   Frequency = count of distinct orders (scored 1=most frequent via NTILE(5) DESC)
--   Monetary = sum of payment_value (scored 1=highest spend via NTILE(5) DESC)
-- Classify into RFM segments per RFM.md rules (R score + F+M composite score).
-- Report avg_sales_per_order = total segment spend / total segment orders per segment.

-- EXPECTED: 11 rows (one per named RFM segment from RFM.md)

WITH delivered_orders AS (
    -- Filter to delivered orders; join customers for customer_unique_id;
    -- sum payment_value per order (multiple payment rows possible)
    SELECT
        c.customer_unique_id,
        o.order_id,
        o.order_purchase_timestamp,
        SUM(op.payment_value) AS order_value
    FROM orders o
    JOIN customers c ON o.customer_id = c.customer_id
    JOIN order_payments op ON o.order_id = op.order_id
    WHERE o.order_status = 'delivered'
    GROUP BY c.customer_unique_id, o.order_id, o.order_purchase_timestamp
),
customer_metrics AS (
    -- Per customer: recency (last purchase date), frequency (# orders), monetary (total spend)
    SELECT
        customer_unique_id,
        MAX(order_purchase_timestamp) AS last_purchase_date,
        COUNT(DISTINCT order_id) AS frequency,
        SUM(order_value) AS monetary
    FROM delivered_orders
    GROUP BY customer_unique_id
),
rfm_scores AS (
    -- Score R, F, M on 1–5 scale using NTILE(5):
    --   R=1: most recent purchase (ORDER BY last_purchase_date DESC)
    --   F=1: most frequent buyer (ORDER BY frequency DESC)
    --   M=1: highest spender (ORDER BY monetary DESC)
    SELECT
        customer_unique_id,
        last_purchase_date,
        frequency,
        monetary,
        NTILE(5) OVER (ORDER BY last_purchase_date DESC) AS r_score,
        NTILE(5) OVER (ORDER BY frequency DESC) AS f_score,
        NTILE(5) OVER (ORDER BY monetary DESC) AS m_score
    FROM customer_metrics
),
rfm_segments AS (
    -- Classify customers into RFM segments per RFM.md segmentation logic
    SELECT
        customer_unique_id,
        r_score,
        f_score,
        m_score,
        f_score + m_score AS fm_score,
        frequency,
        monetary,
        CASE
            WHEN r_score = 1 AND (f_score + m_score) BETWEEN 1 AND 4 THEN 'Champions'
            WHEN r_score IN (4, 5) AND (f_score + m_score) BETWEEN 1 AND 2 THEN 'Can''t Lose Them'
            WHEN r_score IN (4, 5) AND (f_score + m_score) BETWEEN 3 AND 6 THEN 'Hibernating'
            WHEN r_score IN (4, 5) AND (f_score + m_score) BETWEEN 7 AND 10 THEN 'Lost'
            WHEN r_score IN (2, 3) AND (f_score + m_score) BETWEEN 1 AND 4 THEN 'Loyal Customers'
            WHEN r_score = 3 AND (f_score + m_score) BETWEEN 5 AND 6 THEN 'Needs Attention'
            WHEN r_score = 1 AND (f_score + m_score) BETWEEN 7 AND 8 THEN 'Recent Users'
            WHEN (r_score = 1 AND (f_score + m_score) BETWEEN 5 AND 6)
              OR (r_score = 2 AND (f_score + m_score) BETWEEN 5 AND 8) THEN 'Potential Loyalists'
            WHEN r_score = 1 AND (f_score + m_score) BETWEEN 9 AND 10 THEN 'Price Sensitive'
            WHEN r_score = 2 AND (f_score + m_score) BETWEEN 9 AND 10 THEN 'Promising'
            WHEN r_score = 3 AND (f_score + m_score) BETWEEN 7 AND 10 THEN 'About to Sleep'
            ELSE 'Other'
        END AS rfm_segment
    FROM rfm_scores
)
-- Final: avg_sales_per_order = total segment spend / total segment orders
SELECT
    rfm_segment,
    CAST(SUM(monetary) AS REAL) / SUM(frequency) AS avg_sales_per_order
FROM rfm_segments
GROUP BY rfm_segment
ORDER BY avg_sales_per_order DESC;
