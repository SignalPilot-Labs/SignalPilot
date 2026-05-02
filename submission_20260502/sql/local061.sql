-- EXPECTED: 12 rows (one per month) because the question asks to average and list by month
-- INTERPRETATION: For France, with channel_total_id=1 and promo_total_id=1,
-- take each product's monthly sales in 2019 and 2020, compute growth rate,
-- project 2021 = ((s2020-s2019)/s2019)*s2020 + s2020, convert to USD, average by month

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
    JOIN channels ch ON s.channel_id = ch.channel_id
    JOIN promotions p ON s.promo_id = p.promo_id
    WHERE co.country_name = 'France'
      AND ch.channel_total_id = 1
      AND p.promo_total_id = 1
      AND t.calendar_year IN (2019, 2020)
    GROUP BY s.prod_id, t.calendar_year, t.calendar_month_number
),
sales_pivot AS (
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
        (((sales_2020 - sales_2019) * 1.0 / sales_2019) * sales_2020) + sales_2020 AS projected_2021
    FROM sales_pivot
    WHERE sales_2019 > 0 AND sales_2020 > 0
),
projected_usd AS (
    SELECT
        pr.month,
        pr.projected_2021 * COALESCE(cu.to_us, 1.0) AS projected_2021_usd
    FROM projected pr
    LEFT JOIN currency cu ON cu.country = 'France' AND cu.year = 2021 AND cu.month = pr.month
)
SELECT
    month,
    ROUND(AVG(projected_2021_usd), 2) AS avg_projected_monthly_sales_usd
FROM projected_usd
GROUP BY month
ORDER BY month;
