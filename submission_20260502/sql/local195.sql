-- ========== OUTPUT COLUMN SPEC ==========
-- 1. customers_rented_top_actors : count of distinct customers who rented ≥1 film featuring any of the top 5 actors
-- 2. total_customers              : total count of distinct customers in the database
-- 3. percentage_of_customers      : % of total customers who rented films featuring top 5 actors
-- ========================================

-- INTERPRETATION: Find top 5 actors by total rental count, then compute what % of all customers
-- have rented at least one film featuring any of these actors.
-- EXPECTED: 1 row

WITH top_actors AS (
    SELECT a.actor_id
    FROM actor a
    JOIN film_actor fa ON a.actor_id = fa.actor_id
    JOIN inventory i ON fa.film_id = i.film_id
    JOIN rental r ON i.inventory_id = r.inventory_id
    GROUP BY a.actor_id
    ORDER BY COUNT(r.rental_id) DESC
    LIMIT 5
),
top_actor_films AS (
    SELECT DISTINCT film_id
    FROM film_actor
    WHERE actor_id IN (SELECT actor_id FROM top_actors)
),
customers_who_rented AS (
    SELECT DISTINCT r.customer_id
    FROM rental r
    JOIN inventory i ON r.inventory_id = i.inventory_id
    WHERE i.film_id IN (SELECT film_id FROM top_actor_films)
),
total_customers AS (
    SELECT COUNT(DISTINCT customer_id) AS total FROM customer
)
SELECT
    COUNT(DISTINCT cr.customer_id) AS customers_rented_top_actors,
    (SELECT total FROM total_customers) AS total_customers,
    ROUND(
        COUNT(DISTINCT cr.customer_id) * 100.0 / (SELECT total FROM total_customers),
        2
    ) AS percentage_of_customers
FROM customers_who_rented cr
