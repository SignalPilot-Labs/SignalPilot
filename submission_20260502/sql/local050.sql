-- INTERPRETATION: Find the median of the 12 monthly average projected sales in USD
-- for France in 2021, using 2019-2020 data with promo_total_id=1 and channel_total_id=1 filters.
-- Projection formula: (((s2020-s2019)/s2019)*s2020)+s2020
-- EXPECTED: 1 row with the median scalar value

WITH france_sales AS (
    SELECT
        s.prod_id,
        t.calendar_year AS year,
        t.calendar_month_number AS month,
        SUM(s.amount_sold) AS total_sales
    FROM sales s
    JOIN times t ON s.time_id = t.time_id
    JOIN customers c ON s.cust_id = c.cust_id
    JOIN countries co ON c.country_id = co.country_id
    JOIN promotions p ON s.promo_id = p.promo_id
    JOIN channels ch ON s.channel_id = ch.channel_id
    WHERE co.country_name = 'France'
      AND t.calendar_year IN (2019, 2020)
      AND p.promo_total_id = 1
      AND ch.channel_total_id = 1
    GROUP BY s.prod_id, t.calendar_year, t.calendar_month_number
),
pivoted AS (
    SELECT
        prod_id,
        month,
        SUM(CASE WHEN year = 2019 THEN total_sales ELSE 0 END) AS sales_2019,
        SUM(CASE WHEN year = 2020 THEN total_sales ELSE 0 END) AS sales_2020
    FROM france_sales
    GROUP BY prod_id, month
),
projected AS (
    SELECT
        prod_id,
        month,
        (((sales_2020 - sales_2019) / sales_2019) * sales_2020) + sales_2020 AS projected_2021
    FROM pivoted
    WHERE sales_2019 > 0 AND sales_2020 > 0
),
with_usd AS (
    SELECT
        pr.prod_id,
        pr.month,
        pr.projected_2021 * COALESCE(cu.to_us, 1) AS projected_2021_usd
    FROM projected pr
    LEFT JOIN currency cu ON cu.country = 'France' AND cu.year = 2021 AND cu.month = pr.month
),
monthly_avg AS (
    SELECT
        month,
        AVG(projected_2021_usd) AS avg_usd
    FROM with_usd
    GROUP BY month
),
ranked AS (
    SELECT
        avg_usd,
        ROW_NUMBER() OVER (ORDER BY avg_usd) AS rn,
        COUNT(*) OVER () AS total_count
    FROM monthly_avg
)
SELECT AVG(avg_usd) AS median_avg_monthly_projected_sales_usd
FROM ranked
WHERE rn IN (
    (total_count + 1) / 2,
    (total_count + 2) / 2
);
