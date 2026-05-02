-- ========== OUTPUT COLUMN SPEC ==========
-- 1. age_category : Age group label (20s, 30s, 40s, 50s, others)
-- 2. user_count   : Count of users in that category
-- ========================================

-- INTERPRETATION: Count users grouped into age categories (20s, 30s, 40s, 50s, others)
-- Age is computed relative to the dataset's own latest register_date (static snapshot)
-- EXPECTED: 5 rows (one per age category)

WITH ref AS (
  SELECT MAX(register_date) AS ref_date FROM mst_users
),
user_ages AS (
  SELECT
    user_id,
    CAST((strftime('%Y', ref_date) - strftime('%Y', birth_date)) -
         CASE WHEN strftime('%m-%d', birth_date) > strftime('%m-%d', ref_date) THEN 1 ELSE 0 END
         AS INTEGER) AS age
  FROM mst_users, ref
),
categorized AS (
  SELECT
    CASE
      WHEN age BETWEEN 20 AND 29 THEN '20s'
      WHEN age BETWEEN 30 AND 39 THEN '30s'
      WHEN age BETWEEN 40 AND 49 THEN '40s'
      WHEN age BETWEEN 50 AND 59 THEN '50s'
      ELSE 'others'
    END AS age_category
  FROM user_ages
)
SELECT age_category, COUNT(*) AS user_count
FROM categorized
GROUP BY age_category
ORDER BY CASE age_category WHEN '20s' THEN 1 WHEN '30s' THEN 2 WHEN '40s' THEN 3 WHEN '50s' THEN 4 ELSE 5 END
