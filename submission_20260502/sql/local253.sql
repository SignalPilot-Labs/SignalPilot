-- ========== OUTPUT COLUMN SPEC ==========
-- 1. Location              : city name (Mumbai, Pune, New Delhi, Hyderabad)
-- 2. CompanyName           : company name (top 5 per city by avg salary)
-- 3. avg_salary_in_city    : avg annual salary for that company in that city (numeric)
-- 4. avg_salary_in_country : overall national avg annual salary (same for all rows)
-- ========================================
-- EXPECTED: 20 rows (5 companies × 4 cities)
-- INTERPRETATION: Clean salary (strip ₹/$, commas, /yr /mo /hr), normalize to annual
--   (/mo × 12, /hr × 2080), rank companies by avg salary per city, pick top 5,
--   compare to national avg across all locations.

WITH cleaned AS (
  SELECT
    CompanyName,
    Location,
    CASE
      WHEN Salary LIKE '%/yr' THEN
        CAST(REPLACE(REPLACE(REPLACE(REPLACE(Salary, '₹', ''), '$', ''), ',', ''), '/yr', '') AS REAL)
      WHEN Salary LIKE '%/mo' THEN
        CAST(REPLACE(REPLACE(REPLACE(REPLACE(Salary, '₹', ''), '$', ''), ',', ''), '/mo', '') AS REAL) * 12
      WHEN Salary LIKE '%/hr' THEN
        CAST(REPLACE(REPLACE(REPLACE(REPLACE(Salary, '₹', ''), '$', ''), ',', ''), '/hr', '') AS REAL) * 2080
      ELSE NULL
    END AS annual_salary
  FROM SalaryDataset
),
national_avg AS (
  SELECT AVG(annual_salary) AS avg_salary_in_country
  FROM cleaned
  WHERE annual_salary IS NOT NULL
),
city_company_avg AS (
  SELECT
    Location,
    CompanyName,
    AVG(annual_salary) AS avg_salary_in_city
  FROM cleaned
  WHERE Location IN ('Mumbai', 'Pune', 'New Delhi', 'Hyderabad')
    AND annual_salary IS NOT NULL
  GROUP BY Location, CompanyName
),
ranked AS (
  SELECT
    Location,
    CompanyName,
    avg_salary_in_city,
    ROW_NUMBER() OVER (PARTITION BY Location ORDER BY avg_salary_in_city DESC) AS rnk
  FROM city_company_avg
)
SELECT
  r.Location,
  r.CompanyName,
  r.avg_salary_in_city,
  n.avg_salary_in_country
FROM ranked r
CROSS JOIN national_avg n
WHERE r.rnk <= 5
ORDER BY r.Location, r.rnk;
