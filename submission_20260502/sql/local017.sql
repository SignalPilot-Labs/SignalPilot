-- ========== OUTPUT COLUMN SPEC ==========
-- 1. year : the calendar year where the top-2 causes were different from other years
-- ========================================

-- INTERPRETATION: For each year, find the 2 most common pcf_violation_category values
-- (causes of traffic accidents). Identify the year where this pair is different
-- from the pair seen in all (or most) other years.
-- EXPECTED: 1 row (the unique year)

WITH year_cause_counts AS (
    SELECT
        strftime('%Y', collision_date) AS year,
        pcf_violation_category AS cause,
        COUNT(*) AS cnt
    FROM collisions
    WHERE collision_date IS NOT NULL AND pcf_violation_category IS NOT NULL
    GROUP BY year, cause
),
ranked_causes AS (
    SELECT
        year,
        cause,
        ROW_NUMBER() OVER (PARTITION BY year ORDER BY cnt DESC) AS rn
    FROM year_cause_counts
),
top2_per_year AS (
    SELECT
        year,
        MAX(CASE WHEN rn = 1 THEN cause END) AS top1,
        MAX(CASE WHEN rn = 2 THEN cause END) AS top2
    FROM ranked_causes
    WHERE rn <= 2
    GROUP BY year
),
pair_counts AS (
    SELECT
        CASE WHEN top1 <= top2 THEN top1 || '|||' || top2
             ELSE top2 || '|||' || top1 END AS sorted_pair,
        COUNT(*) AS years_with_pair
    FROM top2_per_year
    GROUP BY sorted_pair
)
SELECT t.year
FROM top2_per_year t
JOIN pair_counts pc ON
    CASE WHEN t.top1 <= t.top2 THEN t.top1 || '|||' || t.top2
         ELSE t.top2 || '|||' || t.top1 END = pc.sorted_pair
WHERE pc.years_with_pair = 1
ORDER BY t.year
