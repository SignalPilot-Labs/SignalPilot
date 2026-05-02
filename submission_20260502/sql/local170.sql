-- EXPECTED: ~34 state rows
-- INTERPRETATION: States where both M and F cohorts have retention > 0 at all 6 time points
-- (0, 2, 4, 6, 8, 10 years after each legislator's first term start year),
-- where "retained" means serving on Dec 31 of the respective year.

-- ========== OUTPUT COLUMN SPEC ==========
-- 1. state : 2-letter state abbreviation satisfying both-gender non-zero retention at all 6 intervals
-- ========================================

WITH first_term_start AS (
    SELECT id_bioguide, MIN(term_start) AS first_term_start
    FROM legislators_terms
    GROUP BY id_bioguide
),
first_term_state AS (
    SELECT lt.id_bioguide, lt.state, lt.term_start
    FROM legislators_terms lt
    JOIN first_term_start fts
        ON lt.id_bioguide = fts.id_bioguide
        AND lt.term_start = fts.first_term_start
),
legislator_first AS (
    SELECT ft.id_bioguide, ft.state, l.gender, ft.term_start AS first_term_start,
           CAST(strftime('%Y', ft.term_start) AS INTEGER) AS first_year
    FROM first_term_state ft
    JOIN legislators l ON ft.id_bioguide = l.id_bioguide
    WHERE l.gender IS NOT NULL
),
retention_check AS (
    SELECT
        lf.id_bioguide,
        lf.state,
        lf.gender,
        lf.first_year,
        MAX(CASE WHEN lt.term_start <= (CAST(lf.first_year AS TEXT) || '-12-31')
                 AND (lt.term_end >= (CAST(lf.first_year AS TEXT) || '-12-31') OR lt.term_end IS NULL)
            THEN 1 ELSE 0 END) AS retained_0,
        MAX(CASE WHEN lt.term_start <= (CAST(lf.first_year + 2 AS TEXT) || '-12-31')
                 AND (lt.term_end >= (CAST(lf.first_year + 2 AS TEXT) || '-12-31') OR lt.term_end IS NULL)
            THEN 1 ELSE 0 END) AS retained_2,
        MAX(CASE WHEN lt.term_start <= (CAST(lf.first_year + 4 AS TEXT) || '-12-31')
                 AND (lt.term_end >= (CAST(lf.first_year + 4 AS TEXT) || '-12-31') OR lt.term_end IS NULL)
            THEN 1 ELSE 0 END) AS retained_4,
        MAX(CASE WHEN lt.term_start <= (CAST(lf.first_year + 6 AS TEXT) || '-12-31')
                 AND (lt.term_end >= (CAST(lf.first_year + 6 AS TEXT) || '-12-31') OR lt.term_end IS NULL)
            THEN 1 ELSE 0 END) AS retained_6,
        MAX(CASE WHEN lt.term_start <= (CAST(lf.first_year + 8 AS TEXT) || '-12-31')
                 AND (lt.term_end >= (CAST(lf.first_year + 8 AS TEXT) || '-12-31') OR lt.term_end IS NULL)
            THEN 1 ELSE 0 END) AS retained_8,
        MAX(CASE WHEN lt.term_start <= (CAST(lf.first_year + 10 AS TEXT) || '-12-31')
                 AND (lt.term_end >= (CAST(lf.first_year + 10 AS TEXT) || '-12-31') OR lt.term_end IS NULL)
            THEN 1 ELSE 0 END) AS retained_10
    FROM legislator_first lf
    JOIN legislators_terms lt ON lf.id_bioguide = lt.id_bioguide
    GROUP BY lf.id_bioguide, lf.state, lf.gender, lf.first_year
),
state_gender_retention AS (
    SELECT
        state,
        gender,
        COUNT(*) AS cohort_size,
        SUM(retained_0) * 1.0 / COUNT(*) AS rate_0,
        SUM(retained_2) * 1.0 / COUNT(*) AS rate_2,
        SUM(retained_4) * 1.0 / COUNT(*) AS rate_4,
        SUM(retained_6) * 1.0 / COUNT(*) AS rate_6,
        SUM(retained_8) * 1.0 / COUNT(*) AS rate_8,
        SUM(retained_10) * 1.0 / COUNT(*) AS rate_10
    FROM retention_check
    GROUP BY state, gender
),
valid_gender_state AS (
    SELECT state, gender
    FROM state_gender_retention
    WHERE rate_0 > 0 AND rate_2 > 0 AND rate_4 > 0
      AND rate_6 > 0 AND rate_8 > 0 AND rate_10 > 0
),
valid_states AS (
    SELECT m.state
    FROM valid_gender_state m
    JOIN valid_gender_state f ON m.state = f.state AND f.gender = 'F'
    WHERE m.gender = 'M'
)
SELECT state
FROM valid_states
ORDER BY state
