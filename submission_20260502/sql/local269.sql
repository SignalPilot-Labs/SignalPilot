-- INTERPRETATION: Find all final packaging combinations (top-level, never used as contents),
-- recursively expand nested packaging to reach leaf items (items not in packaging_id),
-- compute total leaf quantity per combination, then average those totals.
-- EXPECTED: 1 row (single average value)

WITH RECURSIVE expand AS (
    -- Base case: top-level packaging (not contained in any other)
    SELECT
        p.packaging_id AS root_id,
        p.contains_id,
        CAST(p.qty AS REAL) AS cumulative_qty
    FROM packaging_relations p
    WHERE p.packaging_id NOT IN (SELECT contains_id FROM packaging_relations)

    UNION ALL

    -- Recursive case: expand nested packaging
    SELECT
        e.root_id,
        pr.contains_id,
        e.cumulative_qty * pr.qty AS cumulative_qty
    FROM expand e
    JOIN packaging_relations pr ON pr.packaging_id = e.contains_id
),
-- Keep only leaf items (not further expanded as packaging_id)
leaf_items AS (
    SELECT
        root_id,
        contains_id,
        cumulative_qty
    FROM expand
    WHERE contains_id NOT IN (SELECT packaging_id FROM packaging_relations)
),
-- Sum leaf quantities per top-level combination
combo_totals AS (
    SELECT
        root_id,
        SUM(cumulative_qty) AS total_qty
    FROM leaf_items
    GROUP BY root_id
)
SELECT AVG(total_qty) AS avg_total_quantity
FROM combo_totals
