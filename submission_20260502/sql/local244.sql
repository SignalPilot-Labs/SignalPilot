WITH stats AS (
    SELECT
        MIN(Milliseconds) AS min_ms,
        AVG(Milliseconds) AS avg_ms,
        MAX(Milliseconds) AS max_ms,
        (MIN(Milliseconds) + AVG(Milliseconds)) / 2.0 AS mid_min_avg,
        (AVG(Milliseconds) + MAX(Milliseconds)) / 2.0 AS mid_avg_max
    FROM Track
),
classified AS (
    SELECT
        t.TrackId,
        t.Milliseconds,
        t.Milliseconds / 60000.0 AS duration_minutes,
        CASE
            WHEN t.Milliseconds < s.mid_min_avg THEN 'Short'
            WHEN t.Milliseconds < s.mid_avg_max THEN 'Medium'
            ELSE 'Long'
        END AS category
    FROM Track t
    CROSS JOIN stats s
),
revenue AS (
    SELECT
        c.category,
        MIN(c.duration_minutes) AS min_minutes,
        MAX(c.duration_minutes) AS max_minutes,
        COALESCE(SUM(il.UnitPrice * il.Quantity), 0) AS total_revenue
    FROM classified c
    LEFT JOIN InvoiceLine il ON c.TrackId = il.TrackId
    GROUP BY c.category
)
SELECT category, min_minutes, max_minutes, total_revenue
FROM revenue
ORDER BY category
