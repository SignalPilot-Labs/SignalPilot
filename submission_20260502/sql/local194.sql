WITH film_revenue AS (
    SELECT
        i.film_id,
        SUM(p.amount) AS total_film_revenue
    FROM payment p
    JOIN rental r ON p.rental_id = r.rental_id
    JOIN inventory i ON r.inventory_id = i.inventory_id
    GROUP BY i.film_id
),
actor_count AS (
    SELECT film_id, COUNT(actor_id) AS num_actors
    FROM film_actor
    GROUP BY film_id
),
actor_film_revenue AS (
    SELECT
        fa.actor_id,
        fa.film_id,
        fr.total_film_revenue / ac.num_actors AS actor_film_revenue
    FROM film_actor fa
    JOIN film_revenue fr ON fa.film_id = fr.film_id
    JOIN actor_count ac ON fa.film_id = ac.film_id
),
ranked AS (
    SELECT
        afr.actor_id,
        a.first_name || ' ' || a.last_name AS actor_name,
        afr.film_id,
        f.title,
        afr.actor_film_revenue,
        ROW_NUMBER() OVER (PARTITION BY afr.actor_id ORDER BY afr.actor_film_revenue DESC) AS rank
    FROM actor_film_revenue afr
    JOIN actor a ON afr.actor_id = a.actor_id
    JOIN film f ON afr.film_id = f.film_id
),
top3 AS (
    SELECT *
    FROM ranked
    WHERE rank <= 3
)
SELECT
    actor_id,
    actor_name,
    film_id,
    title,
    actor_film_revenue,
    rank,
    AVG(actor_film_revenue) OVER (PARTITION BY actor_id) AS avg_revenue_per_actor
FROM top3
ORDER BY actor_id, rank;
