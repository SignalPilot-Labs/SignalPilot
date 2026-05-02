-- ========== OUTPUT COLUMN SPEC ==========
-- 1. average_salary : AVG(salary_year_avg) for Data Analyst, remote (job_work_from_home=1),
--                     non-null salary jobs that have at least one of the top 3 most
--                     frequently demanded skills
-- ========================================

-- INTERPRETATION: Among jobs titled 'Data Analyst' that are remote (job_work_from_home=1)
-- with non-null salary_year_avg, find the top 3 skills by frequency (count of job postings).
-- Then compute the average salary of qualifying jobs that have any of those top 3 skills.
-- EXPECTED: 1 row

WITH qualifying_jobs AS (
    SELECT job_id, salary_year_avg
    FROM job_postings_fact
    WHERE job_title_short = 'Data Analyst'
      AND salary_year_avg IS NOT NULL
      AND job_work_from_home = 1
),
top_3_skills AS (
    SELECT sjd.skill_id
    FROM skills_job_dim sjd
    INNER JOIN qualifying_jobs qj ON sjd.job_id = qj.job_id
    GROUP BY sjd.skill_id
    ORDER BY COUNT(*) DESC
    LIMIT 3
),
qualifying_jobs_with_top_skills AS (
    SELECT DISTINCT qj.job_id, qj.salary_year_avg
    FROM qualifying_jobs qj
    INNER JOIN skills_job_dim sjd ON qj.job_id = sjd.job_id
    INNER JOIN top_3_skills t3s ON sjd.skill_id = t3s.skill_id
)
SELECT AVG(salary_year_avg) AS average_salary
FROM qualifying_jobs_with_top_skills;
