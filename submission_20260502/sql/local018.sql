-- INTERPRETATION: Find pcf_violation_category with highest count in 2021 dynamically,
-- then compute its % share in 2021 and 2011, and return decrease (share_2011 - share_2021).
-- EXPECTED: 1 row

WITH top_category_2021 AS (
    SELECT pcf_violation_category
    FROM collisions
    WHERE strftime('%Y', collision_date) = '2021'
      AND pcf_violation_category IS NOT NULL
    GROUP BY pcf_violation_category
    ORDER BY COUNT(*) DESC
    LIMIT 1
),
totals AS (
    SELECT
        strftime('%Y', collision_date) AS yr,
        COUNT(*) AS total_collisions
    FROM collisions
    WHERE strftime('%Y', collision_date) IN ('2011', '2021')
    GROUP BY yr
),
category_counts AS (
    SELECT
        strftime('%Y', collision_date) AS yr,
        COUNT(*) AS cat_count
    FROM collisions
    WHERE pcf_violation_category = (SELECT pcf_violation_category FROM top_category_2021)
      AND strftime('%Y', collision_date) IN ('2011', '2021')
    GROUP BY yr
),
shares AS (
    SELECT
        c.yr,
        CAST(c.cat_count AS REAL) / t.total_collisions * 100 AS share_pct
    FROM category_counts c
    JOIN totals t ON c.yr = t.yr
)
SELECT
    (SELECT pcf_violation_category FROM top_category_2021) AS pcf_violation_category,
    MAX(CASE WHEN yr = '2021' THEN share_pct END) AS share_2021,
    MAX(CASE WHEN yr = '2011' THEN share_pct END) AS share_2011,
    MAX(CASE WHEN yr = '2011' THEN share_pct END) - MAX(CASE WHEN yr = '2021' THEN share_pct END) AS percentage_point_decrease
FROM shares
