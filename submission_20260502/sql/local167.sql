-- ========== OUTPUT COLUMN SPEC ==========
-- 1. state             : State abbreviation (the state female legislator FIRST represented)
-- 2. legislator_count  : Count of distinct female legislators from that first state
--                        whose terms included December 31st at any point
-- ========================================
-- EXPECTED: 1 row — the single state with the highest count
-- INTERPRETATION: For female legislators only (gender='F'), find each one's first state
-- (state from their minimum term_number). Keep only those who had at least one term
-- spanning December 31st (term_end >= Dec 31 of the term's start year). Group by first
-- state, return the state with highest count.

WITH female_legislators AS (
    SELECT id_bioguide FROM legislators WHERE gender = 'F'
),
first_state AS (
    -- First state = state from the term with the minimum term_number
    SELECT lt.id_bioguide, lt.state
    FROM legislators_terms lt
    JOIN female_legislators fl ON lt.id_bioguide = fl.id_bioguide
    WHERE lt.term_number = (
        SELECT MIN(lt2.term_number) FROM legislators_terms lt2 WHERE lt2.id_bioguide = lt.id_bioguide
    )
),
dec31_legislators AS (
    -- Female legislators who have at least one term spanning December 31
    SELECT DISTINCT lt.id_bioguide
    FROM legislators_terms lt
    JOIN female_legislators fl ON lt.id_bioguide = fl.id_bioguide
    WHERE lt.term_end >= strftime('%Y', lt.term_start) || '-12-31'
)
SELECT
    fs.state,
    COUNT(*) AS legislator_count
FROM first_state fs
JOIN dec31_legislators dl ON fs.id_bioguide = dl.id_bioguide
GROUP BY fs.state
ORDER BY legislator_count DESC
LIMIT 1;
