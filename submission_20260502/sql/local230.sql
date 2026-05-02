-- ========== OUTPUT COLUMN SPEC ==========
-- 1. rank           : explicit rank position (1-4) among top directors
-- 2. director_name  : name of the director (from names.name)
-- 3. movie_count    : count of distinct movies rated above 8 within top 3 genres
-- ========================================
-- EXPECTED: 4 rows (top 4 directors)
-- INTERPRETATION: Find top 3 genres by count of distinct movies with avg_rating > 8,
-- then within those genres find the top 4 directors by count of movies with avg_rating > 8.

WITH top_genres AS (
    SELECT g.genre
    FROM genre g
    JOIN ratings r ON g.movie_id = r.movie_id
    WHERE r.avg_rating > 8
    GROUP BY g.genre
    ORDER BY COUNT(DISTINCT g.movie_id) DESC
    LIMIT 3
),
director_counts AS (
    SELECT n.name AS director_name, COUNT(DISTINCT dm.movie_id) AS movie_count
    FROM director_mapping dm
    JOIN genre g ON dm.movie_id = g.movie_id
    JOIN ratings r ON dm.movie_id = r.movie_id
    JOIN top_genres tg ON g.genre = tg.genre
    JOIN names n ON dm.name_id = n.id
    WHERE r.avg_rating > 8
    GROUP BY dm.name_id, n.name
    ORDER BY movie_count DESC
    LIMIT 4
)
SELECT ROW_NUMBER() OVER (ORDER BY movie_count DESC) AS rank,
       director_name,
       movie_count
FROM director_counts
ORDER BY rank
