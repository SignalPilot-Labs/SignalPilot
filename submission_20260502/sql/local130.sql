-- ========== OUTPUT COLUMN SPEC ==========
-- 1. StudLastName  : last name of student (from Students table)
-- 2. Grade         : numeric grade in the English course (REAL)
-- 3. Quintile      : label "First"/"Second"/"Third"/"Fourth"/"Fifth"
-- ========================================

-- INTERPRETATION: Find all students who completed English courses (ClassStatus=2,
-- CategoryID='ENG'), compute quintile rank using the formula:
-- count(students with grade >= this grade) / total students → map to quintile label.
-- Sort results First to Fifth.

-- EXPECTED: 18 rows (18 students completed English courses)

WITH english_completed AS (
    SELECT st.StudLastName, ss.Grade
    FROM Student_Schedules ss
    JOIN Students st ON ss.StudentID = st.StudentID
    JOIN Classes c ON ss.ClassID = c.ClassID
    JOIN Subjects sub ON c.SubjectID = sub.SubjectID
    WHERE sub.CategoryID = 'ENG'
      AND ss.ClassStatus = 2
),
total AS (
    SELECT COUNT(*) AS total_count FROM english_completed
),
ranked AS (
    SELECT
        ec.StudLastName,
        ec.Grade,
        (SELECT COUNT(*) FROM english_completed ec2 WHERE ec2.Grade >= ec.Grade) AS count_gte,
        t.total_count
    FROM english_completed ec
    CROSS JOIN total t
)
SELECT
    StudLastName,
    Grade,
    CASE
        WHEN CAST(count_gte AS REAL) / total_count <= 0.20 THEN 'First'
        WHEN CAST(count_gte AS REAL) / total_count <= 0.40 THEN 'Second'
        WHEN CAST(count_gte AS REAL) / total_count <= 0.60 THEN 'Third'
        WHEN CAST(count_gte AS REAL) / total_count <= 0.80 THEN 'Fourth'
        ELSE 'Fifth'
    END AS Quintile
FROM ranked
ORDER BY
    CASE
        WHEN CAST(count_gte AS REAL) / total_count <= 0.20 THEN 1
        WHEN CAST(count_gte AS REAL) / total_count <= 0.40 THEN 2
        WHEN CAST(count_gte AS REAL) / total_count <= 0.60 THEN 3
        WHEN CAST(count_gte AS REAL) / total_count <= 0.80 THEN 4
        ELSE 5
    END,
    Grade DESC;
