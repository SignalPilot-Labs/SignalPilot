-- For male legislators from Louisiana, count distinct legislators actively serving
-- on December 31 of each year, where the number of years elapsed since their first term
-- is more than 30 and less than 50, grouped by the exact years elapsed.
WITH RECURSIVE
years(yr) AS (
    SELECT 1700
    UNION ALL
    SELECT yr + 1 FROM years WHERE yr < 2030
),
male_la_legislators AS (
    SELECT DISTINCT lt.id_bioguide
    FROM legislators_terms lt
    JOIN legislators l ON lt.id_bioguide = l.id_bioguide
    WHERE lt.state = 'LA' AND l.gender = 'M'
),
first_terms AS (
    SELECT
        lt.id_bioguide,
        MIN(lt.term_start) AS first_term_start,
        CAST(strftime('%Y', MIN(lt.term_start)) AS INTEGER) AS first_term_year
    FROM legislators_terms lt
    WHERE lt.id_bioguide IN (SELECT id_bioguide FROM male_la_legislators)
    GROUP BY lt.id_bioguide
),
active_dec31 AS (
    SELECT DISTINCT
        ft.id_bioguide,
        y.yr AS check_year,
        ft.first_term_year,
        y.yr - ft.first_term_year AS years_since
    FROM first_terms ft
    JOIN years y ON y.yr >= ft.first_term_year
    JOIN legislators_terms lt ON ft.id_bioguide = lt.id_bioguide AND lt.state = 'LA'
    WHERE date(y.yr || '-12-31') BETWEEN lt.term_start AND lt.term_end
)
SELECT years_since, COUNT(DISTINCT id_bioguide) AS num_legislators
FROM active_dec31
WHERE years_since > 30 AND years_since < 50
GROUP BY years_since
ORDER BY years_since
