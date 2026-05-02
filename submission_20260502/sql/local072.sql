-- INTERPRETATION: Identify the country (by country_code_2) that has rows in the
-- `cities` table inserted on exactly 9 distinct days in January 2022. For that
-- country, find the longest consecutive run of insert dates within January 2022,
-- then compute the proportion of city rows in that run whose capital flag = 1.
-- EXPECTED: 1 row, single column capital_proportion (a real number between 0 and 1).
WITH target_country AS (
    -- The country whose insert_date set hits exactly 9 distinct days in Jan 2022
    SELECT country_code_2
    FROM cities
    WHERE insert_date >= '2022-01-01' AND insert_date <= '2022-01-31'
    GROUP BY country_code_2
    HAVING COUNT(DISTINCT insert_date) = 9
),
country_dates AS (
    -- Distinct insertion dates for that country in January 2022
    SELECT DISTINCT c.insert_date
    FROM cities c
    JOIN target_country t ON c.country_code_2 = t.country_code_2
    WHERE c.insert_date >= '2022-01-01' AND c.insert_date <= '2022-01-31'
),
date_groups AS (
    -- Classic consecutive-date trick: subtract row-number days from each date.
    -- Consecutive runs share the same anchor value `grp`.
    SELECT
        insert_date,
        date(insert_date, '-' || (ROW_NUMBER() OVER (ORDER BY insert_date) - 1) || ' days') AS grp
    FROM country_dates
),
group_sizes AS (
    SELECT
        grp,
        MIN(insert_date) AS start_date,
        MAX(insert_date) AS end_date,
        COUNT(*) AS consecutive_days
    FROM date_groups
    GROUP BY grp
),
longest_group AS (
    -- Pick the longest run; tie-break by earliest start_date
    SELECT start_date, end_date, consecutive_days
    FROM group_sizes
    ORDER BY consecutive_days DESC, start_date
    LIMIT 1
)
SELECT
    CAST(SUM(CASE WHEN c.capital = 1 THEN 1 ELSE 0 END) AS REAL) / COUNT(*) AS capital_proportion
FROM cities c
CROSS JOIN longest_group lg
JOIN target_country t ON c.country_code_2 = t.country_code_2
WHERE c.insert_date >= lg.start_date
  AND c.insert_date <= lg.end_date;
