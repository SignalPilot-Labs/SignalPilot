-- ========== OUTPUT COLUMN SPEC ==========
-- 1. BusinessEntityID  : salesperson ID (INTEGER) - the entity identifier
-- 2. year              : fiscal year (INTEGER) extracted from quota/order date
-- 3. total_sales       : SUM(subtotal) from salesorderheader for that salesperson+year
-- 4. annual_quota      : SUM(SalesQuota) from SalesPersonQuotaHistory for that person+year
-- 5. difference        : total_sales - annual_quota
-- ========================================

-- EXPECTED: 58 rows because there are ~17 salespeople across ~3-4 years each
-- INTERPRETATION: Annual total sales from salesorderheader (subtotal summed per year),
-- annual quota from SalesPersonQuotaHistory (SalesQuota summed per year per person),
-- difference = total_sales - annual_quota, grouped by salesperson ID and year.

WITH annual_quotas AS (
    SELECT
        BusinessEntityID,
        CAST(strftime('%Y', QuotaDate) AS INTEGER) AS year,
        SUM(SalesQuota) AS annual_quota
    FROM SalesPersonQuotaHistory
    GROUP BY BusinessEntityID, year
),
annual_sales AS (
    SELECT
        salespersonid,
        CAST(strftime('%Y', orderdate) AS INTEGER) AS year,
        SUM(subtotal) AS total_sales
    FROM salesorderheader
    WHERE salespersonid IS NOT NULL AND salespersonid != ''
    GROUP BY salespersonid, year
)
SELECT
    aq.BusinessEntityID,
    aq.year,
    COALESCE(s.total_sales, 0) AS total_sales,
    aq.annual_quota,
    COALESCE(s.total_sales, 0) - aq.annual_quota AS difference
FROM annual_quotas aq
LEFT JOIN annual_sales s
    ON aq.BusinessEntityID = s.salespersonid
    AND aq.year = s.year
ORDER BY aq.BusinessEntityID, aq.year
