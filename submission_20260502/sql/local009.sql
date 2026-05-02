-- ========== OUTPUT COLUMN SPEC ==========
-- 1. distance_km : the maximum Haversine distance (km) among all routes where Abakan (ABA) is departure or arrival
-- ========================================

-- INTERPRETATION: Find all unique flight routes where Abakan is either departure or arrival airport,
-- compute the great-circle distance (km) using the Haversine formula for each route,
-- and return the maximum distance.
-- EXPECTED: 1 row (single MAX value)

WITH airport_coords AS (
    SELECT
        airport_code,
        CAST(substr(coordinates, 2, instr(coordinates, ',') - 2) AS REAL) AS lon,
        CAST(substr(coordinates, instr(coordinates, ',') + 1, length(coordinates) - instr(coordinates, ',') - 1) AS REAL) AS lat
    FROM airports_data
),
abakan_routes AS (
    SELECT DISTINCT departure_airport, arrival_airport
    FROM flights
    WHERE departure_airport = 'ABA' OR arrival_airport = 'ABA'
),
route_distances AS (
    SELECT
        r.departure_airport,
        r.arrival_airport,
        2 * 6371 * asin(sqrt(
            sin((arr.lat - dep.lat) * 3.14159265358979 / 180 / 2) * sin((arr.lat - dep.lat) * 3.14159265358979 / 180 / 2) +
            cos(dep.lat * 3.14159265358979 / 180) * cos(arr.lat * 3.14159265358979 / 180) *
            sin((arr.lon - dep.lon) * 3.14159265358979 / 180 / 2) * sin((arr.lon - dep.lon) * 3.14159265358979 / 180 / 2)
        )) AS distance_km
    FROM abakan_routes r
    JOIN airport_coords dep ON r.departure_airport = dep.airport_code
    JOIN airport_coords arr ON r.arrival_airport = arr.airport_code
)
SELECT MAX(distance_km) AS distance_km
FROM route_distances
