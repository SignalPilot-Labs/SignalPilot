-- ========== OUTPUT COLUMN SPEC ==========
-- 1. director_id              : Director's primary key (names.id)
-- 2. director_name            : Director's display name (names.name)
-- 3. movie_count              : Number of movies directed (COUNT)
-- 4. avg_inter_movie_duration : Average days between consecutive movie releases (ROUND to nearest int)
-- 5. avg_rating               : Average avg_rating of director's movies (ROUND to 2 decimals)
-- 6. total_votes              : Sum of total_votes across director's movies
-- 7. min_rating               : Minimum avg_rating across director's movies
-- 8. max_rating               : Maximum avg_rating across director's movies
-- 9. total_duration           : Sum of movie duration across director's movies
-- ========================================

-- EXPECTED: 9 rows (top 9 directors by movie count, then total duration)
-- INTERPRETATION: For each director, compute movie count, average gap in days between
-- consecutive movies sorted by date_published, average/min/max rating, total votes,
-- and total movie duration. Return top 9, sorted by movie_count DESC, total_duration DESC.

WITH director_movies AS (
    SELECT
        dm.name_id AS director_id,
        n.name AS director_name,
        m.id AS movie_id,
        m.date_published,
        m.duration,
        r.avg_rating,
        r.total_votes
    FROM director_mapping dm
    JOIN names n ON dm.name_id = n.id
    JOIN movies m ON dm.movie_id = m.id
    LEFT JOIN ratings r ON m.id = r.movie_id
),
movie_with_lag AS (
    SELECT
        director_id,
        director_name,
        movie_id,
        date_published,
        duration,
        avg_rating,
        total_votes,
        LAG(date_published) OVER (PARTITION BY director_id ORDER BY date_published) AS prev_date
    FROM director_movies
),
inter_durations AS (
    SELECT
        director_id,
        director_name,
        duration,
        avg_rating,
        total_votes,
        CASE
            WHEN prev_date IS NOT NULL
            THEN julianday(date_published) - julianday(prev_date)
            ELSE NULL
        END AS inter_movie_days
    FROM movie_with_lag
),
director_stats AS (
    SELECT
        director_id,
        director_name,
        COUNT(*) AS movie_count,
        ROUND(AVG(inter_movie_days)) AS avg_inter_movie_duration,
        ROUND(AVG(avg_rating), 2) AS avg_rating,
        SUM(total_votes) AS total_votes,
        MIN(avg_rating) AS min_rating,
        MAX(avg_rating) AS max_rating,
        SUM(duration) AS total_duration
    FROM inter_durations
    GROUP BY director_id, director_name
)
SELECT *
FROM director_stats
ORDER BY movie_count DESC, total_duration DESC
LIMIT 9;
