-- INTERPRETATION: Find legislators whose first term started between 1917-01-01 and 1999-12-31 (cohort).
-- For each of the first 20 years following each legislator's initial term start,
-- compute the proportion of the cohort still in office on December 31st of that year.
-- Show all 20 periods in sequence.
--
-- EXPECTED: 20 rows (one per year_number 1-20)
--
-- OUTPUT COLUMN SPEC:
-- 1. year_number    : integer 1-20, the year in sequence after each legislator's first term start
-- 2. retention_rate : proportion of cohort still in office on Dec 31 of (first_year + year_number)

WITH RECURSIVE years AS (
    SELECT 1 AS year_number
    UNION ALL
    SELECT year_number + 1 FROM years WHERE year_number < 20
),
first_terms AS (
    SELECT id_bioguide,
           MIN(term_start) AS first_term_start,
           CAST(strftime('%Y', MIN(term_start)) AS INTEGER) AS first_year
    FROM legislators_terms
    GROUP BY id_bioguide
    HAVING MIN(term_start) >= '1917-01-01' AND MIN(term_start) <= '1999-12-31'
),
cohort_size AS (
    SELECT COUNT(*) AS total FROM first_terms
),
-- For each term of a cohort legislator, compute which year_numbers (1-20) it covers.
-- A term covers year_number N if:
--   term_start <= (first_year + N)-12-31  AND  term_end >= (first_year + N)-12-31
term_coverage AS (
    SELECT
        ft.id_bioguide,
        -- N_min: earliest year_number covered by this term
        MAX(1, CAST(strftime('%Y', lt.term_start) AS INTEGER) - ft.first_year) AS n_min,
        -- N_max: latest year_number covered by this term (Dec 31 anchor)
        MIN(20, CASE
            WHEN lt.term_end IS NULL THEN 20
            WHEN strftime('%m-%d', lt.term_end) >= '12-31'
                 THEN CAST(strftime('%Y', lt.term_end) AS INTEGER) - ft.first_year
            ELSE CAST(strftime('%Y', lt.term_end) AS INTEGER) - ft.first_year - 1
        END) AS n_max
    FROM first_terms ft
    JOIN legislators_terms lt ON ft.id_bioguide = lt.id_bioguide
),
-- Expand coverage ranges: one row per (legislator, covered year_number)
covered AS (
    SELECT DISTINCT tc.id_bioguide, y.year_number
    FROM term_coverage tc
    JOIN years y ON y.year_number >= tc.n_min AND y.year_number <= tc.n_max
),
-- Count retained legislators per year_number
retained AS (
    SELECT year_number, COUNT(DISTINCT id_bioguide) AS retained_count
    FROM covered
    GROUP BY year_number
)
SELECT
    y.year_number,
    CAST(COALESCE(r.retained_count, 0) AS REAL) / c.total AS retention_rate
FROM years y
LEFT JOIN retained r ON y.year_number = r.year_number
CROSS JOIN cohort_size c
ORDER BY y.year_number
