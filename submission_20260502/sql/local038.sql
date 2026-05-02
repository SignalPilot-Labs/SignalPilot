-- ========== OUTPUT COLUMN SPEC ==========
-- 1. actor_full_name : full name (first_name || ' ' || last_name) of the actor
--                      appearing most in qualifying English-language Children films
--                      rated G or PG, length <= 120, released 2000-2010
-- ========================================
-- INTERPRETATION: Find the actor with the most appearances in films that are:
--   - In English language (language.name = 'English')
--   - In 'Children' category
--   - Rated 'G' or 'PG'
--   - Running time <= 120 minutes
--   - Released between 2000 and 2010 (inclusive)
-- EXPECTED: 1 row (the single top actor)
SELECT a.first_name || ' ' || a.last_name AS actor_full_name
FROM film f
JOIN language l ON f.language_id = l.language_id
JOIN film_category fc ON f.film_id = fc.film_id
JOIN category c ON fc.category_id = c.category_id
JOIN film_actor fa ON f.film_id = fa.film_id
JOIN actor a ON fa.actor_id = a.actor_id
WHERE TRIM(l.name) = 'English'
  AND c.name = 'Children'
  AND f.rating IN ('G', 'PG')
  AND f.length <= 120
  AND CAST(f.release_year AS INTEGER) BETWEEN 2000 AND 2010
GROUP BY a.actor_id, a.first_name, a.last_name
ORDER BY COUNT(*) DESC
LIMIT 1
