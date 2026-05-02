-- EXPECTED: 20 rows (top 10 + bottom 10 interest categories)
-- INTERPRETATION: For each interest_id, find its highest composition value across all months.
-- Rank all interests by that max composition. Take top 10 (highest) and bottom 10 (lowest).
-- Display the month_year (MM-YYYY) when that max composition occurred, interest name, and composition value.

WITH max_comp AS (
    SELECT interest_id, MAX(composition) AS max_composition
    FROM interest_metrics
    WHERE interest_id IS NOT NULL
    GROUP BY interest_id
),
interest_month AS (
    -- Get month_year when max composition occurred
    SELECT im.interest_id, im.month_year, im.composition
    FROM interest_metrics im
    JOIN max_comp mc ON im.interest_id = mc.interest_id AND im.composition = mc.max_composition
),
deduped AS (
    -- In case multiple months have same max composition, pick first chronologically
    SELECT interest_id, month_year, composition,
           ROW_NUMBER() OVER (PARTITION BY interest_id ORDER BY month_year) AS rn
    FROM interest_month
),
ranked AS (
    SELECT
        d.interest_id,
        d.month_year,
        d.composition,
        ROW_NUMBER() OVER (ORDER BY d.composition DESC) AS rank_top,
        ROW_NUMBER() OVER (ORDER BY d.composition ASC) AS rank_bottom
    FROM deduped d
    WHERE d.rn = 1
),
top_bottom AS (
    SELECT interest_id, month_year, composition, rank_top, rank_bottom
    FROM ranked
    WHERE rank_top <= 10 OR rank_bottom <= 10
)
SELECT
    tb.month_year,
    map.interest_name,
    tb.composition
FROM top_bottom tb
JOIN interest_map map ON CAST(tb.interest_id AS INTEGER) = map.id
ORDER BY
    CASE WHEN tb.rank_top <= 10 THEN tb.rank_top ELSE 10 + tb.rank_bottom END
