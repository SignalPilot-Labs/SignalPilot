-- ========== OUTPUT COLUMN SPEC ==========
-- 1. store_id      : store identifier (from staff.store_id via rental.staff_id)
-- 2. year          : the year with the highest rental count for that store
-- 3. month         : the month (in that year) with the highest rental count
-- 4. total_rentals : count of rentals for that store/year/month combination
-- ========================================
-- EXPECTED: 2 rows (one per store)
-- INTERPRETATION: For each store, find the single year+month combo where its staff
--                 processed the most rentals. Staff are assigned to stores via staff.store_id.

WITH monthly_rentals AS (
    SELECT
        s.store_id,
        CAST(strftime('%Y', r.rental_date) AS INTEGER) AS year,
        CAST(strftime('%m', r.rental_date) AS INTEGER) AS month,
        COUNT(*) AS total_rentals
    FROM rental r
    JOIN staff s ON r.staff_id = s.staff_id
    GROUP BY s.store_id, strftime('%Y', r.rental_date), strftime('%m', r.rental_date)
),
ranked AS (
    SELECT *,
        ROW_NUMBER() OVER (PARTITION BY store_id ORDER BY total_rentals DESC) AS rn
    FROM monthly_rentals
)
SELECT store_id, year, month, total_rentals
FROM ranked
WHERE rn = 1
ORDER BY store_id
