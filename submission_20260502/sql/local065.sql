-- EXPECTED: 1 row (total income)
-- INTERPRETATION: Sum pizza prices ($12 Meatlovers, $10 Vegetarian) + $1 per extra topping, for non-canceled orders only

WITH non_cancelled AS (
    SELECT order_id
    FROM pizza_clean_runner_orders
    WHERE cancellation IS NULL
),
order_income AS (
    SELECT
        co.order_id,
        co.pizza_id,
        co.extras,
        CASE WHEN co.pizza_id = 1 THEN 12 ELSE 10 END AS base_price,
        CASE
            WHEN co.extras IS NULL OR co.extras = '' THEN 0
            ELSE length(co.extras) - length(replace(co.extras, ',', '')) + 1
        END AS extra_count
    FROM pizza_clean_customer_orders co
    INNER JOIN non_cancelled nc ON co.order_id = nc.order_id
)
SELECT SUM(base_price + extra_count) AS total_income
FROM order_income
