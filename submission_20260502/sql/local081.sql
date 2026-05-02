-- ========== OUTPUT COLUMN SPEC ==========
-- 1. groupname       : spending group name (Low/Medium/High/Very High)
-- 2. customer_count  : number of customers assigned to this group
-- 3. percentage      : % of total 1998 customers this group represents
-- ========================================

-- EXPECTED: 4 rows (one per spending group)
-- INTERPRETATION: Find customers with orders in 1998, sum unitprice*quantity (no discount),
-- classify by customergroupthreshold ranges, count per group and % of total.

WITH customer_spend AS (
  SELECT
    o.customerid,
    SUM(od.unitprice * od.quantity) AS total_spend
  FROM orders o
  JOIN order_details od ON o.orderid = od.orderid
  WHERE strftime('%Y', o.orderdate) = '1998'
  GROUP BY o.customerid
),
total_customers AS (
  SELECT COUNT(*) AS total FROM customer_spend
),
grouped AS (
  SELECT
    cs.customerid,
    cs.total_spend,
    cgt.groupname
  FROM customer_spend cs
  JOIN customergroupthreshold cgt
    ON cs.total_spend >= cgt.rangebottom
    AND cs.total_spend <= cgt.rangetop
)
SELECT
  g.groupname,
  COUNT(*) AS customer_count,
  CAST(COUNT(*) AS REAL) * 100.0 / tc.total AS percentage
FROM grouped g
CROSS JOIN total_customers tc
GROUP BY g.groupname, tc.total
ORDER BY g.groupname
