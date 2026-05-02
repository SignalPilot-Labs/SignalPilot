-- INTERPRETATION: Find countries where the number of customers > 4, compute total sales
-- per such country (joining customers to invoices), then return the median of those totals.
-- EXPECTED: 1 row (single median value)

WITH country_customers AS (
    SELECT Country, COUNT(*) as customer_count
    FROM customers
    GROUP BY Country
    HAVING COUNT(*) > 4
),
country_sales AS (
    SELECT c.Country, SUM(i.Total) as total_sales
    FROM customers c
    JOIN invoices i ON i.CustomerId = c.CustomerId
    WHERE c.Country IN (SELECT Country FROM country_customers)
    GROUP BY c.Country
),
ranked AS (
    SELECT total_sales,
           ROW_NUMBER() OVER (ORDER BY total_sales) AS rn,
           COUNT(*) OVER () AS cnt
    FROM country_sales
)
SELECT AVG(total_sales) AS median_total_sales
FROM ranked
WHERE rn IN ((cnt + 1) / 2, (cnt + 2) / 2)
