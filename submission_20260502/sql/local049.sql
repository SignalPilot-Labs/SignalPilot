WITH yearly_counts AS (
    SELECT
        ci.industry,
        CAST(strftime('%Y', cd.date_joined) AS INTEGER) AS year,
        COUNT(*) AS new_companies
    FROM companies_dates cd
    JOIN companies_industries ci ON cd.company_id = ci.company_id
    WHERE CAST(strftime('%Y', cd.date_joined) AS INTEGER) BETWEEN 2019 AND 2021
    GROUP BY ci.industry, year
),
industry_totals AS (
    SELECT
        industry,
        SUM(new_companies) AS total_companies
    FROM yearly_counts
    GROUP BY industry
    ORDER BY total_companies DESC
    LIMIT 1
),
top_industry_yearly AS (
    SELECT yc.industry, yc.year, yc.new_companies
    FROM yearly_counts yc
    JOIN industry_totals it ON yc.industry = it.industry
)
SELECT
    industry,
    CAST(SUM(new_companies) AS REAL) / COUNT(DISTINCT year) AS avg_new_unicorns_per_year
FROM top_industry_yearly
GROUP BY industry
