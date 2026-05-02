-- ========== OUTPUT COLUMN SPEC ==========
-- 1. FacRank      : faculty rank (e.g., ASSC, ASST, PROF)
-- 2. FacFirstName : faculty member's first name
-- 3. FacLastName  : faculty member's last name
-- 4. FacSalary    : faculty member's salary (closest to avg for their rank)
-- ========================================
-- INTERPRETATION: For each faculty rank, find the faculty member(s) whose salary
-- has the smallest absolute difference from the average salary of all members in that rank.
-- EXPECTED: ~3-4 rows (one per rank, possibly ties)

WITH avg_salary AS (
    SELECT FacRank, AVG(FacSalary) AS avg_sal
    FROM university_faculty
    GROUP BY FacRank
),
diff AS (
    SELECT
        f.FacRank,
        f.FacFirstName,
        f.FacLastName,
        f.FacSalary,
        ABS(f.FacSalary - a.avg_sal) AS salary_diff
    FROM university_faculty f
    JOIN avg_salary a ON f.FacRank = a.FacRank
),
min_diff AS (
    SELECT FacRank, MIN(salary_diff) AS min_diff
    FROM diff
    GROUP BY FacRank
)
SELECT d.FacRank, d.FacFirstName, d.FacLastName, d.FacSalary
FROM diff d
JOIN min_diff m ON d.FacRank = m.FacRank AND d.salary_diff = m.min_diff
ORDER BY d.FacRank
