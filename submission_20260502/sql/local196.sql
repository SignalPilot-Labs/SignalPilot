-- ========== OUTPUT COLUMN SPEC ==========
-- 1. rating                  : film rating category of the first movie rented by each customer
-- 2. avg_total_amount        : average total payment amount spent per customer in that group
-- 3. avg_subsequent_rentals  : average number of subsequent rentals (total rentals - 1) per customer
-- ========================================

-- INTERPRETATION: For each rating category of the first film rented (identified by the earliest
-- payment date per customer), compute the average total amount spent and the average number of
-- subsequent rentals (total rentals - 1) across all customers in that group.
-- EXPECTED: 5 rows (G, NC-17, PG, PG-13, R)

WITH first_payment AS (
  -- Identify earliest payment date per customer
  SELECT customer_id, MIN(payment_date) AS min_payment_date
  FROM payment
  GROUP BY customer_id
),
first_rental_rating AS (
  -- Get the film rating of the first rented film per customer (one row per customer)
  SELECT p.customer_id, MIN(f.rating) AS rating
  FROM payment p
  JOIN first_payment fp ON p.customer_id = fp.customer_id
                        AND p.payment_date = fp.min_payment_date
  JOIN rental r ON p.rental_id = r.rental_id
  JOIN inventory i ON r.inventory_id = i.inventory_id
  JOIN film f ON i.film_id = f.film_id
  GROUP BY p.customer_id
),
customer_stats AS (
  -- Total amount paid and total distinct rentals per customer
  SELECT customer_id,
         SUM(amount) AS total_amount,
         COUNT(DISTINCT rental_id) AS total_rentals
  FROM payment
  GROUP BY customer_id
)
SELECT
  frr.rating,
  AVG(cs.total_amount) AS avg_total_amount,
  AVG(cs.total_rentals - 1) AS avg_subsequent_rentals
FROM first_rental_rating frr
JOIN customer_stats cs ON frr.customer_id = cs.customer_id
GROUP BY frr.rating
ORDER BY frr.rating
