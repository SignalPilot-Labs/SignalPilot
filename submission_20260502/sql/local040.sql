-- EXPECTED: 3 rows because question asks for the three boroughs with highest tree count
-- INTERPRETATION: Join trees with deduplicated income_trees by zipcode (income_trees has
--   4 exact-duplicate zip codes, so we deduplicate first). Filter for median income > 0
--   AND mean income > 0 AND valid borough name (not NULL/empty). Group by borough, count
--   trees and compute avg mean income, return top 3 by tree count.
--   "Filling missing ZIP values where necessary" — all trees have non-NULL/non-zero ZIP
--   codes; no actual filling needed. LEFT JOIN is used but income > 0 filter acts as INNER
--   JOIN for valid income records.

WITH deduped_income AS (
  SELECT DISTINCT zipcode, Estimate_Median_income, Estimate_Mean_income
  FROM income_trees
),
combined AS (
  SELECT t.boroname, i.Estimate_Median_income, i.Estimate_Mean_income
  FROM trees t
  LEFT JOIN deduped_income i ON t.zipcode = i.zipcode
  WHERE i.Estimate_Median_income > 0
    AND i.Estimate_Mean_income > 0
    AND t.boroname IS NOT NULL
    AND t.boroname != ''
),
borough_stats AS (
  SELECT
    boroname,
    COUNT(*) AS tree_count,
    AVG(Estimate_Mean_income) AS avg_mean_income
  FROM combined
  GROUP BY boroname
  ORDER BY tree_count DESC
  LIMIT 3
)
SELECT boroname, tree_count, avg_mean_income FROM borough_stats;
