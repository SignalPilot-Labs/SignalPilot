-- INTERPRETATION: Sort all rows in olist_geolocation by (state, city, zip, lat, lng).
-- For each row, compute the Spherical Law of Cosines distance to the previous row.
-- Return the two consecutive city names with the maximum such distance.

-- EXPECTED: 1 row (the single pair with greatest distance)

WITH ordered AS (
  SELECT
    geolocation_state,
    geolocation_city,
    geolocation_lat,
    geolocation_lng,
    LAG(geolocation_lat) OVER (ORDER BY geolocation_state, geolocation_city, geolocation_zip_code_prefix, geolocation_lat, geolocation_lng) AS prev_lat,
    LAG(geolocation_lng) OVER (ORDER BY geolocation_state, geolocation_city, geolocation_zip_code_prefix, geolocation_lat, geolocation_lng) AS prev_lng,
    LAG(geolocation_city) OVER (ORDER BY geolocation_state, geolocation_city, geolocation_zip_code_prefix, geolocation_lat, geolocation_lng) AS prev_city,
    LAG(geolocation_state) OVER (ORDER BY geolocation_state, geolocation_city, geolocation_zip_code_prefix, geolocation_lat, geolocation_lng) AS prev_state
  FROM olist_geolocation
),
distances AS (
  SELECT
    prev_state AS city1_state,
    prev_city AS city1,
    geolocation_state AS city2_state,
    geolocation_city AS city2,
    6371.0 * acos(
      MIN(1.0, MAX(-1.0,
        cos(prev_lat * acos(-1.0) / 180.0) * cos(geolocation_lat * acos(-1.0) / 180.0) * cos((geolocation_lng - prev_lng) * acos(-1.0) / 180.0)
        + sin(prev_lat * acos(-1.0) / 180.0) * sin(geolocation_lat * acos(-1.0) / 180.0)
      ))
    ) AS distance_km
  FROM ordered
  WHERE prev_lat IS NOT NULL
)
SELECT city1, city2
FROM distances
ORDER BY distance_km DESC
LIMIT 1;
