WITH filtered_customers AS (
    SELECT c.customer_id
    FROM customer c
    JOIN address a ON c.address_id = a.address_id
    JOIN city ci ON a.city_id = ci.city_id
    WHERE ci.city LIKE 'A%' OR ci.city LIKE '%-%'
),
rental_hours_by_category AS (
    SELECT
        cat.name AS category_name,
        SUM((julianday(r.return_date) - julianday(r.rental_date)) * 24) AS total_rental_hours
    FROM rental r
    JOIN filtered_customers fc ON r.customer_id = fc.customer_id
    JOIN inventory i ON r.inventory_id = i.inventory_id
    JOIN film_category fc2 ON i.film_id = fc2.film_id
    JOIN category cat ON fc2.category_id = cat.category_id
    WHERE r.return_date IS NOT NULL
    GROUP BY cat.category_id, cat.name
)
SELECT category_name, total_rental_hours
FROM rental_hours_by_category
ORDER BY total_rental_hours DESC
LIMIT 1;
