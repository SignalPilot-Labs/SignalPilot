-- ========== OUTPUT COLUMN SPEC ==========
-- 1. num_pairs : count of unique city pairs in the distance range with the fewest pairs
-- ========================================

-- INTERPRETATION: For each unique unordered city pair, compute average Haversine distance
-- of all routes between them. Bucket into ranges [0,1000), [1000,2000), ..., [5000,6000), [6000+).
-- Count pairs per bucket, return the count for the bucket with the fewest pairs.

-- EXPECTED: 1 row (single aggregate value)

WITH airport_coords AS (
    SELECT
        airport_code,
        json_extract(city, '$.en') AS city_name,
        CAST(SUBSTR(coordinates, 2, INSTR(coordinates, ',') - 2) AS REAL) AS lon,
        CAST(SUBSTR(coordinates, INSTR(coordinates, ',') + 1, LENGTH(coordinates) - INSTR(coordinates, ',') - 1) AS REAL) AS lat
    FROM airports_data
),
flight_distances AS (
    SELECT
        CASE WHEN a1.city_name <= a2.city_name THEN a1.city_name ELSE a2.city_name END AS city1,
        CASE WHEN a1.city_name <= a2.city_name THEN a2.city_name ELSE a1.city_name END AS city2,
        2 * 6371 * asin(sqrt(
            sin((a2.lat * 3.14159265358979 / 180 - a1.lat * 3.14159265358979 / 180) / 2) *
            sin((a2.lat * 3.14159265358979 / 180 - a1.lat * 3.14159265358979 / 180) / 2) +
            cos(a1.lat * 3.14159265358979 / 180) * cos(a2.lat * 3.14159265358979 / 180) *
            sin((a2.lon * 3.14159265358979 / 180 - a1.lon * 3.14159265358979 / 180) / 2) *
            sin((a2.lon * 3.14159265358979 / 180 - a1.lon * 3.14159265358979 / 180) / 2)
        )) AS distance_km
    FROM flights f
    JOIN airport_coords a1 ON f.departure_airport = a1.airport_code
    JOIN airport_coords a2 ON f.arrival_airport = a2.airport_code
    WHERE a1.city_name != a2.city_name
),
city_pair_avg AS (
    SELECT city1, city2, AVG(distance_km) AS avg_distance
    FROM flight_distances
    GROUP BY city1, city2
),
city_pair_ranges AS (
    SELECT
        CASE
            WHEN avg_distance < 1000 THEN 0
            WHEN avg_distance < 2000 THEN 1000
            WHEN avg_distance < 3000 THEN 2000
            WHEN avg_distance < 4000 THEN 3000
            WHEN avg_distance < 5000 THEN 4000
            WHEN avg_distance < 6000 THEN 5000
            ELSE 6000
        END AS distance_range
    FROM city_pair_avg
),
range_counts AS (
    SELECT distance_range, COUNT(*) AS pair_count
    FROM city_pair_ranges
    GROUP BY distance_range
)
SELECT MIN(pair_count) AS num_pairs
FROM range_counts;
