-- ========== OUTPUT COLUMN SPEC ==========
-- 1. month_year                          : the month label (e.g., "09-2018")
-- 2. interest_name                       : name of the interest with highest avg composition that month
-- 3. max_index_composition               : max AVG(composition / index_value) for that month
-- 4. 3_month_rolling_avg                 : 3-month rolling average of max_index_composition
-- 5. 1_month_ago                         : interest name with highest avg composition from 1 month prior
-- 6. max_index_composition_1_month_ago   : max_index_composition from 1 month prior
-- 7. 2_months_ago                        : interest name with highest avg composition from 2 months prior
-- 8. max_index_composition_2_months_ago  : max_index_composition from 2 months prior
-- =========================================

-- INTERPRETATION: For each month Sep 2018 – Aug 2019, compute avg(composition/index_value) per interest,
-- find the interest with the highest value (max_index_composition), then compute a 3-month rolling
-- average of those maxima. Also include the interest name and max_index_composition from the prior
-- 1 and 2 months using LAG window functions.
-- EXPECTED: 12 rows (one per month)

WITH monthly_avg AS (
    SELECT
        _month, _year, month_year, interest_id,
        AVG(CAST(composition AS REAL) / CAST(index_value AS REAL)) AS avg_composition
    FROM interest_metrics
    WHERE _year IS NOT NULL
      AND ((_year = 2018 AND _month >= 9) OR (_year = 2019 AND _month <= 8))
    GROUP BY _month, _year, month_year, interest_id
),
monthly_max AS (
    SELECT
        _month, _year, month_year, interest_id, avg_composition,
        ROW_NUMBER() OVER (PARTITION BY _year, _month ORDER BY avg_composition DESC) AS rn
    FROM monthly_avg
),
top_per_month AS (
    SELECT
        _month, _year, month_year, interest_id,
        avg_composition AS max_index_composition
    FROM monthly_max
    WHERE rn = 1
),
with_names AS (
    SELECT
        t._month, t._year, t.month_year,
        m.interest_name,
        t.max_index_composition
    FROM top_per_month t
    JOIN interest_map m ON CAST(t.interest_id AS INTEGER) = m.id
),
final AS (
    SELECT
        _month, _year,
        month_year,
        interest_name,
        max_index_composition,
        AVG(max_index_composition) OVER (
            ORDER BY _year, _month
            ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
        ) AS "3_month_rolling_avg",
        LAG(interest_name, 1) OVER (ORDER BY _year, _month) AS "1_month_ago",
        LAG(max_index_composition, 1) OVER (ORDER BY _year, _month) AS max_index_composition_1_month_ago,
        LAG(interest_name, 2) OVER (ORDER BY _year, _month) AS "2_months_ago",
        LAG(max_index_composition, 2) OVER (ORDER BY _year, _month) AS max_index_composition_2_months_ago
    FROM with_names
)
SELECT
    month_year,
    interest_name,
    max_index_composition,
    "3_month_rolling_avg",
    "1_month_ago",
    max_index_composition_1_month_ago,
    "2_months_ago",
    max_index_composition_2_months_ago
FROM final
ORDER BY _year, _month;
