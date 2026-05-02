-- Top-level packaging containers (not contained in any other packaging) with any
-- nested item whose total accumulated quantity across the hierarchy exceeds 500.
-- Quantities multiply down the hierarchy (parent qty * child qty * ...).
WITH RECURSIVE
top_level AS (
    SELECT id, name
    FROM packaging
    WHERE id NOT IN (SELECT contains_id FROM packaging_relations)
),
expanded(top_id, top_name, item_id, total_qty) AS (
    -- Base: direct children of each top-level container
    SELECT
        tl.id,
        tl.name,
        pr.contains_id,
        pr.qty
    FROM top_level tl
    JOIN packaging_relations pr ON pr.packaging_id = tl.id

    UNION ALL

    -- Recursive: descend into nested containers, multiplying quantities
    SELECT
        e.top_id,
        e.top_name,
        pr.contains_id,
        e.total_qty * pr.qty
    FROM expanded e
    JOIN packaging_relations pr ON pr.packaging_id = e.item_id
),
totals AS (
    SELECT
        top_id,
        top_name,
        item_id,
        SUM(total_qty) AS sum_qty
    FROM expanded
    GROUP BY top_id, top_name, item_id
)
SELECT
    t.top_id        AS container_id,
    t.top_name      AS container_name,
    t.item_id       AS item_id,
    p.name          AS item_name,
    t.sum_qty       AS total_quantity
FROM totals t
JOIN packaging p ON p.id = t.item_id
WHERE t.sum_qty > 500
ORDER BY t.top_id, p.name;
