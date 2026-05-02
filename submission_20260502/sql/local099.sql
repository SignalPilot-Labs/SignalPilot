-- ========== OUTPUT COLUMN SPEC ==========
-- 1. actor_count : COUNT of actors whose most-collaborated director is Yash Chopra
--                  (i.e., more films with Yash Chopra than with any other single director)
-- ========================================

-- INTERPRETATION: For each actor, count films with each director.
-- Find actors where Yash Chopra's film count is STRICTLY MORE than the max
-- film count with any other single director. Return the count of such actors.

-- EXPECTED: 1 row (single integer count)

WITH actor_director_films AS (
    SELECT
        TRIM(c.PID) AS actor_pid,
        d.PID AS director_pid,
        COUNT(*) AS film_count
    FROM M_Cast c
    JOIN M_Director d ON c.MID = d.MID
    GROUP BY TRIM(c.PID), d.PID
),
-- Films each actor made with Yash Chopra specifically
yash_films AS (
    SELECT actor_pid, film_count AS yash_film_count
    FROM actor_director_films
    WHERE director_pid = 'nm0007181'  -- Yash Chopra's PID
),
-- Max films each actor made with any director OTHER than Yash Chopra
other_max AS (
    SELECT actor_pid, MAX(film_count) AS other_max_count
    FROM actor_director_films
    WHERE director_pid != 'nm0007181'
    GROUP BY actor_pid
)
-- Count actors where Yash Chopra collaboration count is STRICTLY MORE than with any other director
SELECT COUNT(*) AS actor_count
FROM yash_films yf
LEFT JOIN other_max om ON yf.actor_pid = om.actor_pid
WHERE yf.yash_film_count > COALESCE(om.other_max_count, 0)
